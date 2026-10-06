"""Configuration: SECRET_GUARD_* environment variables, the user's `config.json` (user_config.py) and the repo's `.secret-guard.toml`."""
from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .user_config import with_user_settings

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
CONFIG_NAME = ".secret-guard.toml"
HOSTED_SCOPES = ("all", "ci")   # where a hosted model may be used: everywhere, or only in CI-style scans (not the commit hook)
_TOP_LEVEL_KEYS = {"skip": "a list of glob strings", "allowlist": "a list of fingerprint strings",
				   "allow": "a list of tables, for example [[allow]] fingerprint = \"...\" reason = \"...\"",
				   "allow_inline": "true or false", "model": "a table, for example [model] hosted_scope = \"ci\" or name = \"...\", block_at = 0.6"}
_ALLOW_KEYS = {"fingerprint", "path", "reason"}
_MODEL_KEYS = {"hosted_scope", "name", "block_at", "warn_at"}   # never base_url: a pull request must not choose where data goes


class ConfigError(Exception):
	pass


def is_loopback_host(host: str) -> bool:
	return host in _LOOPBACK


def _float(env: Mapping[str, str], key: str, default: float) -> float:
	raw = env.get(key)
	if raw in (None, ""):
		return default
	try:
		return float(raw)
	except ValueError as e:
		raise ConfigError(f"{key} must be a number, got {raw!r}") from e


def _scope(value: str, source: str) -> str:
	if value not in HOSTED_SCOPES:
		raise ConfigError(f"{source} must be one of {', '.join(HOSTED_SCOPES)}, got {value!r}")
	return value


@dataclass(frozen=True)
class AllowEntry:
	"""`[[allow]]`: a fingerprint with the reason a reviewer should see, and optionally the paths it may apply to."""
	fingerprint: str
	reason: str
	path: str | None = None


@dataclass(frozen=True)
class RepoSettings:
	"""What `.secret-guard.toml` may say. It is part of the diff it guards, so it can only narrow where data goes."""
	skip: tuple[str, ...] = ()
	allowlist: frozenset[str] = frozenset()
	hosted_scope: str | None = None
	allow: tuple[AllowEntry, ...] = ()
	model_name: str | None = None   # `[model]` name / block_at / warn_at: thresholds are per model, so they live with the repo's choice
	block_at: float | None = None
	warn_at: float | None = None
	allow_inline: bool = False   # honour `# smart-commit-guard: allow` on a line; off by default because it is easy to abuse

	@property
	def fingerprints(self) -> frozenset[str]:
		"""Every accepted fingerprint: the plain `allowlist` plus the `[[allow]]` entries."""
		return self.allowlist | {e.fingerprint for e in self.allow}

	@property
	def allow_paths(self) -> dict[str, str]:
		return {e.fingerprint: e.path for e in self.allow if e.path}

	@classmethod
	def parse(cls, text: str, source: str = CONFIG_NAME) -> RepoSettings:
		try:
			data = tomllib.loads(text)
		except tomllib.TOMLDecodeError as e:
			raise ConfigError(f"cannot parse {source}: {e}") from e
		for key in data:
			if key not in _TOP_LEVEL_KEYS:
				raise ConfigError(f"{source}: unknown key {key!r} (allowed: {', '.join(_TOP_LEVEL_KEYS)})")
		lists: dict[str, list[str]] = {}
		for key in ("skip", "allowlist"):
			value = data.get(key, [])
			if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
				raise ConfigError(f"{source}: {key!r} must be {_TOP_LEVEL_KEYS[key]}, for example {key} = [\"...\"]")
			lists[key] = value
		allow = []
		raw_allow = data.get("allow", [])
		if not isinstance(raw_allow, list) or not all(isinstance(e, dict) for e in raw_allow):
			raise ConfigError(f"{source}: 'allow' must be {_TOP_LEVEL_KEYS['allow']}")
		for entry in raw_allow:
			for key in entry:
				if key not in _ALLOW_KEYS:
					raise ConfigError(f"{source}: unknown key {key!r} in [[allow]] (allowed: {', '.join(sorted(_ALLOW_KEYS))})")
			for key in ("fingerprint", "reason"):
				if not isinstance(entry.get(key), str) or not entry[key].strip():
					raise ConfigError(f"{source}: every [[allow]] entry needs a non-empty string {key!r}"
									  + (" (say why, so reviewers can judge it)" if key == "reason" else ""))
			if "path" in entry and not isinstance(entry["path"], str):
				raise ConfigError(f"{source}: [[allow]] 'path' must be a glob string")
			allow.append(AllowEntry(entry["fingerprint"], entry["reason"], entry.get("path")))
		inline = data.get("allow_inline", False)
		if not isinstance(inline, bool):
			raise ConfigError(f"{source}: 'allow_inline' must be true or false")
		model = data.get("model", {})
		if not isinstance(model, dict):
			raise ConfigError(f"{source}: 'model' must be a table, for example [model] hosted_scope = \"ci\"")
		for key in model:
			if key not in _MODEL_KEYS:
				raise ConfigError(f"{source}: unknown key {key!r} in [model] (allowed: {', '.join(sorted(_MODEL_KEYS))})")
		scope = model.get("hosted_scope")
		if scope is not None:
			if not isinstance(scope, str):
				raise ConfigError(f"{source}: [model] hosted_scope must be one of {', '.join(HOSTED_SCOPES)}")
			scope = _scope(scope, f"{source}: [model] hosted_scope")
		name = model.get("name")
		if name is not None and (not isinstance(name, str) or not name.strip()):
			raise ConfigError(f"{source}: [model] name must be a non-empty string")
		numbers: dict[str, float | None] = {}
		for key in ("block_at", "warn_at"):
			v = model.get(key)
			if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1):
				raise ConfigError(f"{source}: [model] {key} must be a number between 0 and 1")
			numbers[key] = None if v is None else float(v)
		return cls(tuple(lists["skip"]), frozenset(lists["allowlist"]), scope, tuple(allow), name, numbers["block_at"],
				   numbers["warn_at"], inline)

	@classmethod
	def load(cls, root: Path) -> RepoSettings:
		path = root / CONFIG_NAME
		if not path.is_file():
			return cls()
		try:
			text = path.read_text(encoding="utf-8", errors="replace")
		except OSError as e:
			raise ConfigError(f"cannot read {path}: {e}") from e
		return cls.parse(text)


@dataclass(frozen=True)
class Config:
	base_url: str = "http://localhost:11435"
	model: str | None = "jevk5:4b"   # the model the thresholds below were calibrated on
	api_key: str | None = None
	timeout: float = 10.0
	allow_hosted: bool = False
	hosted_scope: str = "all"
	budget: float | None = None   # total seconds of model time per scan; None: the caller's default for the scan mode
	block_at: float = 0.5   # calibrated for jevk5:4b (evals/); rerun the eval before using another model
	warn_at: float = 0.4

	@property
	def is_hosted(self) -> bool:
		"""False only for localhost, 127.0.0.1 and [::1]."""
		return not is_loopback_host(urlparse(self.base_url).hostname or "")

	@classmethod
	def from_env(cls, env: Mapping[str, str], repo: RepoSettings | None = None) -> Config:
		"""Reads SECRET_GUARD_*. Raises ConfigError for a hosted base URL without SECRET_GUARD_ALLOW_HOSTED=1, or one that
		is not https. The repo file can only narrow the hosted scope: the most restrictive of file and environment wins."""
		env = with_user_settings(env)
		d = cls()
		scope = _scope(env.get("SECRET_GUARD_HOSTED_SCOPE") or d.hosted_scope, "SECRET_GUARD_HOSTED_SCOPE")
		if repo and repo.hosted_scope == "ci":
			scope = "ci"
		budget = _float(env, "SECRET_GUARD_BUDGET", 0.0) or None
		c = cls(
			base_url=env.get("SECRET_GUARD_BASE_URL") or d.base_url,
			model=env.get("SECRET_GUARD_MODEL") or (repo.model_name if repo else None) or d.model,
			api_key=env.get("SECRET_GUARD_API_KEY") or None,
			timeout=_float(env, "SECRET_GUARD_TIMEOUT", d.timeout),
			allow_hosted=env.get("SECRET_GUARD_ALLOW_HOSTED") == "1",
			hosted_scope=scope,
			budget=budget,
			block_at=_float(env, "SECRET_GUARD_BLOCK_AT", repo.block_at if repo and repo.block_at is not None else d.block_at),
			warn_at=_float(env, "SECRET_GUARD_WARN_AT", repo.warn_at if repo and repo.warn_at is not None else d.warn_at),
		)
		if c.timeout <= 0:
			raise ConfigError("SECRET_GUARD_TIMEOUT must be greater than 0")
		if budget is not None and budget < 0:
			raise ConfigError("SECRET_GUARD_BUDGET must be greater than 0")
		if c.is_hosted:
			if not c.allow_hosted:
				raise ConfigError(f"{c.base_url} is not a local server; set SECRET_GUARD_ALLOW_HOSTED=1 to send candidate "
								  "lines (which may contain real secrets) to it")
			if urlparse(c.base_url).scheme != "https" and env.get("SECRET_GUARD_ALLOW_INSECURE") != "1":
				raise ConfigError(f"{c.base_url} is not https: the candidate lines and the API key would travel in clear text; "
								  "use an https URL (or SECRET_GUARD_ALLOW_INSECURE=1 on a network you fully control)")
		if not 0 <= c.warn_at <= c.block_at <= 1:
			raise ConfigError("thresholds must satisfy 0 <= SECRET_GUARD_WARN_AT <= SECRET_GUARD_BLOCK_AT <= 1")
		return c
