"""Environment configuration."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(Exception):
	pass


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
		raise NotImplementedError

	@classmethod
	def from_env(cls, env: Mapping[str, str]) -> Config:
		"""Reads SECRET_GUARD_*. Raises ConfigError for a hosted base URL without SECRET_GUARD_ALLOW_HOSTED=1."""
		raise NotImplementedError
