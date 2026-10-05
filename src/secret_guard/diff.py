"""Parse unified diffs into added lines."""
from __future__ import annotations

from .types import AddedLine


def parse_added_lines(diff_text: str) -> list[AddedLine]:
	"""Only `+` lines of text files, with new-file line numbers. Removed lines, context and binaries are ignored."""
	raise NotImplementedError
