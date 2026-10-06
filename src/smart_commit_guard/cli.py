"""Command line: `smart-commit-guard scan --staged | --diff <range> | --files ...`."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import traceback
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, git, report, user_config
from .config import CONFIG_NAME, Config, ConfigError, RepoSettings
from .decider import Decider, DeciderUnavailable, HttpDecider
from .diff import parse_added_lines
from .git import GitError
from .messages import message_lines
from .policy import scan
from .redact import fingerprint_v2, fingerprints
from .skip import BINARY_SUFFIXES
from .types import AddedLine, ScanResult

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
@CHAIN@exe={exe}
if [ -x "$exe" ] || command -v "$exe" >/dev/null 2>&1; then
	exec "$exe" scan @ARGS@
fi
""" + _MISSING
# Shared hook (committed to the repo): no machine-specific paths, so it resolves the tool at run time.
SHARED_HOOK = """#!/bin/sh
# managed by smart-commit-guard (install-hook --shared). Commit this file so every clone gets the same gate.
@CHAIN@root=$(git rev-parse --show-toplevel)
if command -v smart-commit-guard >/dev/null 2>&1; then
	exec smart-commit-guard scan @ARGS@
elif [ -x "$root/.venv/bin/smart-commit-guard" ]; then
	exec "$root/.venv/bin/smart-commit-guard" scan @ARGS@
elif command -v uvx >/dev/null 2>&1; then
	exec uvx @UVX@smart-commit-guard scan @ARGS@
fi
""" + _MISSING
# `install-hook --chain`: the hook that was already there is kept as `<name>.local` and runs first.
CHAIN_BLOCK = """local_hook="$(dirname "$0")/@NAME@.local"
if [ -x "$local_hook" ]; then
	"$local_hook" "$@" || exit $?
fi
"""
# (hook file, arguments for `scan`). The message hook is separate because the message does not exist yet when pre-commit runs.
HOOKS = (("pre-commit", "--staged"), ("commit-msg", '--message "$1"'))
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


def _message_hint(message_file: str) -> str:
	return ("smart-commit-guard: commit message blocked: it contains a secret. Your message is saved in "
			f"{message_file}; edit it and re-run with `git commit -e -F {message_file}`. For a false positive, run the commit "
			f"with {SKIP_ENV}=1.")


def _log_skip() -> None:
	"""Append an audit entry for a bypassed commit to `<git dir>/secret-guard-skips.log`. Never blocks the commit."""
	try:
		log = Path(git.run("rev-parse", "--git-path", LOG_NAME).strip())
		branch = git.run("branch", "--show-current").strip() or "(detached)"
		files = git.run("-c", "core.quotepath=off", "diff", "--cached", "--name-only", "-z").split("\0")
		files = [f for f in files if f]
		settings = RepoSettings.load(git.repo_root() or Path.cwd())
		lines = [l for l in parse_added_lines(git.diff_text("--cached")) if not _skipped_by(l.path, settings.skip)]
		found = scan(lines, None, allowlist=settings.fingerprints, allow_paths=settings.allow_paths,
					 inline_allow=settings.allow_inline).findings   # rules only: instant, and the model may be what was wrong
		entry = [f"{datetime.now(UTC).isoformat(timespec='seconds')} SKIP branch={branch} files={len(files)}"]
		entry += [f"  file: {f}" for f in files]
		entry += [f"  {f.level.upper()} {f.path}:{f.number} {f.reason} {report.clip(f.preview)} allowlist={fingerprint_v2(f.path, f.preview)}"
				  for f in found]
		with log.open("a", encoding="utf-8") as fh:
			fh.write("\n".join(entry) + "\n")
	except (ToolError, ConfigError, GitError, OSError) as e:
		print(f"smart-commit-guard: could not write the skips log: {e}", file=sys.stderr)


def _input(args: argparse.Namespace, root: Path) -> tuple[list[AddedLine], list[str], list[AddedLine]]:
	"""(added lines, changed paths that may have no lines such as key stores, commit message lines), repo-relative paths.
	Messages never go to the model: rule hits block, candidates only warn (prose is too noisy to block on a score)."""
	if args.messages and not args.diff:
		raise ToolError("--messages goes with --diff: it scans the messages of the commits in that range")
	if args.message:
		try:
			text = Path(args.message).read_bytes().decode("utf-8", "replace")
		except OSError as e:
			raise ToolError(f"cannot read the commit message {args.message}: {e}") from e
		return [], [], message_lines(text)
	if args.text:
		return [], [], message_lines(sys.stdin.buffer.read().decode("utf-8", "replace"), "stdin")
	if args.all or args.files:
		if args.all:
			listed = [p for p in git.run("ls-files", "-z", cwd=root).split("\0") if p]
			files = [(str(root / p), p) for p in listed]
		else:
			names = [n for n in sys.stdin.buffer.read().decode("utf-8", "replace").split("\0") if n] if args.files == ["-"] else args.files
			files = [(n, _display_path(n, root)) for n in names]
		return _file_lines(files), [shown for _, shown in files], []
	if args.diff:
		if ".." not in args.diff:
			raise ToolError(f"--diff takes a revision range such as origin/main...HEAD, got {args.diff!r} "
							"(a single revision would compare it with the working tree)")
		rev = git.normalize_range(args.diff)
		try:
			lines, paths = parse_added_lines(git.diff_text(rev)), git.changed_paths(rev)
			messages = [l for sha, body in git.commit_messages(args.diff) for l in message_lines(body, f"commit {sha}")] if args.messages else []
			return lines, paths, messages
		except GitError as e:
			if any(t in str(e) for t in ("bad revision", "unknown revision", "Invalid revision")):
				raise ToolError(f"{e}. In CI check out with fetch-depth: 0 (a shallow clone lacks the base), and after a force-push "
								"the old `before` commit may be gone: scan the branch against its base instead.") from e
			raise
	return _staged_lines(), git.changed_paths("--cached"), []


def _staged_lines() -> list[AddedLine]:
	"""The lines this commit adds. During a merge the index also holds everything brought in from the other branch, which was
	scanned (or deliberately skipped) when it was committed there: only lines that are new against every parent are scanned,
	so conflict resolutions and hand edits are, and old findings do not come back."""
	lines = parse_added_lines(git.diff_text("--cached"))
	for head in git.merge_heads():
		try:
			theirs = {(l.path, l.text) for l in parse_added_lines(git.diff_text("--cached", head))}
		except GitError:
			continue   # an unreadable MERGE_HEAD must not hide lines: scan them all
		lines = [l for l in lines if (l.path, l.text) in theirs]
	return lines


def _read_baseline(path: str) -> frozenset[str]:
	try:
		data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
		return frozenset(row["fingerprint"] for row in data["findings"])
	except OSError as e:
		raise ConfigError(f"cannot read the baseline {path}: {e}") from e
	except (ValueError, KeyError, TypeError) as e:
		raise ConfigError(f"{path} is not a smart-commit-guard baseline file ({type(e).__name__}: {e})") from e


def _execute(args: argparse.Namespace, env: Mapping[str, str], decider: Decider | None) -> ScanResult:
	"""Read the input, apply the repo config and the baseline, and scan."""
	root = git.repo_root() or Path.cwd()
	lines, paths, messages = _input(args, root)
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
	messages = [l for l in messages if not _skipped_by(l.path, settings.skip)]
	skipped_reason = None
	if args.message or args.text or args.no_model:   # a commit message hook must never fail on model or hosted-model configuration
		decider, cfg = None, Config()
	else:
		cfg = Config.from_env(env, settings)
		if cfg.is_hosted and cfg.hosted_scope == "ci" and args.staged:
			decider, skipped_reason = None, "hosted_scope"   # CI is the backstop for what the hook cannot judge
		else:
			decider = decider or HttpDecider(cfg.base_url, cfg.model, cfg.timeout, cfg.api_key)
	budget = cfg.budget or (BUDGET_COMMIT if args.staged else BUDGET_CI)
	allow = settings.fingerprints | (_read_baseline(args.baseline) if args.baseline else frozenset())
	result = scan(lines, decider, block_at=cfg.block_at, warn_at=cfg.warn_at, allowlist=allow, allow_paths=settings.allow_paths,
				  inline_allow=settings.allow_inline, paths=paths, budget=budget)
	if messages:
		said = scan(messages, None, allowlist=allow, allow_paths=settings.allow_paths, inline_allow=settings.allow_inline)
		result.findings = sorted(result.findings + said.findings, key=lambda f: (f.path, f.number))
	result.model_skipped = skipped_reason
	return result


def _scan(args: argparse.Namespace, env: Mapping[str, str], decider: Decider | None) -> int:
	if args.staged and env.get(SKIP_ENV) == "1":   # only the local commit hook; CI (`--diff`) cannot be skipped this way
		print(f"smart-commit-guard: SKIPPED ({SKIP_ENV}=1): this commit was not scanned. Only use this for a false positive.",
			  file=sys.stderr)
		_log_skip()
		return 0
	if args.message and env.get(SKIP_ENV) == "1":   # the pre-commit hook already logged this skip
		print(f"smart-commit-guard: SKIPPED ({SKIP_ENV}=1): this commit message was not scanned.", file=sys.stderr)
		return 0
	result = _execute(args, env, decider)
	if args.format == "json":
		print(report.as_json(result))
	elif args.format == "sarif":
		print(report.as_sarif(result))
	else:
		report.print_text(result, env.get("GITHUB_ACTIONS") == "true", _message_hint(args.message) if args.message else _hint())
	return result.exit_code


def _whole_tree_args(no_model: bool) -> argparse.Namespace:
	return argparse.Namespace(staged=False, diff=None, files=None, all=True, config_from=None, no_model=no_model, baseline=None,
							  message=None, text=None, messages=False)


def _baseline_create(output: str, no_model: bool, env: Mapping[str, str], decider: Decider | None) -> int:
	"""Record every current finding (masked, fingerprints only) so that `scan --baseline FILE` fails on new ones only."""
	result = _execute(_whole_tree_args(no_model), env, decider)
	rows = [{"path": f.path, "line": f.number, "level": f.level, "reason": f.reason,
			 "fingerprint": fingerprint_v2(f.path, f.preview)} for f in result.findings]
	data = {"version": 1, "created": datetime.now(UTC).isoformat(timespec="seconds"), "findings": rows}
	Path(output).write_bytes((json.dumps(data, indent="\t") + "\n").encode("utf-8"))
	print(f"wrote {output}: {len(rows)} finding(s) recorded. Review and commit it; scan with `--baseline {output}` to fail on new findings only.")
	return 0


def _allowlist_migrate(env: Mapping[str, str]) -> int:
	"""Rewrite v1 fingerprints in `.secret-guard.toml` to v2 (text replacement, so comments and layout survive)."""
	root = git.repo_root() or Path.cwd()
	path = root / CONFIG_NAME
	if not path.is_file():
		raise ToolError(f"{path} not found; there is nothing to migrate")
	settings = RepoSettings.load(root)
	old = settings.fingerprints
	args = _whole_tree_args(True)
	lines, paths, _ = _input(args, root)
	lines = [l for l in lines if not _skipped_by(l.path, settings.skip)]
	# empty allowlist, no model: every flagged line shows up as a finding, so its v1 and v2 fingerprints can be paired
	found = scan(lines, None, paths=[p for p in paths if not _skipped_by(p, settings.skip)]).findings
	text = path.read_text(encoding="utf-8", errors="replace")
	migrated = 0
	for f in found:
		v2, v1 = fingerprints(f.path, f.preview)
		if v1 in old and f'"{v1}"' in text:
			text = text.replace(f'"{v1}"', f'"{v2}"')
			migrated += 1
	stale = sorted(fp for fp in old if not fp.startswith("v2:") and f'"{fp}"' in text)
	path.write_bytes(text.encode("utf-8"))
	print(f"migrated {migrated} fingerprint(s) to v2 in {path}")
	if stale:
		print(f"{len(stale)} v1 entr{'y' if len(stale) == 1 else 'ies'} no longer match any finding (stale, or the file moved): "
			  + ", ".join(stale) + ". They still work as v1 for now; remove them if they are obsolete.", file=sys.stderr)
	return 0


def _executable() -> str:
	"""Absolute path of this tool, so the hook works when `smart-commit-guard` is not on git's PATH (venv, uv run)."""
	me = Path(sys.argv[0])
	if me.name in ("smart-commit-guard", "smart-commit-guard.exe") and me.exists():
		return str(me.resolve())
	return shutil.which("smart-commit-guard") or "smart-commit-guard"


def _uvx_spec() -> str:
	"""`--from 'smart-commit-guard>=0.2,<0.3' `: the uvx fallback follows the installing version's minor range, so a hook never
	silently jumps to a release that changes behaviour. Empty when the version is unknown (a checkout)."""
	m = re.match(r"(\d+)\.(\d+)", __version__)
	return f"--from 'smart-commit-guard>={m[1]}.{m[2]},<{m[1]}.{int(m[2]) + 1}' " if m else ""


def _hook_text(name: str, shared: bool, exe: str = "") -> str:
	"""A hook script (with `@CHAIN@` and `@NAME@` still to fill in): per-clone with an absolute path, or shared and path-free."""
	args = dict(HOOKS)[name]
	text = SHARED_HOOK.replace("@UVX@", _uvx_spec()) if shared else HOOK.format(exe=shlex.quote(exe))
	return text.replace("@ARGS@", args)


def _chain(text: str, name: str, chained: bool) -> str:
	return text.replace("@CHAIN@", CHAIN_BLOCK.replace("@NAME@", name) if chained else "")


def _is_ours(hook: Path) -> bool:
	return "smart-commit-guard" in hook.read_text(encoding="utf-8", errors="replace")


def _check_hook(hook: Path, force: bool, chain: bool) -> None:
	"""Refuse before anything is written, so a refusal never leaves one hook installed and the other not."""
	local = hook.with_name(hook.name + ".local")
	if hook.exists() and not _is_ours(hook) and chain:
		if local.exists() and not force:
			raise ToolError(f"{local} already exists; use --force to overwrite it")
	elif hook.exists() and not force:
		raise ToolError(f"{hook} already exists; use --force to overwrite it, or --chain to keep it and run it first")


def _write_hook(hook: Path, text: str, force: bool, chain: bool = False) -> None:
	"""Write a hook. With `chain`, a hook that is already there (not ours) is kept as `<name>.local` and called first."""
	_check_hook(hook, force, chain)
	local = hook.with_name(hook.name + ".local")
	if hook.exists() and not _is_ours(hook) and chain:
		hook.replace(local)
		print(f"kept the existing hook as {local}; it runs before the scan")
	text = _chain(text, hook.name, chain and local.exists())
	hook.parent.mkdir(parents=True, exist_ok=True)
	hook.write_bytes(text.encode("utf-8"))   # LF endings on every OS: write_text would turn them into CRLF on Windows
	hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
	print(f"installed {hook}")


def _install_hook(force: bool, shared: bool, chain: bool = False) -> int:
	if not shared:
		exe = _executable()
		targets = [(Path(git.run("rev-parse", "--git-path", f"hooks/{name}").strip()), _hook_text(name, False, exe)) for name, _ in HOOKS]
		for hook, _ in targets:
			_check_hook(hook, force, chain)
		for hook, text in targets:
			_write_hook(hook, text, force, chain)
		return 0
	top = Path(git.run("rev-parse", "--show-toplevel").strip())
	try:
		current = git.run("config", "core.hooksPath").strip()
	except GitError:   # exit 1: not set
		current = ""
	if current not in ("", SHARED_DIR) and not force:
		raise ToolError(f"core.hooksPath is already set to {current!r}; use --force to replace it")
	targets = [(top / SHARED_DIR / name, _hook_text(name, True)) for name, _ in HOOKS]
	for hook, _ in targets:
		_check_hook(hook, force, chain)
	for hook, text in targets:
		_write_hook(hook, text, force, chain)
	git.run("config", "core.hooksPath", SHARED_DIR)
	attrs = top / ".gitattributes"
	existing = attrs.read_text(encoding="utf-8", errors="replace") if attrs.exists() else ""
	if GITATTRIBUTES_LINE not in existing.splitlines():
		attrs.write_bytes((existing + ("" if existing.endswith("\n") or not existing else "\n") + GITATTRIBUTES_LINE + "\n").encode("utf-8"))
	print(f"set core.hooksPath={SHARED_DIR}. Commit {SHARED_DIR}/ and .gitattributes; each clone then runs "
		  f"`git config core.hooksPath {SHARED_DIR}` once (or `smart-commit-guard install-hook --shared`).")
	return 0


def _hook_tool(hook_text: str, root: Path) -> tuple[str, str] | None:
	"""(description, executable or '') the hook would run, resolved the way the hook resolves it; None if it cannot find any."""
	if m := re.search(r"^exe=(.+)$", hook_text, re.MULTILINE):   # per-clone hook: the absolute path baked in at install time
		exe = shlex.split(m[1])[0] if m[1].strip() else ""
		found = exe if Path(exe).is_file() else shutil.which(exe)
		return (f"{found}", found) if found else None
	for candidate in (shutil.which("smart-commit-guard"), root / ".venv" / "bin" / "smart-commit-guard",
					  root / ".venv" / "Scripts" / "smart-commit-guard.exe"):
		if candidate and Path(candidate).is_file():
			return str(candidate), str(candidate)
	if shutil.which("uvx"):
		return "uvx (downloads and caches the release)", ""
	return None


def _tool_version(exe: str) -> str:
	try:
		r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15, check=False)
	except (OSError, subprocess.SubprocessError):
		return "unknown version"
	return r.stdout.strip() or "unknown version"


def _user_config(action: str, force: bool, env: Mapping[str, str]) -> int:
	if action == "path":
		path = user_config.config_path(env)
		print(path if path else "unknown: set SECRET_GUARD_CONFIG")
		return 0
	print(f"wrote {user_config.init(env, force=force)}")
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
			root = git.repo_root() or Path.cwd()
			tool = _hook_tool(text, root)
			if tool is None:
				say("FAIL", "hook tool", "the hook cannot find smart-commit-guard (not on PATH, no .venv, no uvx): every commit "
										"would be blocked with an install message")
			else:
				where, exe = tool
				say("ok", "hook tool", f"{where}" + (f" ({_tool_version(exe)})" if exe else ""))
			try:
				hooks_path = git.run("config", "core.hooksPath").strip()
			except GitError:
				hooks_path = ""
			for name, _ in HOOKS:
				path = hook.with_name(name)
				if hooks_path == SHARED_DIR and path.is_file():
					expected = _chain(_hook_text(name, True), name, path.with_name(name + ".local").exists())
					if path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n") != expected:
						say("WARN", "shared hook", f"{path} differs from the template of smart-commit-guard {__version__}: it may be "
												   "stale (run `smart-commit-guard install-hook --shared --force`, then commit it)")
		msg_hook = hook.with_name("commit-msg")
		if not msg_hook.is_file() or "scan --message" not in msg_hook.read_text(encoding="utf-8", errors="replace"):
			say("WARN", "commit-msg hook", f"{msg_hook} is missing: commit messages are not scanned for secrets. Run "
										   "`smart-commit-guard install-hook` (or `install-hook --shared`) again")
		elif not os.access(msg_hook, os.X_OK):
			say("WARN", "commit-msg hook", f"{msg_hook} is not executable (chmod +x)")
		else:
			say("ok", "commit-msg hook", str(msg_hook))
	probe = AddedLine("doctor.py", 1, 'KEY = "' + "AKIA" + 'IOSFODNN7EXAMPLE"')   # assembled so this file never trips the scanner
	if scan([probe], None).exit_code == 1:
		say("ok", "rules", "a synthetic AWS key is blocked")
	else:
		say("FAIL", "rules", "a synthetic AWS key was not blocked")
	try:
		uc_path = user_config.config_path(env)
		if uc_path and uc_path.is_file():
			say("ok", "user config", str(uc_path))
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
	src.add_argument("--message", metavar="FILE", help="a commit message file (what the commit-msg hook runs); rule hits block, "
													   "candidates only warn")
	src.add_argument("--text", choices=["-"], help="text on stdin, scanned like a commit message (for example a PR title and body)")
	sc.add_argument("--messages", action="store_true", help="with --diff: also scan the message of every commit in the range")
	sc.add_argument("--format", choices=report.FORMATS, default="text",
					help="text (with GitHub Actions annotations when GITHUB_ACTIONS=true), json, or sarif for code scanning")
	sc.add_argument("--json", action="store_true", help="same as --format json")
	sc.add_argument("--no-model", action="store_true", help="rules only")
	sc.add_argument("--baseline", metavar="FILE", help="ignore the findings recorded in this file (see `baseline create`), "
													   "so only new ones fail; for adopting the tool on an existing repo")
	sc.add_argument("--config-from", metavar="REF", help=f"read {CONFIG_NAME} from this revision (for example origin/main) "
														 "instead of the working tree, so a pull request cannot change its own rules")
	ih = sub.add_parser("install-hook", help="install a git pre-commit hook")
	ih.add_argument("--force", action="store_true")
	ih.add_argument("--chain", action="store_true",
					help="keep an existing pre-commit hook (husky, lefthook, a custom one) as pre-commit.local and run it before the scan")
	ih.add_argument("--shared", action="store_true",
					help="write a committable .githooks/pre-commit and set core.hooksPath, so every clone shares the gate")
	sub.add_parser("doctor", help="check that the hook, rules and model are working")
	bl = sub.add_parser("baseline", help="record the current findings so that only new ones fail")
	bl.add_argument("action", choices=["create"])
	bl.add_argument("--output", "-o", default=".secret-guard-baseline.json", metavar="FILE")
	bl.add_argument("--no-model", action="store_true", help="rules only: candidates are recorded as warnings")
	uc = sub.add_parser("config", help="your per-user settings file (which model to use)")
	uc.add_argument("action", choices=["init", "path"], help="init writes a commented template; path prints where the file is")
	uc.add_argument("--force", action="store_true", help="with init: overwrite an existing file")
	al = sub.add_parser("allowlist", help="maintain the allowlist in .secret-guard.toml")
	al.add_argument("action", choices=["migrate"], help="rewrite v1 fingerprints to v2 (hash of the stripped line)")
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
		if args.command == "install-hook":
			return _install_hook(args.force, args.shared, args.chain)
		if args.command == "baseline":
			return _baseline_create(args.output, args.no_model, env, decider)
		if args.command == "config":
			return _user_config(args.action, args.force, env)
		if args.command == "allowlist":
			return _allowlist_migrate(env)
		return _doctor(env, decider)
	except Exception as e:  # noqa: BLE001  exit 1 must only ever mean "a finding blocked": a crash is a tool error
		if env.get(DEBUG_ENV) == "1":
			traceback.print_exc()
		message = str(e) if isinstance(e, (ToolError, ConfigError, GitError)) else f"unexpected {type(e).__name__}: {e}"
		print(f"smart-commit-guard: {message}", file=sys.stderr)
		if machine and args.format == "json":
			print(report.error_json(message))
		return 2
