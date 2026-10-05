"""Masking and fingerprints."""
from __future__ import annotations

import hashlib

_KNOWN_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "sk_live_", "sk_test_", "sk-", "glpat-", "AKIA", "ASIA",
				   "AIza", "xoxb-", "xoxa-", "xoxp-", "xoxr-", "xoxs-")


def mask(value: str) -> str:
	"""Keep shape (length class, character classes, known prefix) but not content."""
	prefix = next((p for p in _KNOWN_PREFIXES if value.startswith(p)), "")
	rest = value[len(prefix):]
	shaped = "".join("A" if c.isupper() else "a" if c.islower() else "9" if c.isdigit() else "*" for c in rest)
	return prefix + shaped


def mask_in_line(line: str, value: str) -> str:
	"""The line with `value` replaced by its mask."""
	return line.replace(value, mask(value)) if value else line


def fingerprint(path: str, masked_line: str) -> str:
	"""Stable hash of a masked finding, for the allowlist."""
	return hashlib.sha256(f"{path}\0{masked_line}".encode()).hexdigest()[:16]
