"""Paths that are never scanned, and paths where findings are likely examples."""
from __future__ import annotations


def is_skipped(path: str) -> bool:
	"""Lockfiles, generated files, binaries by extension, and `.env.example`."""
	raise NotImplementedError


def is_example_path(path: str) -> bool:
	"""Tests, fixtures, docs, READMEs and examples: a rule hit there is judged by the model instead of blocking."""
	raise NotImplementedError
