"""Masking and fingerprints."""
from __future__ import annotations


def mask(value: str) -> str:
	"""Keep shape (length class, character classes, known prefix) but not content."""
	raise NotImplementedError


def fingerprint(path: str, masked_line: str) -> str:
	"""Stable hash of a masked finding, for the allowlist."""
	raise NotImplementedError
