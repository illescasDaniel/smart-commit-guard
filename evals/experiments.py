"""Prompt experiments on one model: `python evals/experiments.py MODEL` writes evals/models/experiments_<model>.md.

Variants: the shipped question, without `criteria`, with the file path named in the instructions, and with one line of
context before and after the candidate (real neighbouring lines for the open-source cases, a fixed benign pair for the
synthetic ones, which have no file around them). The scores of each variant go through the same protocol as compare_models.
"""
from __future__ import annotations

import glob
import json
import os
import statistics
import sys
from pathlib import Path

from compare_models import OUT, bootstrap, fit_threshold, load_cases, metrics

from smart_commit_guard.config import Config
from smart_commit_guard.decider import _question, _urllib_post

BEFORE, AFTER = "import os", "def main():"   # neighbours for lines that have no file around them
UV = os.path.expanduser("~/.cache/uv/archive-v0")


def neighbours(c: dict) -> tuple[str, str]:
	if c["set"] != "oss":
		return BEFORE, AFTER
	for root in ("/usr/lib/python3.14/site-packages", "/usr/lib/node_modules", *glob.glob(f"{UV}/*")):
		p = Path(root) / c["path"]
		if p.is_file():
			try:
				lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
				i = next(i for i, ln in enumerate(lines) if ln == c["text"])
				return (lines[i - 1][:200] if i else ""), (lines[i + 1][:200] if i + 1 < len(lines) else "")
			except (OSError, StopIteration):
				continue
	return "", ""


def ece(rows: list[tuple[float, bool]], bins: int = 10) -> float:
	total = 0.0
	for b in range(bins):
		sel = [(s, y) for s, y in rows if min(int(s * bins), bins - 1) == b]
		if sel:
			total += len(sel) / len(rows) * abs(statistics.fmean(s for s, _ in sel) - statistics.fmean(y for _, y in sel))
	return total


def question(variant: str, c: dict) -> dict:
	q = _question(0)
	if variant == "no_criteria":
		del q["criteria"]
	elif variant == "path":
		q["instructions"] = f"The file is `{c['path']}`. " + q["instructions"]
	elif variant == "context":
		q["instructions"] += " The lines before and after are context only."
	return q


def main(model: str) -> None:
	cfg = Config.from_env(os.environ | {"SECRET_GUARD_MODEL": model})
	url = cfg.base_url.rstrip("/") + "/v1/systemone"
	cases = load_cases()
	ctx = {(c["path"], c["text"]): neighbours(c) for c in cases}
	scores: dict[str, dict[str, float]] = {}
	for variant in ("baseline", "no_criteria", "path", "context"):
		scores[variant] = {}
		for c in cases:
			item = {"path": c["path"], "line": c["text"][:1000]}
			if variant == "context":
				item["before"], item["after"] = ctx[(c["path"], c["text"])]
			payload = {"state": {"items": [item]}, "questions": {"item_0": question(variant, c)}, "model": model}
			scores[variant][f"{c['path']}|{c['text']}"] = float(_urllib_post(url, payload, 120.0, {})["answers"]["item_0"]["noul"])
		print(variant, "done", file=sys.stderr)
	lines = [f"# Prompt experiments on `{model}` ({len(cases)} lines)\n",
			 "| variant | AUC test [95 %] | threshold | recall test | false blocks test | ECE (all) |", "|---|---|---|---|---|---|"]
	for variant, sc in scores.items():
		def rows(split: str | None, sc: dict[str, float] = sc) -> list[tuple[float, bool]]:
			return [(sc[f"{c['path']}|{c['text']}"], c["label"] == "real") for c in cases if split is None or c["split"] == split]
		thr = fit_threshold(rows("tune"))
		m, ci = metrics(rows("test"), thr), bootstrap(rows("test"), thr)
		lines.append(f"| {variant} | {m['auc']:.3f} [{ci['auc'][0]:.3f}, {ci['auc'][1]:.3f}] | {thr:.2f} | {m['recall']:.3f} | {m['fpr']:.3f} | {ece(rows(None)):.3f} |")
	text = "\n".join(lines) + "\n"
	(OUT / f"experiments_{model.replace(':', '_')}.md").write_text(text, encoding="utf-8")
	(OUT / f"experiments_{model.replace(':', '_')}.json").write_text(json.dumps(scores))
	print(text)


if __name__ == "__main__":
	main(sys.argv[1] if len(sys.argv) > 1 else "jevk5:4b")
