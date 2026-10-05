"""Environment configuration."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class ConfigError(Exception):
	pass


def _float(env: Mapping[str, str], key: str, default: float) -> float:
	raw = env.get(key)
	if raw in (None, ""):
		return default
	try:
		return float(raw)
	except ValueError as e:
		raise ConfigError(f"{key} must be a number, got {raw!r}") from e


@dataclass(frozen=True)
class Config:
	base_url: str = "http://localhost:11435"
	model: str | None = None
	api_key: str | None = None
	timeout: float = 10.0
	allow_hosted: bool = False
	block_at: float = 0.85
	warn_at: float = 0.5

	@property
	def is_hosted(self) -> bool:
		"""False only for localhost, 127.0.0.1 and [::1]."""
		return (urlparse(self.base_url).hostname or "") not in _LOOPBACK

	@classmethod
	def from_env(cls, env: Mapping[str, str]) -> Config:
		"""Reads SECRET_GUARD_*. Raises ConfigError for a hosted base URL without SECRET_GUARD_ALLOW_HOSTED=1."""
		d = cls()
		c = cls(
			base_url=env.get("SECRET_GUARD_BASE_URL") or d.base_url,
			model=env.get("SECRET_GUARD_MODEL") or None,
			api_key=env.get("SECRET_GUARD_API_KEY") or None,
			timeout=_float(env, "SECRET_GUARD_TIMEOUT", d.timeout),
			allow_hosted=env.get("SECRET_GUARD_ALLOW_HOSTED") == "1",
			block_at=_float(env, "SECRET_GUARD_BLOCK_AT", d.block_at),
			warn_at=_float(env, "SECRET_GUARD_WARN_AT", d.warn_at),
		)
		if c.is_hosted and not c.allow_hosted:
			raise ConfigError(f"{c.base_url} is not a local server; set SECRET_GUARD_ALLOW_HOSTED=1 to send masked "
							  "snippets to it")
		if not 0 <= c.warn_at <= c.block_at <= 1:
			raise ConfigError("thresholds must satisfy 0 <= SECRET_GUARD_WARN_AT <= SECRET_GUARD_BLOCK_AT <= 1")
		return c
