"""Command line: `secret-guard scan --staged | --diff <range> | --files ...`."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from .config import Config, ConfigError
from .decider import Decider, DeciderUnavailable, HttpDecider
from .diff import parse_added_lines
from .policy import scan
from .redact import fingerprint
from .types import AddedLine, ScanResult

SKIP_ENV = "SKIP_SECRET_GUARD"
LOG_NAME = "secret-guard-skips.log"
# Tail shared by both hooks: reached only when the tool cannot be found.
_MISSING = """if [ "$SKIP_SECRET_GUARD" = "1" ]; then
	echo "secret-guard: SKIPPED (SKIP_SECRET_GUARD=1) and the tool is unavailable: this commit was not scanned or logged." >&2
	exit 0
fi
echo "secret-guard: not installed (try: uv tool install secret-guard); commit blocked. CI is the backstop, so install it." >&2
exit 1
"""
# Per-clone hook: absolute path of the tool that ran `install-hook`.
HOOK = """#!/bin/sh
# installed by secret-guard
exe={exe}
if [ -x "$exe" ] || command -v "$exe" >/dev/null 2>&1; then
	exec "$exe" scan --staged
fi
""" + _MISSING
# Shared hook (committed to the repo): no machine-specific paths, so it resolves the tool at run time.
SHARED_HOOK = """#!/bin/sh
# managed by secret-guard (install-hook --shared). Commit this file so every clone gets the same gate.
root=$(git rev-parse --show-toplevel)
if command -v secret-guard >/dev/null 2>&1; then
	exec secret-guard scan --staged
elif [ -x "$root/.venv/bin/secret-guard" ]; then
	exec "$root/.venv/bin/secret-guard" scan --staged
elif command -v uvx >/dev/null 2>&1; then
	exec uvx secret-guard scan --staged
fi
""" + _MISSING
SHARED_DIR = ".githooks"
GITATTRIBUTES_LINE = f"/{SHARED_DIR}/* text eol=lf"


class ToolError(Exception):
	pass


def _git(*args: str) -> str:
	try:
		r = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
	except OSError as e:
		raise ToolError(f"cannot run git: {e}") from e
	if r.returncode != 0:
		raise ToolError(f"git {' '.join(args)} failed: {r.stderr.strip() or 'not a git repository?'}")
	return r.stdout


def _file_lines(paths: Sequence[str]) -> list[AddedLine]:
	out: list[AddedLine] = []
	for p in paths:
		if Path(p).is_dir():   # `git ls-files` lists symlinked directories and submodules
			continue
		try:
			text = Path(p).read_text(errors="ignore")
		except OSError as e:
			raise ToolError(f"cannot read {p}: {e}") from e
		out += [AddedLine(p, i, t) for i, t in enumerate(text.splitlines(), start=1)]
	return out


def _repo_settings() -> tuple[list[str], frozenset[str]]:
	"""(extra skip globs, allowlisted fingerprints) from `.secret-guard.toml` in the working directory."""
	path = Path(".secret-guard.toml")
	if not path.is_file():
		return [], frozenset()
	try:
		data = tomllib.loads(path.read_text())
	except (OSError, tomllib.TOMLDecodeError) as e:
		raise ToolError(f"cannot read {path}: {e}") from e
	return list(data.get("skip", [])), frozenset(data.get("allowlist", []))


def _report(result: ScanResult, as_json: bool) -> None:
	rows = [{"path": f.path, "line": f.number, "level": f.level, "reason": f.reason, "preview": f.preview, "p": f.p,
			 "fingerprint": fingerprint(f.path, f.preview)} for f in result.findings]
	if as_json:
		print(json.dumps({"exit_code": result.exit_code, "model_unavailable": result.model_unavailable, "findings": rows}))
		return
	for f, r in zip(result.findings, rows):
		score = f" p={f.p:.2f}" if f.p is not None else ""
		print(f"{f.level.upper():5} {f.path}:{f.number}  {f.reason}{score}\n      {_clip(f.preview)}\n      allowlist: {r['fingerprint']}")
	if result.model_unavailable:
		print("note: the decision model was unavailable; only rule hits were enforced", file=sys.stderr)
	if result.exit_code:
		print("secret-guard: commit blocked. Move secrets to environment variables. For a false positive, allowlist it "
			  f"in .secret-guard.toml or, for this commit only, run it with {SKIP_ENV}=1.", file=sys.stderr)


def _clip(s: str, n: int = 160) -> str:
	return s if len(s) <= n else s[:n] + "..."


def _log_skip() -> None:
	"""Append an audit entry for a bypassed commit to `<git dir>/secret-guard-skips.log`. Never blocks the commit."""
	try:
		log = Path(_git("rev-parse", "--git-path", LOG_NAME).strip())
		branch = _git("branch", "--show-current").strip() or "(detached)"
		diff = _git("diff", "--cached", "-U0", "--no-color")
		files = _git("diff", "--cached", "--name-only").splitlines()
		skip, allow = _repo_settings()
		lines = [l for l in parse_added_lines(diff) if not any(fnmatch.fnmatch(l.path, g) for g in skip)]
		found = scan(lines, None, allowlist=allow).findings   # rules only: instant, and the model may be what was wrong
		entry = [f"{datetime.now(UTC).isoformat(timespec='seconds')} SKIP branch={branch} files={len(files)}"]
		entry += [f"  file: {f}" for f in files]
		entry += [f"  {f.level.upper()} {f.path}:{f.number} {f.reason} {_clip(f.preview)} allowlist={fingerprint(f.path, f.preview)}"
				  for f in found]
		with log.open("a") as fh:
			fh.write("\n".join(entry) + "\n")
	except (ToolError, OSError) as e:
		print(f"secret-guard: could not write the skips log: {e}", file=sys.stderr)


def _scan(args: argparse.Namespace, env: Mapping[str, str], decider: Decider | None) -> int:
	if args.staged and env.get(SKIP_ENV) == "1":   # only the local commit hook; CI (`--diff`) cannot be skipped this way
		print(f"secret-guard: SKIPPED ({SKIP_ENV}=1): this commit was not scanned. Only use this for a false positive.",
			  file=sys.stderr)
		_log_skip()
		return 0
	if args.files:
		lines = _file_lines(args.files)
	elif args.diff:
		lines = parse_added_lines(_git("diff", "-U0", "--no-color", args.diff))
	else:
		lines = parse_added_lines(_git("diff", "--cached", "-U0", "--no-color"))
	skip, allow = _repo_settings()
	lines = [l for l in lines if not any(fnmatch.fnmatch(l.path, g) for g in skip)]
	hosted = False
	if args.no_model:
		decider, cfg = None, Config()
	else:
		cfg = Config.from_env(env)
		hosted = cfg.is_hosted
		decider = decider or HttpDecider(cfg.base_url, cfg.model, cfg.timeout, cfg.api_key)
	result = scan(lines, decider, block_at=cfg.block_at, warn_at=cfg.warn_at, hosted=hosted, allowlist=allow)
	_report(result, args.json)
	return result.exit_code


def _executable() -> str:
	"""Absolute path of this tool, so the hook works when `secret-guard` is not on git's PATH (venv, uv run)."""
	me = Path(sys.argv[0])
	if me.name == "secret-guard" and me.exists():
		return str(me.resolve())
	return shutil.which("secret-guard") or "secret-guard"


def _write_hook(hook: Path, text: str, force: bool) -> None:
	if hook.exists() and not force:
		raise ToolError(f"{hook} already exists; use --force to overwrite it")
	hook.parent.mkdir(parents=True, exist_ok=True)
	hook.write_text(text)
	hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
	print(f"installed {hook}")


def _install_hook(force: bool, shared: bool) -> int:
	if not shared:
		_write_hook(Path(_git("rev-parse", "--git-path", "hooks/pre-commit").strip()), HOOK.format(exe=shlex.quote(_executable())), force)
		return 0
	top = Path(_git("rev-parse", "--show-toplevel").strip())
	current = subprocess.run(["git", "config", "core.hooksPath"], capture_output=True, text=True, check=False).stdout.strip()
	if current not in ("", SHARED_DIR) and not force:
		raise ToolError(f"core.hooksPath is already set to {current!r}; use --force to replace it")
	_write_hook(top / SHARED_DIR / "pre-commit", SHARED_HOOK, force)
	_git("config", "core.hooksPath", SHARED_DIR)
	attrs = top / ".gitattributes"
	existing = attrs.read_text() if attrs.exists() else ""
	if GITATTRIBUTES_LINE not in existing.splitlines():
		attrs.write_text(existing + ("" if existing.endswith("\n") or not existing else "\n") + GITATTRIBUTES_LINE + "\n")
	print(f"set core.hooksPath={SHARED_DIR}. Commit {SHARED_DIR}/ and .gitattributes; each clone then runs "
		  f"`git config core.hooksPath {SHARED_DIR}` once (or `secret-guard install-hook --shared`).")
	return 0


def _doctor(env: Mapping[str, str], decider: Decider | None) -> int:
	"""Check the whole chain: hook installed and wired, rules working, model reachable. Exit 1 only for real failures."""
	failed = False

	def report(status: str, label: str, detail: str = "") -> None:
		nonlocal failed
		failed = failed or status == "FAIL"
		print(f"{status:5} {label}" + (f": {detail}" if detail else ""))

	hook = Path(_git("rev-parse", "--git-path", "hooks/pre-commit").strip())
	if not hook.is_file():
		report("FAIL", "pre-commit hook", f"{hook} not found; run `secret-guard install-hook` (or `install-hook --shared`)")
	else:
		text = hook.read_text(errors="ignore")
		if "scan --staged" not in text:
			report("FAIL", "pre-commit hook", f"{hook} exists but does not run `secret-guard scan --staged`")
		elif not os.access(hook, os.X_OK):
			report("FAIL", "pre-commit hook", f"{hook} is not executable (chmod +x)")
		else:
			report("ok", "pre-commit hook", str(hook))
	probe = AddedLine("doctor.py", 1, 'KEY = "' + "AKIA" + 'IOSFODNN7EXAMPLE"')   # assembled so this file never trips the scanner
	if scan([probe], None).exit_code == 1:
		report("ok", "rules", "a synthetic AWS key is blocked")
	else:
		report("FAIL", "rules", "a synthetic AWS key was not blocked")
	try:
		cfg = Config.from_env(env)
		(decider or HttpDecider(cfg.base_url, cfg.model, cfg.timeout, cfg.api_key)).judge([("doctor.py", 'password = "x"')])
		report("ok", "model", f"{cfg.model} at {cfg.base_url}")
	except ConfigError as e:
		report("FAIL", "config", str(e))
	except DeciderUnavailable as e:
		report("WARN", "model", f"unreachable ({e}); rule hits still block, ambiguous candidates only warn")
	if env.get(SKIP_ENV):
		report("WARN", SKIP_ENV, f"is set to {env[SKIP_ENV]!r} in this environment: commits are not being scanned")
	return 1 if failed else 0


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None, decider: Decider | None = None) -> int:
	"""Exit codes: 0 allowed, 1 blocked, 2 tool error."""
	parser = argparse.ArgumentParser(prog="secret-guard")
	sub = parser.add_subparsers(dest="command", required=True)
	sc = sub.add_parser("scan", help="scan added lines for secrets")
	src = sc.add_mutually_exclusive_group(required=True)
	src.add_argument("--staged", action="store_true", help="the staged diff (git commit)")
	src.add_argument("--diff", metavar="RANGE", help="a git revision range, e.g. origin/main...HEAD (CI)")
	src.add_argument("--files", nargs="+", metavar="PATH", help="scan whole files")
	sc.add_argument("--json", action="store_true")
	sc.add_argument("--no-model", action="store_true", help="rules only")
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
	try:
		if args.command == "scan":
			return _scan(args, env, decider)
		return _install_hook(args.force, args.shared) if args.command == "install-hook" else _doctor(env, decider)
	except (ToolError, ConfigError) as e:
		print(f"secret-guard: {e}", file=sys.stderr)
		return 2
