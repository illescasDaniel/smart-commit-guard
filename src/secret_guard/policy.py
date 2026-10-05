"""Scan policy: thresholds, batching and fail-open/closed rules live here, not in the model."""
from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from .decider import Decider
from .types import AddedLine, ScanResult

MAX_CALLS = 5


def scan(lines: Sequence[AddedLine], decider: Decider | None, *, block_at: float = 0.85, warn_at: float = 0.5,
		 hosted: bool = False, allowlist: AbstractSet[str] = frozenset()) -> ScanResult:
	"""decider=None means rules only. With hosted=True the decider only ever receives masked text."""
	raise NotImplementedError
