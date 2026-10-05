"""Deterministic layer: known secret shapes and candidate extraction."""
from __future__ import annotations

from .types import LineHit


def scan_line(text: str) -> LineHit | None:
	"""A rule hit (high confidence for private keys, AWS keys, token prefixes, URLs with a password), a candidate
	(secret-looking name assigned a literal, or a long high-entropy literal), or None."""
	raise NotImplementedError
