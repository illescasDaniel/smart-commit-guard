"""Masking and fingerprints."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from .rules import KNOWN_PREFIXES, entropy, has_digit_and_letter
from .types import LineHit

# Defence in depth: previews end up in CI logs, so a long random-looking token is masked even when no rule flagged it.
_TOKEN = re.compile(r"[A-Za-z0-9+/=_-]{16,}")
_TOKEN_ENTROPY = 3.0


def mask(value: str) -> str:
	"""Keep shape (length class, character classes, known prefix) but not content."""
	prefix = next((p for p in KNOWN_PREFIXES if value.startswith(p)), "")
	rest = value[len(prefix):]
	shaped = "".join("A" if c.isupper() else "a" if c.islower() else "9" if c.isdigit() else "*" for c in rest)
	return prefix + shaped


def mask_spans(line: str, spans: Iterable[tuple[int, int]]) -> str:
	"""The line with each span replaced by its mask."""
	out = line
	for start, end in sorted(set(spans), reverse=True):   # right to left, so earlier offsets stay valid
		out = out[:start] + mask(out[start:end]) + out[end:]
	return out


def mask_line(line: str, hits: Iterable[LineHit]) -> str:
	"""Every hit on the line masked, plus any other long high-entropy token. No secret from a line survives in its preview."""
	spans = [(h.start, h.end) for h in hits]
	for m in _TOKEN.finditer(line):
		if not any(m.start() < e and s < m.end() for s, e in spans) and has_digit_and_letter(m.group()) and entropy(m.group()) > _TOKEN_ENTROPY:
			spans.append(m.span())
	return mask_spans(line, spans)


def fingerprint(path: str, masked_line: str) -> str:
	"""v1: stable hash of a masked finding. Re-indenting the line changes it, so it is only accepted, never printed."""
	return hashlib.sha256(f"{path}\0{masked_line}".encode()).hexdigest()[:16]


def fingerprint_v2(path: str, masked_line: str) -> str:
	"""v2 (printed): the same hash over the stripped line, so re-indenting does not break an allowlist entry."""
	return "v2:" + hashlib.sha256(f"{path}\0{masked_line.strip()}".encode()).hexdigest()[:16]


def fingerprints(path: str, masked_line: str) -> tuple[str, str]:
	"""(v2, v1): an allowlist entry in either form matches."""
	return fingerprint_v2(path, masked_line), fingerprint(path, masked_line)
