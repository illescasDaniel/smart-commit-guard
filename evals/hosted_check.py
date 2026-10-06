"""Small hosted-endpoint check: `python evals/hosted_check.py [N]` scores N model-stage lines with the hosted model named in
`.env` (see `.env.example`) and compares them with the local `jevk5:4b` scores of `compare_models.py`.
The lines are synthetic or from public open-source code; no real secret is sent."""
from __future__ import annotations

import json
import random
import statistics
import sys
import time
from pathlib import Path

from compare_models import OUT, auc, load_cases

from smart_commit_guard.config import Config
from smart_commit_guard.decider import HttpDecider


def dotenv() -> dict[str, str]:
	env = {}
	for line in Path(__file__).parent.parent.joinpath(".env").read_text(encoding="utf-8").splitlines():
		if "=" in line and not line.lstrip().startswith("#"):
			k, v = line.split("=", 1)
			env[k.strip()] = v.strip().strip("\"'")
	return env


def main(n: int) -> None:
	cfg = Config.from_env(dotenv())
	cases = load_cases()
	hand = [c for c in cases if c["family"] == "hand-written"]
	rest = random.Random(1).sample([c for c in cases if c["family"] != "hand-written"], max(0, n - len(hand)))
	picked = (hand + rest)[:n]
	local = json.loads((OUT / "scores_jevk5_4b.json").read_text(encoding="utf-8"))["scores"]
	decider = HttpDecider(cfg.base_url, cfg.model, 60.0, cfg.api_key)
	rows, lat = [], []
	for c in picked:
		t = time.perf_counter()
		p = decider.judge([(c["path"], c["text"])])[0]
		lat.append((time.perf_counter() - t) * 1000)
		rows.append({"label": c["label"], "hosted": p, "local": local[f"{c['path']}|{c['text']}"]})

	def col(key: str, label: str) -> list[float]:
		return [r[key] for r in rows if r["label"] == label]

	def at_half(key: str) -> dict[str, float]:
		return {"recall": sum(p >= .5 for p in col(key, "real")) / len(col(key, "real")),
				"false_blocks": sum(p >= .5 for p in col(key, "ok")) / len(col(key, "ok"))}
	out = {"model": cfg.model, "n": len(rows), "real": len(col("hosted", "real")), "ok": len(col("hosted", "ok")),
		   "auc_hosted": auc(col("hosted", "real"), col("hosted", "ok")), "auc_local_jevk5": auc(col("local", "real"), col("local", "ok")),
		   "mean_abs_score_diff": statistics.fmean(abs(r["hosted"] - r["local"]) for r in rows),
		   "p50_ms": statistics.median(lat), "p95_ms": sorted(lat)[int(0.95 * len(lat)) - 1],
		   "at_0.5_hosted": at_half("hosted"), "at_0.5_local": at_half("local")}
	(OUT / "hosted_check.json").write_text(json.dumps({"summary": out, "rows": rows}), encoding="utf-8")
	print(json.dumps(out, indent=1))


if __name__ == "__main__":
	main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
