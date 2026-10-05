"""Command line: `secret-guard scan --staged | --diff <range> | --files ...`."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from .decider import Decider


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None, decider: Decider | None = None) -> int:
	"""Exit codes: 0 allowed, 1 blocked, 2 tool error."""
	raise NotImplementedError
