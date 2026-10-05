"""Parse unified diffs into added lines."""
from __future__ import annotations

import re

from .types import AddedLine

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_added_lines(diff_text: str) -> list[AddedLine]:
	"""Only `+` lines of text files, with new-file line numbers. Removed lines, context and binaries are ignored."""
	out: list[AddedLine] = []
	path: str | None = None
	in_hunk = False
	number = 0
	for raw in diff_text.splitlines():
		if raw.startswith("diff --git "):
			path, in_hunk = None, False
			continue
		if not in_hunk and raw.startswith("+++ "):
			target = raw[4:].split("\t")[0]
			path = None if target == "/dev/null" else target.removeprefix("b/")
			continue
		m = _HUNK.match(raw)
		if m:
			in_hunk, number = True, int(m.group(1))
			continue
		if not in_hunk or path is None:
			continue
		if raw.startswith("+"):
			out.append(AddedLine(path, number, raw[1:]))
			number += 1
		elif raw.startswith(" "):
			number += 1
	return out
