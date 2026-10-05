"""Live eval: run labelled lines through the real pipeline with a real decision model and sweep the thresholds.

	uv run python evals/run_eval.py evals/cases_tune.json evals/cases_holdout.json

Uses SECRET_GUARD_BASE_URL / SECRET_GUARD_MODEL like the CLI (default http://localhost:11435). Choose thresholds on the
tuning set; report them on the held-out set. Cases are synthetic: no real credential is in these files.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time

from smart_commit_guard.config import Config
from smart_commit_guard.decider import Decider, HttpDecider
from smart_commit_guard.policy import scan
from smart_commit_guard.rules import scan_line
from smart_commit_guard.skip import is_example_path
from smart_commit_guard.types import AddedLine


class Recording:
	"""Delegates to the real decider and remembers every answer, so the threshold sweep costs no extra calls."""

	def __init__(self, inner: Decider):
		self.inner, self.cache, self.latencies = inner, {}, []

	def judge(self, items):
		t = time.perf_counter()
		ps = self.inner.judge(items)
		self.latencies.append((time.perf_counter() - t, len(items)))
		self.cache.update(zip(items, ps))
		return ps


class Cached:
	def __init__(self, cache):
		self.cache = cache

	def judge(self, items):
		return [self.cache[i] for i in items]


def outcome(line: AddedLine, decider: Decider, block_at: float, warn_at: float) -> str:
	r = scan([line], decider, block_at=block_at, warn_at=warn_at)
	return "block" if r.exit_code else "warn" if r.findings else "pass"


def stage(c: dict) -> str:
	hit = scan_line(c["text"])
	if hit is None:
		return "no-hit"
	return "rule-block" if hit.high_confidence and not is_example_path(c["path"]) else "model"


def metrics(cases, lines, decider, block_at, warn_at):
	out = [outcome(l, decider, block_at, warn_at) for l in lines]
	real = [o for c, o in zip(cases, out) if c["label"] == "real"]
	ok = [o for c, o in zip(cases, out) if c["label"] == "ok"]
	tp, fp = real.count("block"), ok.count("block")
	return {"block_at": block_at, "warn_at": warn_at, "recall": tp / len(real), "precision": tp / (tp + fp) if tp + fp else 1.0,
			"fp_rate": fp / len(ok), "missed": len(real) - tp, "false_blocks": fp, "warned_ok": ok.count("warn"),
			"warned_real": real.count("warn")}


def main(paths: list[str]) -> None:
	cfg = Config.from_env(os.environ | {"SECRET_GUARD_MODEL": os.environ.get("SECRET_GUARD_MODEL", "jevk5:4b")})
	rec = Recording(HttpDecider(cfg.base_url, cfg.model, 60.0, cfg.api_key))
	report = {}
	for path in paths:
		with open(path) as f:
			cases = json.load(f)
		lines = [AddedLine(c["path"], i + 1, c["text"]) for i, c in enumerate(cases)]
		scan(lines, rec, block_at=0.5, warn_at=0.5)          # one live pass fills the cache (<= 5 batches of 30)
		cached = Cached(rec.cache)
		stages = [stage(c) for c in cases]
		print(f"\n== {path}: {len(cases)} cases, {sum(c['label'] == 'real' for c in cases)} real")
		print("stages:", {s: stages.count(s) for s in set(stages)})
		missed_by_rules = [c for c, s in zip(cases, stages) if s == "no-hit" and c["label"] == "real"]
		print(f"real secrets the rules never surface (cannot be caught): {len(missed_by_rules)}")
		for c in missed_by_rules:
			print("   ", c["path"], c["text"][:80])
		ps = {"real": [], "ok": []}
		for c, l, st in zip(cases, lines, stages):
			if st == "model":
				ps[c["label"]].append(rec.cache[(l.path, l.text)])
		for k, v in ps.items():
			print(f"model p on {k}: " + " ".join(f"{x:.2f}" for x in sorted(v)))
		rows = [metrics(cases, lines, cached, b, w) for b in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.85) for w in (0.05, 0.1, 0.2)
				if w <= b]
		print(f"{'block':>6} {'warn':>5} {'recall':>7} {'prec':>6} {'fp_rate':>8} {'missed':>6} {'fblock':>6} {'warn_ok':>7} {'warn_real':>9}")
		for r in rows:
			print(f"{r['block_at']:6.2f} {r['warn_at']:5.2f} {r['recall']:7.2f} {r['precision']:6.2f} {r['fp_rate']:8.2f} "
				  f"{r['missed']:6d} {r['false_blocks']:6d} {r['warned_ok']:7d} {r['warned_real']:9d}")
		report[path] = {"rows": rows, "p": {f"{k[0]}|{k[1]}": v for k, v in rec.cache.items()}}
	if rec.latencies:
		per_item = [t / n for t, n in rec.latencies]
		print(f"\nmodel calls: {len(rec.latencies)}, median {statistics.median(t for t, _ in rec.latencies) * 1000:.0f} ms/call, "
			  f"{statistics.median(per_item) * 1000:.0f} ms/item")
	with open("evals/last_run.json", "w") as f:
		json.dump(report, f, indent="\t")


if __name__ == "__main__":
	main(sys.argv[1:] or ["evals/cases_tune.json", "evals/cases_holdout.json"])
