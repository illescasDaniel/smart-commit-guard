"""The only place that runs git: safe diff flags, UTF-8 decoding, C-quoted path handling and repo-root lookup."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .skip import BINARY_SUFFIXES

# Config that changes how a diff looks must never change what the scan sees (user or repo config, .gitattributes).
_DIFF_CONFIG = ("-c", "core.quotepath=off", "-c", "diff.mnemonicPrefix=false", "-c", "diff.noprefix=false",
				"-c", "diff.relative=false", "-c", "diff.submodule=short", "-c", "diff.renames=false")
# `--no-renames`: a file renamed to a sensitive name (`config.json` -> `.env`) is then an added file, with its content scanned.
# `--text` overrides `binary` / `-diff` attributes, so a secret in a file marked binary is still seen. Real binaries
# (by suffix) are excluded up front so their bytes are never read into memory.
_DIFF_FLAGS = ("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames", "--text", "--src-prefix=a/", "--dst-prefix=b/",
			   "--submodule=short", "-U0")
_BINARY_PATHSPEC = tuple(f":(exclude,icase,glob)**/*{s}" for s in sorted(BINARY_SUFFIXES))


class GitError(Exception):
	pass


def _describe(args: tuple[str, ...]) -> str:
	"""The command for an error message: without the pinned `-c` options and the long binary pathspec."""
	shown, skip_next = [], False
	for a in args:
		if a == "--":
			break
		if skip_next:
			skip_next = False
		elif a == "-c":
			skip_next = True
		elif not a.startswith("--no-") and a not in ("--text", "-U0"):
			shown.append(a)
	return " ".join(shown)


def run(*args: str, cwd: str | Path | None = None) -> str:
	"""stdout of `git <args>`, decoded as UTF-8 (never the locale code page). Raises GitError."""
	try:
		r = subprocess.run(["git", *args], capture_output=True, check=False, cwd=cwd)
	except OSError as e:
		raise GitError(f"cannot run git: {e}") from e
	if r.returncode != 0:
		raise GitError(f"git {_describe(args)} failed: {r.stderr.decode('utf-8', 'replace').strip() or 'not a git repository?'}")
	return r.stdout.decode("utf-8", "replace")


EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_RANGE = re.compile(r"^(?P<left>[^.]*?)(?P<dots>\.\.\.?)(?P<right>.*)$")


def normalize_range(revision_range: str) -> str:
	"""A push event's `before` is all zeros when a branch is new: compare against the empty tree, so the whole branch is scanned."""
	m = _RANGE.match(revision_range)
	if m and m["left"] and set(m["left"]) == {"0"}:
		return f"{EMPTY_TREE}..{m['right']}"   # the empty tree has no merge base, so `...` becomes `..`
	return revision_range


def diff_text(*revision_args: str) -> str:
	"""The unified diff (`-U0`) of a revision range, or of `--cached`, with every user-configurable diff option pinned."""
	return run(*_DIFF_CONFIG, *_DIFF_FLAGS, *revision_args, "--", ":/", *_BINARY_PATHSPEC)


def changed_paths(*revision_args: str) -> list[str]:
	"""Added, modified or renamed files (binaries included), for the file-name rules. `-z`: names are never quoted."""
	out = run(*_DIFF_CONFIG, "diff", "--no-renames", "--name-only", "--diff-filter=AMR", "-z", *revision_args)
	return [p for p in out.split("\0") if p]


def repo_root() -> Path | None:
	"""Top level of the working tree, or None outside a git repository."""
	try:
		return Path(run("rev-parse", "--show-toplevel").strip())
	except GitError:
		return None


def read_blob(rev: str, path: str) -> str | None:
	"""Text of `path` at `rev` (for example `origin/main`), or None when it does not exist there."""
	try:
		return run("show", f"{rev}:{path}")
	except GitError:
		return None


_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
_OCTAL = re.compile(r"[0-7]{1,3}")


def unquote_path(raw: str) -> str:
	"""Undo git's C-style quoting (`"caf\\303\\251.py"` -> `café.py`). Unquoted input is returned as is."""
	if len(raw) < 2 or not (raw.startswith('"') and raw.endswith('"')):
		return raw
	body, out, i = raw[1:-1], bytearray(), 0
	while i < len(body):
		c = body[i]
		if c != "\\" or i + 1 >= len(body):
			out += c.encode("utf-8")
			i += 1
			continue
		nxt = body[i + 1]
		if m := _OCTAL.match(body, i + 1):
			out.append(int(m.group(), 8) & 0xFF)
			i = m.end()
		elif nxt in _ESCAPES:
			out.append(_ESCAPES[nxt])
			i += 2
		else:   # unknown escape: keep it literally
			out += ("\\" + nxt).encode("utf-8")
			i += 2
	return out.decode("utf-8", "replace")
