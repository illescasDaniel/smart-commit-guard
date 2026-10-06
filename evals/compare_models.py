"""Compare decision models on every eval set: scores, latency and GPU memory.

	python evals/compare_models.py run jevk5:4b [--small]   # writes evals/models/scores_<model>.json
	python evals/compare_models.py report [--small]      # reads every scores file, prints the tables, writes evals/models/report.md

`run` unloads every other model first, measures the GPU memory before loading and its peak while judging, and records each
call's latency. `report` fits one threshold per model on the `tune` half (the highest threshold that keeps the false-block rate
at or under 2 % there) and scores it on the `test` half, with bootstrap 95 % intervals. Thresholds are per model, so AUC is
the comparison that does not depend on them.
"""
from __future__ import annotations

import json
import os
import random
import statistics
import subprocess
import sys
import threading
import time
from functools import partial
from pathlib import Path
from typing import Any

from smart_commit_guard.config import Config
from smart_commit_guard.decider import HttpDecider

HERE = Path(__file__).parent
OUT = HERE / "models"


def load_cases(small: bool = False) -> list[dict]:
	"""Every labelled model-stage line from all sets. Hand-written sets: `tune` stays tune, `holdout` is test. Generated cases
	carry their template split. The OSS lines are split by package (even / odd hash), so no package is in both halves."""
	cases: list[dict] = []
	for name, split in (("cases_tune.json", "tune"), ("cases_holdout.json", "test")):
		for c in json.loads(Path(HERE / name).read_text(encoding="utf-8")):
			if c["stage"] == "model":
				cases.append({**c, "set": name.split(".")[0], "split": split, "family": "hand-written", "template": "-"})
	if small:   # the hand-written sets only: the screening round
		return cases
	for c in json.loads(Path(HERE / "cases_generated.json").read_text(encoding="utf-8")):
		cases.append({**c, "set": "generated"})
	oss = HERE / "cases_oss.json"
	if oss.exists():
		for c in json.loads(Path(oss).read_text(encoding="utf-8")):
			split = "tune" if sum(map(ord, c["source"])) % 2 == 0 else "test"
			cases.append({**c, "set": "oss", "split": split, "family": "oss-ok", "template": c["source"]})
	return cases


def _gpu_used_mib() -> int:
	out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=False).stdout
	return int(out.split()[0])


def _loaded_models() -> list[str]:
	out = subprocess.run(["ollaya", "ps"], capture_output=True, text=True, check=False).stdout.splitlines()[1:]
	return [l.split()[0] for l in out if l.strip()]


def _server_rss_mib() -> int | None:
	out = subprocess.run(["pgrep", "-f", "ollaya serve"], capture_output=True, text=True, check=False).stdout.split()
	if not out:
		return None
	return sum(int(Path(f"/proc/{p}/statm").read_text().split()[1]) * 4096 for p in out if Path(f"/proc/{p}/statm").exists()) // (1 << 20)


class GpuSampler(threading.Thread):
	def __init__(self) -> None:
		super().__init__(daemon=True)
		self.peak, self._stop_flag = 0, threading.Event()

	def run(self) -> None:
		while not self._stop_flag.is_set():
			self.peak = max(self.peak, _gpu_used_mib())
			time.sleep(0.05)

	def stop(self) -> int:
		self._stop_flag.set()
		self.join()
		return self.peak


def run(model: str, small: bool = False) -> None:
	for m in _loaded_models():
		subprocess.run(["ollaya", "stop", m], capture_output=True, check=False)
	time.sleep(3)
	idle = _gpu_used_mib()
	cfg = Config.from_env(os.environ | {"SECRET_GUARD_MODEL": model})
	decider = HttpDecider(cfg.base_url, model, 120.0, cfg.api_key)
	cases = load_cases(small)
	items = list(dict.fromkeys((c["path"], c["text"]) for c in cases))
	sampler = GpuSampler()
	sampler.start()
	t0 = time.perf_counter()
	decider.judge([items[0]])
	cold = time.perf_counter() - t0
	rss_loaded = _server_rss_mib()
	scores, lat = {}, []
	for it in items:
		t = time.perf_counter()
		scores[f"{it[0]}|{it[1]}"] = decider.judge([it])[0]
		lat.append(time.perf_counter() - t)
	peak = sampler.stop()
	steady = _gpu_used_mib()
	OUT.mkdir(exist_ok=True)
	row = {"model": model, "items": len(items), "cold_start_s": cold, "latency_ms": [x * 1000 for x in lat], "gpu_idle_mib": idle,
		   "gpu_peak_mib": peak, "gpu_loaded_mib": steady, "server_rss_mib": rss_loaded, "scores": scores, "size": _model_size(model)}
	(OUT / f"{'small' if small else 'scores'}_{model.replace(':', '_')}.json").write_text(json.dumps(row))
	print(f"{model}: {len(items)} items, cold start {cold:.1f}s, median {statistics.median(lat) * 1000:.0f} ms, "
		  f"GPU {idle} -> peak {peak} MiB (+{peak - idle}), loaded {steady} MiB, server RSS {rss_loaded} MiB")


def _model_size(model: str) -> str:
	for line in subprocess.run(["ollaya", "list"], capture_output=True, text=True, check=False).stdout.splitlines():
		if line.split() and line.split()[0] == model:
			return " ".join(line.split()[2:4])
	return "?"


# --- report

def auc(pos: list[float], neg: list[float]) -> float:
	if not pos or not neg:
		return float("nan")
	return sum((a > b) + 0.5 * (a == b) for a in pos for b in neg) / (len(pos) * len(neg))


def fit_threshold(rows: list[tuple[float, bool]], max_fpr: float = 0.02) -> float:
	"""The lowest threshold whose false-block rate on `rows` (p, is_real) is at most `max_fpr`: the most recall that stays quiet."""
	neg = sorted(p for p, real in rows if not real)
	if not neg:
		return 0.5
	allowed = int(len(neg) * max_fpr)
	cut = neg[-(allowed + 1)] if allowed < len(neg) else 0.0   # at most `allowed` negatives are above it
	return min(0.99, cut + 1e-6)


def metrics(rows: list[tuple[float, bool]], threshold: float) -> dict:
	pos = [p for p, r in rows if r]
	neg = [p for p, r in rows if not r]
	tp = sum(p >= threshold for p in pos)
	fp = sum(p >= threshold for p in neg)
	return {"auc": auc(pos, neg), "recall": tp / len(pos) if pos else float("nan"), "fpr": fp / len(neg) if neg else float("nan"),
			"precision": tp / (tp + fp) if tp + fp else 1.0}


def bootstrap(rows: list[tuple[float, bool]], threshold: float, n: int = 1000) -> dict[str, tuple[float, float]]:
	rng = random.Random(5)
	draws: dict[str, list[float]] = {"auc": [], "recall": [], "fpr": []}
	for _ in range(n):
		sample = [rows[rng.randrange(len(rows))] for _ in rows]
		m = metrics(sample, threshold)
		for k, values in draws.items():
			if m[k] == m[k]:   # not NaN
				values.append(m[k])
	return {k: (sorted(v)[int(0.025 * len(v))], sorted(v)[int(0.975 * len(v)) - 1]) for k, v in draws.items() if v}


def _rows(cases: list[dict], sc: dict, pred) -> list[tuple[float, bool]]:
	return [(sc[f"{c['path']}|{c['text']}"], c["label"] == "real") for c in cases if pred(c)]


def report(small: bool = False) -> None:
	cases = load_cases(small)
	files = sorted(OUT.glob("small_*.json" if small else "scores_*.json"))
	runs = [json.loads(Path(f).read_text(encoding="utf-8")) for f in files]
	lines = []
	def say(s: str = "") -> None:
		print(s)
		lines.append(s)
	n_real = sum(c["label"] == "real" for c in cases)
	say(f"# Model comparison\n\n{len(cases)} lines that reach the model: {n_real} real, {len(cases) - n_real} ok "
		f"({sum(c['set'] == 'oss' for c in cases)} from open-source packages, {sum(c['set'] == 'generated' for c in cases)} generated, "
		f"{sum(c['family'] == 'hand-written' for c in cases)} hand-written).\n")
	summary: list[dict[str, Any]] = []
	for run_ in runs:
		sc = run_["scores"]
		rows_of = partial(_rows, cases, sc)
		tune, test, allr = rows_of(lambda c: c["split"] == "tune"), rows_of(lambda c: c["split"] == "test"), rows_of(lambda c: True)
		thr = fit_threshold(tune)
		m_test, ci = metrics(test, thr), bootstrap(test, thr)
		lat = sorted(run_["latency_ms"])
		summary.append({"model": run_["model"], "size": run_["size"], "auc": metrics(allr, thr)["auc"], "auc_test": m_test["auc"], "ci": ci,
						"thr": thr, "recall": m_test["recall"], "fpr": m_test["fpr"], "p50": statistics.median(lat),
						"p95": lat[int(0.95 * len(lat)) - 1], "vram": run_["gpu_peak_mib"] - run_["gpu_idle_mib"],
						"loaded": run_["gpu_loaded_mib"] - run_["gpu_idle_mib"], "cold": run_["cold_start_s"], "rss": run_["server_rss_mib"],
						"at_default": metrics(test, 0.5), "run": run_, "rows": rows_of})
	say("## Summary (test half: held-out templates, held-out OSS packages, held-out hand-written set)\n")
	say("Threshold fitted on the tune half at <= 2 % false blocks. Intervals: bootstrap 95 %.\n")
	say("| model | disk | AUC (all) | AUC test [95 %] | threshold | recall test [95 %] | false blocks test [95 %] | recall @0.5 | false @0.5 | p50 ms | p95 ms | VRAM peak MiB | VRAM loaded MiB | cold start s |")
	say("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
	for s in sorted(summary, key=lambda s: -s["auc_test"]):
		ci = s["ci"]
		say(f"| `{s['model']}` | {s['size']} | {s['auc']:.3f} | {s['auc_test']:.3f} [{ci['auc'][0]:.3f}, {ci['auc'][1]:.3f}] | {s['thr']:.2f} | "
			f"{s['recall']:.3f} [{ci['recall'][0]:.3f}, {ci['recall'][1]:.3f}] | {s['fpr']:.3f} [{ci['fpr'][0]:.3f}, {ci['fpr'][1]:.3f}] | "
			f"{s['at_default']['recall']:.3f} | {s['at_default']['fpr']:.3f} | {s['p50']:.0f} | {s['p95']:.0f} | +{s['vram']} | +{s['loaded']} | {s['cold']:.1f} |")
	say("\n## Recall by family at each model's fitted threshold (test half)\n")
	fams = sorted({c["family"] for c in cases if c["label"] == "real" and c["split"] == "test"})
	say("| family | n | " + " | ".join(f"`{s['model']}`" for s in summary) + " |")
	say("|---|---|" + "---|" * len(summary))
	for fam in fams:
		n = sum(c["family"] == fam and c["split"] == "test" and c["label"] == "real" for c in cases)
		cells = []
		for s in summary:
			r = s["rows"](lambda c, fam=fam: c["family"] == fam and c["split"] == "test")
			cells.append(f"{sum(p >= s['thr'] for p, _ in r) / len(r):.2f}")
		say(f"| {fam} | {n} | " + " | ".join(cells) + " |")
	say("\n## False blocks by source of `ok` lines at each model's fitted threshold (test half)\n")
	say("| source | n | " + " | ".join(f"`{s['model']}`" for s in summary) + " |")
	say("|---|---|" + "---|" * len(summary))
	for src in ("hand-written", "generated", "oss"):
		pred = (lambda c, src=src: c["label"] == "ok" and c["split"] == "test" and (c["family"] == "hand-written" if src == "hand-written" else c["set"] == src))
		n = sum(pred(c) for c in cases)
		cells = []
		for s in summary:
			r = s["rows"](pred)
			cells.append(f"{sum(p >= s['thr'] for p, _ in r)}")
		say(f"| {src} | {n} | " + " | ".join(cells) + " |")
	(OUT / ("report_small.md" if small else "report.md")).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
	small = "--small" in sys.argv
	args = [a for a in sys.argv[1:] if a != "--small"]
	if len(args) == 2 and args[0] == "run":
		run(args[1], small)
	elif args == ["report"]:
		report(small)
	else:
		sys.exit(__doc__)
