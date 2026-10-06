"""Commit messages as scannable lines."""
from __future__ import annotations

import re

from .types import AddedLine

MESSAGE_LABEL = "COMMIT_EDITMSG"
# `git commit -v` appends the diff below a line like `# ------------------------ >8 ------------------------` (the comment
# character may be changed). Everything under it is the diff, which the pre-commit scan already covers, so it is not message text.
_SCISSORS = re.compile(r"^\S ?-{10,} >8 -{10,}$")


def message_lines(text: str, label: str = MESSAGE_LABEL) -> list[AddedLine]:
	"""Every line of the message above the scissors line, numbered from 1. Comment lines are kept on purpose: with `-m`
	git does not strip them, so a secret on a `#` line would be committed."""
	out: list[AddedLine] = []
	for number, raw in enumerate(text.split("\n"), start=1):
		raw = raw.removesuffix("\r")
		if _SCISSORS.match(raw):
			break
		out.append(AddedLine(label, number, raw))
	return out
