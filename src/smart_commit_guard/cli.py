"""Command line: `smart-commit-guard scan --staged | --diff <range> | --files ...`."""
from __future__ import annotations

import argparse
import fnmatch
import os
import shlex
import shutil
import stat
import sys
import traceback
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, git, report
from .config import CONFIG_NAME, Config, ConfigError, RepoSettings
from .decider import Decider, DeciderUnavailable, HttpDecider
from .diff import parse_added_lines
from .git import GitError
from .policy import scan
from .redact import fingerprint
from .skip import BINARY_SUFFIXES
from .types import AddedLine

SKIP_ENV = "SKIP_SECRET_GUARD"
LOG_NAME = "secret-guard-skips.log"
DEBUG_ENV = "SMART_COMMIT_GUARD_DEBUG"
BUDGET_COMMIT, BUDGET_CI = 5.0, 120.0   # default seconds of model time per scan; SECRET_GUARD_BUDGET overrides
MAX_FILE_BYTES = 2_000_000
# Tail shared by both hooks: reached only when the tool cannot be found.
_MISSING = """if [ "$SKIP_SECRET_GUARD" = "1" ]; then
	echo "smart-commit-guard: SKIPPED (SKIP_SECRET_GUARD=1) and the tool is unavailable: this commit was not scanned or logged." >&2
	exit 0
fi
echo "smart-commit-guard: not installed (try: uv tool install smart-commit-guard); commit blocked. CI is the backstop, so install it." >&2
exit 1
"""
# Per-clone hook: absolute path of the tool that ran `install-hook`.
HOOK = """#!/bin/sh
# installed by smart-commit-guard
exe={exe}
if [ -x "$exe" ] || command -v "$exe" >/dev/null 2>&1; then
	exec "$exe" scan --staged
fi
""" + _MISSING
# Shared hook (committed to the repo): no machine-specific paths, so it resolves the tool at run time.
SHARED_HOOK = """#!/bin/sh
# managed by smart-commit-guard (install-hook --shared). Commit this file so every clone gets the same gate.
root=$(git rev-parse --show-toplevel)
if command -v smart-commit-guard >/dev/null 2>&1; then
	exec smart-commit-guard scan --staged
elif [ -x "$root/.venv/bin/smart-commit-guard" ]; then
	exec "$root/.venv/bin/smart-commit-guard" scan --staged
elif command -v uvx >/dev/null 2>&1; then
	exec uvx smart-commit-guard scan --staged
fi
""" + _MISSING
SHARED_DIR = ".githooks"
GITATTRIBUTES_LINE = f"/{SHARED_DIR}/* text eol=lf"


class ToolError(Exception):
	pass


def _file_lines(files: Sequence[tuple[str, str]]) -> list[AddedLine]:
	"""(path to read, repo-relative display path) -> every line. Real binaries and huge files are skipped with a note."""
	out: list[AddedLine] = []
	for read, shown in files:
		p = Path(read)
		if p.is_dir() or p.suffix.lower() in BINARY_SUFFIXES:   # `git ls-files` lists symlinked directories and submodules
			continue
		try:
			size = p.stat().st_size
			if size > MAX_FILE_BYTES:
				print(f"smart-commit-guard: skipped {shown}: {size} bytes is over the {MAX_FILE_BYTES} byte limit", file=sys.stderr)
				continue
			data = p.read_bytes()
		except OSError as e:
			raise ToolError(f"cannot read {read}: {e}") from e
		if b"\0" in data[:8192]:   # a binary file, whatever its name
			continue
		rows = data.decode("utf-8", "replace").split("\n")   # not splitlines(): form feeds and U+2028 would shift line numbers
		if rows[-1] == "":   # no phantom empty line after the final newline
			rows.pop()
		out += [AddedLine(shown, i, t.removesuffix("\r")) for i, t in enumerate(rows, start=1)]
	return out


def _display_path(path: str, root: Path) -> str:
	"""Repo-relative POSIX path (so skip globs, rules and fingerprints agree with `--diff` and `--staged`); paths outside the
	repository keep their own spelling."""
	for candidate in (Path(os.path.abspath(path)), Path(os.path.realpath(path))):
		try:
			return candidate.relative_to(root).as_posix()
		except ValueError:
			continue
	return Path(path).as_posix()


def _skipped_by(path: str, skip: Sequence[str]) -> bool:
	return any(fnmatch.fnmatchcase(path, g) for g in skip)


def _load_settings(root: Path, config_from: str | None = None) -> RepoSettings:
	"""`.secret-guard.toml` from the repo root, or from a trusted revision such as `origin/main`: in CI the file is part
	of the very diff it guards, so a change could otherwise skip the scan."""
	if config_from is None:
		return RepoSettings.load(root)
	text = git.read_blob(config_from, CONFIG_NAME)
	return RepoSettings() if text is None else RepoSettings.parse(text, f"{CONFIG_NAME} at {config_from}")


def _hint() -> str:
	return ("smart-commit-guard: commit blocked. Move secrets to environment variables. For a false positive, allowlist it "
			f"in {CONFIG_NAME} or, for this commit only, run it with {SKIP_ENV}=1.")


def _log_skip() -> None:
	"""Append an audit entry for a bypassed commit to `<git dir>/secret-guard-skips.log`. Never blocks the commit."""
	try:
		log = Path(git.run("rev-parse", "--git-path", LOG_NAME).strip())
		branch = git.run("branch", "--show-current").strip() or "(detached)"
		files = git.run("-c", "core.quotepath=off", "diff", "--cached", "--name-only", "-z").split("\0")
		files = [f for f in files if f]
		settings = RepoSettings.load(git.repo_root() or Path.cwd())
		lines = [l for l in parse_added_lines(git.diff_text("--cached")) if not _skipped_by(l.path, settings.skip)]
		found = scan(lines, None, allowlist=settings.allowlist).findings   # rules only: instant, and the model may be what was wrong
		entry = [f"{datetime.now(UTC).isoformat(timespec='seconds')} SKIP branch={branch} files={len(files)}"]
		entry += [f"  file: {f}" for f in files]
		entry += [f"  {f.level.upper()} {f.path}:{f.number} {f.reason} {report.clip(f.preview)} allowlist={fingerprint(f.path, f.preview)}"
				  for f in found]
		with log.open("a", encoding="utf-8") as fh:
			fh.write("\n".join(entry) + "\n")
	except (ToolError, ConfigError, GitError, OSError) as e:
		print(f"smart-commit-guard: could not write the skips log: {e}", file=sys.stderr)


def _input(args: argparse.Namespace, root: Path) -> tuple[list[AddedLine], list[str]]:
	"""(added lines, changed paths that may have no lines, such as key stores) with repo-relative paths."""
	if args.all or args.files:
		if args.all:
			listed = [p for p in git.run("ls-files", "-z", cwd=root).split("\0") if p]
			files = [(str(root / p), p) for p in listed]
		else:
			names = [n for n in sys.stdin.buffer.read().decode("utf-8", "replace").split("\0") if n] if args.files == ["-"] else args.files
			files = [(n, _display_path(n, root)) for n in names]
		return _file_lines(files), [shown for _, shown in files]
	if args.diff:
		if ".." not in args.diff:
			raise ToolError(f"--diff takes a revision range such as origin/main...HEAD, got {args.diff!r} "
							"(a single revision would compare it with the working tree)")
		return parse_added_lines(git.diff_text(args.diff)), git.changed_paths(args.diff)
	return parse_added_lines(git.diff_text("--cached")), git.changed_paths("--cached")


def _scan(args: argparse.Namespace, env: Mapping[str, str], decider: Decider | None) -> int:
	if args.staged and env.get(SKIP_ENV) == "1":   # only the local commit hook; CI (`--diff`) cannot be skipped this way
		print(f"smart-commit-guard: SKIPPED ({SKIP_ENV}=1): this commit was not scanned. Only use this for a false positive.",
			  file=sys.stderr)
		_log_skip()
		return 0
	root = git.repo_root() or Path.cwd()
	lines, paths = _input(args, root)
	settings = _load_settings(root, args.config_from)
	if args.diff and CONFIG_NAME in paths and not args.config_from:
		print(f"smart-commit-guard: warning: {CONFIG_NAME} changes in this range, and it can skip or allowlist findings. "
			  "Review that change, or read the config from the base branch with --config-from.", file=sys.stderr)
	filtered = [l for l in lines if not _skipped_by(l.path, settings.skip)]
	kept = [p for p in paths if not _skipped_by(p, settings.skip)]
	if settings.skip and paths and (not kept or any(g.strip("*") == "" for g in settings.skip)):
		print(f"smart-commit-guard: warning: the skip patterns in {CONFIG_NAME} cover every changed file, so nothing was scanned.",
			  file=sys.stderr)
	lines, paths = filtered, kept
	skipped_reason = None
	if args.no_model:
		decider, cfg = None, Config()
	else:
		cfg = Config.from_env(env, settings)
		if cfg.is_hosted and cfg.hosted_scope == "ci" and args.staged:
			decider, skipped_reason = None, "hosted_scope"   # CI is the backstop for what the hook cannot judge
		else:
			decider = decider or HttpDecider(cfg.base_url, cfg.model, cfg.timeout, cfg.api_key)
	budget = cfg.budget or (BUDGET_COMMIT if args.staged else BUDGET_CI)
	result = scan(lines, decider, block_at=cfg.block_at, warn_at=cfg.warn_at, allowlist=settings.allowlist, paths=paths, budget=budget)
	result.model_skipped = skipped_reason
	if args.format == "json":
		print(report.as_json(result))
	elif args.format == "sarif":
		print(report.as_sarif(result))
	else:
		report.print_text(result, env.get("GITHUB_ACTIONS") == "true", _hint())
	return result.exit_code


def _executable() -> str:
	"""Absolute path of this tool, so the hook works when `smart-commit-guard` is not on git's PATH (venv, uv run)."""
	me = Path(sys.argv[0])
	if me.name in ("smart-commit-guard", "smart-commit-guard.exe") and me.exists():
		return str(me.resolve())
	return shutil.which("smart-commit-guard") or "smart-commit-guard"


def _write_hook(hook: Path, text: str, force: bool) -> None:
	if hook.exists() and not force:
		raise ToolError(f"{hook} already exists; use --force to overwrite it")
	hook.parent.mkdir(parents=True, exist_ok=True)
	hook.write_bytes(text.encode("utf-8"))   # LF endings on every OS: write_text would turn them into CRLF on Windows
	hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
	print(f"installed {hook}")


def _install_hook(force: bool, shared: bool) -> int:
	if not shared:
		_write_hook(Path(git.run("rev-parse", "--git-path", "hooks/pre-commit").strip()), HOOK.format(exe=shlex.quote(_executable())), force)
		return 0
	top = Path(git.run("rev-parse", "--show-toplevel").strip())
	try:
		current = git.run("config", "core.hooksPath").strip()
	except GitError:   # exit 1: not set
		current = ""
	if current not in ("", SHARED_DIR) and not force:
		raise ToolError(f"core.hooksPath is already set to {current!r}; use --force to replace it")
	_write_hook(top / SHARED_DIR / "pre-commit", SHARED_HOOK, force)
	git.run("config", "core.hooksPath", SHARED_DIR)
	attrs = top / ".gitattributes"
	existing = attrs.read_text(encoding="utf-8", errors="replace") if attrs.exists() else ""
	if GITATTRIBUTES_LINE not in existing.splitlines():
		attrs.write_bytes((existing + ("" if existing.endswith("\n") or not existing else "\n") + GITATTRIBUTES_LINE + "\n").encode("utf-8"))
	print(f"set core.hooksPath={SHARED_DIR}. Commit {SHARED_DIR}/ and .gitattributes; each clone then runs "
		  f"`git config core.hooksPath {SHARED_DIR}` once (or `smart-commit-guard install-hook --shared`).")
	return 0


def _doctor(env: Mapping[str, str], decider: Decider | None) -> int:
	"""Check the whole chain: hook installed and wired, rules working, model reachable. Exit 1 only for real failures."""
	failed = False

	def say(status: str, label: str, detail: str = "") -> None:
		nonlocal failed
		failed = failed or status == "FAIL"
		print(f"{status:5} {label}" + (f": {detail}" if detail else ""))

	say("ok", "version", __version__)
	hook = Path(git.run("rev-parse", "--git-path", "hooks/pre-commit").strip())
	if not hook.is_file():
		say("FAIL", "pre-commit hook", f"{hook} not found; run `smart-commit-guard install-hook` (or `install-hook --shared`)")
	else:
		text = hook.read_text(encoding="utf-8", errors="replace")
		if "scan --staged" not in text:
			say("FAIL", "pre-commit hook", f"{hook} exists but does not run `smart-commit-guard scan --staged`")
		elif not os.access(hook, os.X_OK):
			say("FAIL", "pre-commit hook", f"{hook} is not executable (chmod +x)")
		else:
			say("ok", "pre-commit hook", str(hook))
	probe = AddedLine("doctor.py", 1, 'KEY = "' + "AKIA" + 'IOSFODNN7EXAMPLE"')   # assembled so this file never trips the scanner
	if scan([probe], None).exit_code == 1:
		say("ok", "rules", "a synthetic AWS key is blocked")
	else:
		say("FAIL", "rules", "a synthetic AWS key was not blocked")
	try:
		cfg = Config.from_env(env, _load_settings(git.repo_root() or Path.cwd()))
		if cfg.is_hosted:
			host = urlparse(cfg.base_url).hostname
			where = "used in CI only; commits fall back to rules" if cfg.hosted_scope == "ci" else "used for commits and CI"
			say("WARN", "model", f"hosted ({host}), {where}. Candidate lines are sent there unmasked, so only use a server you "
								 "would trust with the secrets themselves")
		if not (cfg.is_hosted and cfg.hosted_scope == "ci"):
			(decider or HttpDecider(cfg.base_url, cfg.model, cfg.timeout, cfg.api_key)).judge([("doctor.py", 'password = "x"')])
			say("ok", "model", f"{cfg.model} at {cfg.base_url}")
	except ConfigError as e:
		say("FAIL", "config", str(e))
	except DeciderUnavailable as e:
		say("WARN", "model", f"unreachable ({e}); rule hits still block, ambiguous candidates only warn")
	if env.get(SKIP_ENV):
		say("WARN", SKIP_ENV, f"is set to {env[SKIP_ENV]!r} in this environment: commits are not being scanned")
	return 1 if failed else 0


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None, decider: Decider | None = None) -> int:
	"""Exit codes: 0 allowed, 1 blocked by a finding, 2 tool or configuration error (never a finding)."""
	parser = argparse.ArgumentParser(prog="smart-commit-guard")
	parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
	sub = parser.add_subparsers(dest="command", required=True)
	sc = sub.add_parser("scan", help="scan added lines for secrets")
	src = sc.add_mutually_exclusive_group(required=True)
	src.add_argument("--staged", action="store_true", help="the staged diff (git commit)")
	src.add_argument("--diff", metavar="RANGE", help="a git revision range, e.g. origin/main...HEAD (CI)")
	src.add_argument("--files", nargs="+", metavar="PATH", help="scan whole files; `-` reads NUL-separated paths from stdin")
	src.add_argument("--all", action="store_true", help="scan every tracked file (git ls-files)")
	sc.add_argument("--format", choices=report.FORMATS, default="text",
					help="text (with GitHub Actions annotations when GITHUB_ACTIONS=true), json, or sarif for code scanning")
	sc.add_argument("--json", action="store_true", help="same as --format json")
	sc.add_argument("--no-model", action="store_true", help="rules only")
	sc.add_argument("--config-from", metavar="REF", help=f"read {CONFIG_NAME} from this revision (for example origin/main) "
														 "instead of the working tree, so a pull request cannot change its own rules")
	ih = sub.add_parser("install-hook", help="install a git pre-commit hook")
	ih.add_argument("--force", action="store_true")
	ih.add_argument("--shared", action="store_true",
					help="write a committable .githooks/pre-commit and set core.hooksPath, so every clone shares the gate")
	sub.add_parser("doctor", help="check that the hook, rules and model are working")
	try:
		args = parser.parse_args(argv)
	except SystemExit as e:
		return 2 if e.code else 0
	env = os.environ if env is None else env
	machine = args.command == "scan" and (args.json or args.format != "text")
	if args.command == "scan" and args.json:
		args.format = "json"
	try:
		if args.command == "scan":
			return _scan(args, env, decider)
		return _install_hook(args.force, args.shared) if args.command == "install-hook" else _doctor(env, decider)
	except Exception as e:  # noqa: BLE001  exit 1 must only ever mean "a finding blocked": a crash is a tool error
		if env.get(DEBUG_ENV) == "1":
			traceback.print_exc()
		message = str(e) if isinstance(e, (ToolError, ConfigError, GitError)) else f"unexpected {type(e).__name__}: {e}"
		print(f"smart-commit-guard: {message}", file=sys.stderr)
		if machine and args.format == "json":
			print(report.error_json(message))
		return 2
