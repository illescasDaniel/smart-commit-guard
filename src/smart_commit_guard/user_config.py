"""Per-user settings: `~/.config/smart-commit-guard/config.json` (comments allowed), the place to choose a model.

It is the user's own file, outside every repository, so unlike `.secret-guard.toml` it may name the server, the key and the
hosted opt-in. Each key becomes the matching `SECRET_GUARD_*` variable unless that variable is set: environment wins."""
from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Mapping
from pathlib import Path

CONFIG_ENV = "SECRET_GUARD_CONFIG"   # an explicit path (and `none`-like use in tests): wins over the default location
_KEYS = {   # key -> (SECRET_GUARD_* variable, accepted types)
	"base_url": ("SECRET_GUARD_BASE_URL", (str,)), "model": ("SECRET_GUARD_MODEL", (str,)),
	"api_key": ("SECRET_GUARD_API_KEY", (str,)), "timeout": ("SECRET_GUARD_TIMEOUT", (int, float)),
	"allow_hosted": ("SECRET_GUARD_ALLOW_HOSTED", (bool,)), "hosted_scope": ("SECRET_GUARD_HOSTED_SCOPE", (str,)),
	"budget": ("SECRET_GUARD_BUDGET", (int, float)), "block_at": ("SECRET_GUARD_BLOCK_AT", (int, float)),
	"warn_at": ("SECRET_GUARD_WARN_AT", (int, float)),
}
_EXTRA = {"api_key_env": "the name of an environment variable that holds the API key (keeps the key out of the file)"}

TEMPLATE = """\
// smart-commit-guard user settings. Comments (// and /* */) are allowed in this file.
// Environment variables (SECRET_GUARD_BASE_URL, SECRET_GUARD_MODEL, ...) override anything here.
{
	// The default: a local ollaya server and the model the thresholds were calibrated on. Nothing leaves your machine.
	"base_url": "http://localhost:11435",
	"model": "jevk5:4b"

	// Another local model (it needs its own thresholds, see evals/thresholds.json for `jeb:4b` and `snap:2b`):
	// "model": "jeb:4b", "block_at": 0.5, "warn_at": 0.4

	// A hosted model, for example TypeSafe Jev. Candidate lines (which may contain real secrets) are sent there UNMASKED,
	// so only use a server you would trust with the secrets themselves. Keep the key out of the file with api_key_env:
	//   "base_url": "https://api.typesafe.ai",
	//   "model": "jev-latest",
	//   "allow_hosted": true,
	//   "api_key_env": "TYPESAFE_API_KEY",
	//   "hosted_scope": "ci"      // "ci": the commit hook never calls the hosted model (rules plus warnings); CI does
}
"""


def config_path(env: Mapping[str, str]) -> Path | None:
	if explicit := env.get(CONFIG_ENV):
		return Path(explicit)
	if xdg := env.get("XDG_CONFIG_HOME"):
		return Path(xdg) / "smart-commit-guard" / "config.json"
	if appdata := env.get("APPDATA"):   # Windows
		return Path(appdata) / "smart-commit-guard" / "config.json"
	if home := env.get("HOME") or env.get("USERPROFILE"):
		return Path(home) / ".config" / "smart-commit-guard" / "config.json"
	return None


def strip_comments(text: str) -> str:
	"""Remove `//` and `/* */` comments outside strings, so the file stays plain JSON for everything else."""
	out, i, n, in_str = [], 0, len(text), False
	while i < n:
		c = text[i]
		if in_str:
			out.append(c)
			if c == "\\" and i + 1 < n:
				out.append(text[i + 1])
				i += 1
			elif c == '"':
				in_str = False
		elif c == '"':
			in_str = True
			out.append(c)
		elif text.startswith("//", i):
			while i < n and text[i] != "\n":
				i += 1
			continue
		elif text.startswith("/*", i):
			end = text.find("*/", i + 2)
			i = n if end < 0 else end + 2
			continue
		else:
			out.append(c)
		i += 1
	return "".join(out)


def _error(path: Path, message: str) -> Exception:
	from .config import ConfigError
	return ConfigError(f"{path}: {message}")


def read(path: Path, env: Mapping[str, str]) -> dict[str, str]:
	"""The file as `SECRET_GUARD_*` variables. Raises ConfigError for anything malformed."""
	try:
		text = path.read_text(encoding="utf-8")
	except OSError as e:
		raise _error(path, f"cannot read: {e}") from e
	try:
		data = json.loads(strip_comments(text))
	except json.JSONDecodeError as e:
		raise _error(path, f"not valid JSON ({e})") from e
	if not isinstance(data, dict):
		raise _error(path, "must be a JSON object")
	out: dict[str, str] = {}
	for key, value in data.items():
		if key == "api_key_env":
			if not isinstance(value, str) or not value:
				raise _error(path, "api_key_env must be the name of an environment variable")
			if env.get(value):
				out.setdefault("SECRET_GUARD_API_KEY", env[value])
			continue
		if key not in _KEYS:
			allowed = ", ".join(sorted([*_KEYS, *_EXTRA]))
			raise _error(path, f"unknown key {key!r} (allowed: {allowed})")
		var, types = _KEYS[key]
		if not isinstance(value, types) or (isinstance(value, bool) and bool not in types):
			raise _error(path, f"{key} must be {' or '.join(t.__name__ for t in types)}")
		out[var] = ("1" if value else "0") if isinstance(value, bool) else str(value)
	if "api_key" in data and os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
		print(f"smart-commit-guard: warning: {path} holds an API key and is readable by others; run chmod 600 on it "
			  "(or use api_key_env)", file=sys.stderr)
	return out


def with_user_settings(env: Mapping[str, str]) -> Mapping[str, str]:
	"""`env` plus the settings file for every variable `env` leaves unset or empty. No file: `env` unchanged."""
	path = config_path(env)
	if path is None or not path.is_file():
		return env
	return {**read(path, env), **{k: v for k, v in env.items() if v != ""}}


def init(env: Mapping[str, str], *, force: bool = False) -> Path:
	path = config_path(env)
	if path is None:
		from .config import ConfigError
		raise ConfigError("cannot tell where your config directory is: set SECRET_GUARD_CONFIG to a path")
	if path.exists() and not force:
		from .config import ConfigError
		raise ConfigError(f"{path} already exists (use --force to overwrite)")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(TEMPLATE, encoding="utf-8")
	if os.name == "posix":
		path.chmod(0o600)
	return path
