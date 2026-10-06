"""Parse unified diffs into added lines."""
from __future__ import annotations

import re

from .git import unquote_path
from .types import AddedLine

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _target_path(header: str) -> str | None:
	"""Path from a `+++ ` header: C-quoted when it has odd characters, with a trailing tab when it has spaces."""
	target = header[4:]
	if not target.startswith('"'):
		target = target.split("\t")[0]
	if target == "/dev/null":
		return None
	return unquote_path(target).removeprefix("b/")


def parse_added_lines(diff_text: str) -> list[AddedLine]:
	"""Only `+` lines of text files, with new-file line numbers. Removed lines and context are ignored.

	Expects the pinned format of `git.diff_text` (`a/` and `b/` prefixes, `--text`). A file whose added lines contain a NUL
	byte is a real binary that `--text` expanded, so it is dropped as a whole."""
	out: list[AddedLine] = []
	binary: set[str] = set()
	path: str | None = None
	in_hunk = False
	number = 0
	# split on "\n" only: str.splitlines() also breaks on form feeds and U+2028, which would shift every line number
	for raw in diff_text.split("\n"):
		raw = raw.removesuffix("\r")
		if raw.startswith("diff --git "):
			path, in_hunk = None, False
			continue
		if not in_hunk and raw.startswith("+++ "):
			path = _target_path(raw)
			continue
		m = _HUNK.match(raw)
		if m:
			in_hunk, number = True, int(m.group(1))
			continue
		if not in_hunk or path is None:
			continue
		if raw.startswith("+"):
			if "\0" in raw:
				binary.add(path)
			out.append(AddedLine(path, number, raw[1:]))
			number += 1
		elif raw.startswith(" "):
			number += 1
	return [line for line in out if line.path not in binary]
