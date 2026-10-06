"""Print the CHANGELOG.md section of a version, for the GitHub release notes.

	python scripts/release_notes.py v0.2.0
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def section(changelog: str, version: str) -> str | None:
	"""The text under `## <version> ...` up to the next `## ` heading, or None."""
	version = version.removeprefix("v")
	m = re.search(rf"^## {re.escape(version)}(?:[ \t][^\n]*)?\n(?P<body>.*?)(?=^## |\Z)", changelog, re.MULTILINE | re.DOTALL)
	return m["body"].strip() if m else None


def main(argv: list[str]) -> int:
	if len(argv) != 1:
		print(__doc__, file=sys.stderr)
		return 2
	text = section((Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8"), argv[0])
	if not text:
		print(f"no CHANGELOG.md section for {argv[0]}", file=sys.stderr)
		return 1
	print(text)
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
