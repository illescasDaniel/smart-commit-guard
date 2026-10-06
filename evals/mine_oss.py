"""Mine real-world `ok` lines: candidate lines (the ones that reach the model) from installed open-source packages.

	python evals/mine_oss.py DIR [DIR ...] > evals/cases_oss.json

Lines come from third-party code that is not this project's own tests, so a live credential in them is very unlikely;
they are labelled `ok`, and the few the model scores high are reviewed by hand (see PLAN.md). The path in each case
is `<package>/<relative path>` and `source` names the package, so the corpus can be split by package.
"""
from __future__ import annotations

import json
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

from smart_commit_guard.policy import stage

SUFFIXES = {".py", ".json", ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".js", ".ts", ".sh", ".rst", ".html", ".xml"}
PER_PACKAGE = 12
MAX_CASES = 700


def package_of(root: Path, path: Path) -> str:
	parts = path.relative_to(root).parts
	return parts[0].split("-")[0] if parts else "?"


def main(roots: list[str]) -> None:
	rng = random.Random(7)
	by_pkg: dict[str, list[dict]] = defaultdict(list)
	seen: set[str] = set()
	for r in roots:
		root = Path(r)
		for dirpath, dirs, files in os.walk(root):
			dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", "node_modules", "tests", "test", "testing"}]
			for name in files:
				p = Path(dirpath) / name
				if p.suffix not in SUFFIXES or p.stat().st_size > 400_000:
					continue
				try:
					text = p.read_text(encoding="utf-8")
				except (OSError, UnicodeDecodeError):
					continue
				pkg = package_of(root, p)
				for line in text.split("\n"):
					line = line.rstrip()
					if not 12 <= len(line) <= 300 or line in seen:
						continue
					rel = p.relative_to(root).as_posix()
					if stage(rel, line) == "model":
						seen.add(line)
						by_pkg[pkg].append({"path": rel, "text": line, "label": "ok", "stage": "model", "source": pkg})
	out: list[dict] = []
	for pkg, cases in sorted(by_pkg.items()):
		rng.shuffle(cases)
		out += cases[:PER_PACKAGE]
	rng.shuffle(out)
	print(f"{len(by_pkg)} packages, {sum(map(len, by_pkg.values()))} candidate lines, kept {min(len(out), MAX_CASES)}", file=sys.stderr)
	json.dump(out[:MAX_CASES], sys.stdout, indent="\t", ensure_ascii=False)


if __name__ == "__main__":
	main(sys.argv[1:])
