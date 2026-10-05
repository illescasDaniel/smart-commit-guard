"""Decision-model client for the `/v1/systemone` protocol."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

MAX_BATCH = 30
MAX_ITEM_CHARS = 300


class DeciderUnavailable(Exception):
	"""Unreachable, timed out, malformed or incomplete answer."""


class Decider(Protocol):
	def judge(self, items: Sequence[tuple[str, str]]) -> list[float]:
		"""(path, line text) -> P(real credential) per item, at most MAX_BATCH items. Raises DeciderUnavailable."""
		...


class HttpDecider:
	def __init__(self, base_url: str, model: str | None, timeout: float, api_key: str | None = None,
				 post: Callable[[str, dict, float], dict] | None = None):
		raise NotImplementedError

	def judge(self, items: Sequence[tuple[str, str]]) -> list[float]:
		raise NotImplementedError
