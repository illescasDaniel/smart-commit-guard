"""Paths that are never scanned, and paths where findings are likely examples."""
from __future__ import annotations

from pathlib import PurePosixPath

_LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock", "pipfile.lock",
			  "cargo.lock", "gemfile.lock", "composer.lock", "go.sum", "bun.lock", "bun.lockb"}
_BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tar", ".7z", ".woff",
					".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".mov", ".avif", ".heic", ".so", ".dll", ".exe", ".pyc"}
_GENERATED_SUFFIXES = (".min.js", ".min.css", ".map")
_EXAMPLE_DIRS = {"test", "tests", "fixtures", "fixture", "docs", "doc", "examples", "example", "samples", "sample"}
_EXAMPLE_NAME_MARKERS = (".example", ".sample", "-example", "_example")


def _parts(path: str) -> tuple[str, ...]:
	return tuple(p.lower() for p in PurePosixPath(path).parts)


def is_skipped(path: str) -> bool:
	"""Lockfiles, generated files, binaries by extension, and `.env.example`."""
	name = PurePosixPath(path).name.lower()
	return (name in _LOCKFILES or name == ".env.example" or name.endswith(_GENERATED_SUFFIXES)
			or PurePosixPath(name).suffix in _BINARY_SUFFIXES)


def is_example_path(path: str) -> bool:
	"""Tests, fixtures, docs, READMEs and examples: a rule hit there is judged by the model instead of blocking."""
	parts = _parts(path)
	name = parts[-1] if parts else ""
	return (bool(_EXAMPLE_DIRS.intersection(parts[:-1])) or name.startswith(("test_", "readme"))
			or name.endswith(("_test.py", ".md", ".rst")) or any(m in name for m in _EXAMPLE_NAME_MARKERS))
