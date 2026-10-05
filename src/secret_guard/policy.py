"""Scan policy: thresholds, batching and fail-open/closed rules live here, not in the model."""
from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from .decider import MAX_BATCH, Decider, DeciderUnavailable
from .redact import fingerprint, mask_in_line
from .rules import scan_line
from .skip import is_example_path, is_skipped
from .types import AddedLine, Finding, LineHit, ScanResult

MAX_CALLS = 30   # one candidate per request (see decider.MAX_BATCH), so this is also the candidates judged per scan


def _label(hit: LineHit) -> str:
	return f"{hit.rule} pattern" if hit.kind == "rule" else "secret-looking value"


def scan(lines: Sequence[AddedLine], decider: Decider | None, *, block_at: float = 0.5, warn_at: float = 0.4,
		 hosted: bool = False, allowlist: AbstractSet[str] = frozenset()) -> ScanResult:
	"""decider=None means rules only. With hosted=True the decider only ever receives masked text."""
	result = ScanResult()
	pending: list[tuple[AddedLine, LineHit, str]] = []   # (line, hit, masked line); the model decides these
	for line in lines:
		if is_skipped(line.path):
			continue
		hit = scan_line(line.text)
		if hit is None:
			continue
		masked = mask_in_line(line.text, hit.value)
		if fingerprint(line.path, masked) in allowlist:
			continue
		if hit.high_confidence and not is_example_path(line.path):
			result.findings.append(Finding(line.path, line.number, "block", f"{_label(hit)} (rule, no model needed)", masked))
		else:
			pending.append((line, hit, masked))

	judged = _judge(pending, decider, hosted, result) if decider is not None else {}
	for i, (line, hit, masked) in enumerate(pending):
		p = judged.get(i)
		if p is None:
			why = ("model unavailable" if result.model_unavailable else "not judged by the model")
			level = "block" if hit.high_confidence else "warn"   # a known secret shape is never waved through
			result.findings.append(Finding(line.path, line.number, level, f"{_label(hit)}: {why}", masked))
		elif p >= block_at:
			result.findings.append(Finding(line.path, line.number, "block", f"{_label(hit)}: model says likely real", masked, p))
		elif p >= warn_at:
			result.findings.append(Finding(line.path, line.number, "warn", f"{_label(hit)}: model is unsure", masked, p))
	result.findings.sort(key=lambda f: (f.path, f.number))
	return result


def _judge(pending: list[tuple[AddedLine, LineHit, str]], decider: Decider, hosted: bool,
		   result: ScanResult) -> dict[int, float]:
	"""Index into `pending` -> P(real). Stops at the first failure or after MAX_CALLS batches."""
	out: dict[int, float] = {}
	for start in range(0, min(len(pending), MAX_CALLS * MAX_BATCH), MAX_BATCH):
		batch = pending[start:start + MAX_BATCH]
		items = [(line.path, masked if hosted else line.text) for line, _, masked in batch]
		try:
			ps = decider.judge(items)
		except DeciderUnavailable:
			result.model_unavailable = True
			break
		out.update({start + i: p for i, p in enumerate(ps)})
	return out
