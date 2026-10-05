"""Command line: `secret-guard scan --staged | --diff <range> | --files ...`."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import stat
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from .config import Config, ConfigError
from .decider import Decider, HttpDecider
from .diff import parse_added_lines
from .policy import scan
from .redact import fingerprint
from .types import AddedLine, ScanResult

HOOK = "#!/bin/sh\n# installed by secret-guard\nexec secret-guard scan --staged\n"


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
		print("secret-guard: commit blocked. Move secrets to environment variables, or allowlist a false positive "
			  "in .secret-guard.toml.", file=sys.stderr)


def _clip(s: str, n: int = 160) -> str:
	return s if len(s) <= n else s[:n] + "..."


def _scan(args: argparse.Namespace, env: Mapping[str, str], decider: Decider | None) -> int:
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


def _install_hook(force: bool) -> int:
	hook = Path(_git("rev-parse", "--git-path", "hooks/pre-commit").strip())
	if hook.exists() and not force:
		raise ToolError(f"{hook} already exists; use --force to overwrite it")
	hook.parent.mkdir(parents=True, exist_ok=True)
	hook.write_text(HOOK)
	hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
	print(f"installed {hook}")
	return 0


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
	try:
		args = parser.parse_args(argv)
	except SystemExit as e:
		return 2 if e.code else 0
	env = os.environ if env is None else env
	try:
		return _scan(args, env, decider) if args.command == "scan" else _install_hook(args.force)
	except (ToolError, ConfigError) as e:
		print(f"secret-guard: {e}", file=sys.stderr)
		return 2
