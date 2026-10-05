"""Decision-model client for the `/v1/systemone` protocol."""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Sequence
from typing import Protocol

MAX_BATCH = 1   # measured: jevk5:4b scores a line very differently by position in a batch (evals/), alone it is accurate
MAX_ITEM_CHARS = 300

def _question(i: int) -> dict:
	"""One question per `items[i]`, so the model knows which item of the batch is meant."""
	return {
		"type": "noul",
		"instructions": (f"Does `items[{i}].line` contain a real, unmasked credential (password, API key, token, private "
						 "key or similar secret) that should not be committed to version control?"),
		"criteria": {
			"true": "A hardcoded live secret, key or credential value.",
			"false": "A placeholder, mock or test value, an environment-variable or config reference, a masked value "
					 "(runs of A/a/9/*), or a public identifier.",
		},
	}


class DeciderUnavailable(Exception):
	"""Unreachable, timed out, malformed or incomplete answer."""


class Decider(Protocol):
	def judge(self, items: Sequence[tuple[str, str]]) -> list[float]:
		"""(path, line text) -> P(real credential) per item, at most MAX_BATCH items. Raises DeciderUnavailable."""
		...


def _urllib_post(url: str, payload: dict, timeout: float, headers: dict[str, str]) -> dict:
	req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
								 headers={"Content-Type": "application/json", **headers})
	with urllib.request.urlopen(req, timeout=timeout) as resp:
		return json.loads(resp.read())


class HttpDecider:
	def __init__(self, base_url: str, model: str | None, timeout: float, api_key: str | None = None,
				 post: Callable[[str, dict, float], dict] | None = None):
		self._url = base_url.rstrip("/") + "/v1/systemone"
		self._model, self._timeout = model, timeout
		headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
		self._post = post or (lambda url, payload, t: _urllib_post(url, payload, t, headers))

	def judge(self, items: Sequence[tuple[str, str]]) -> list[float]:
		if not items:
			return []
		payload: dict = {
			"state": {"items": [{"path": p, "line": t[:MAX_ITEM_CHARS]} for p, t in items]},
			"questions": {f"item_{i}": _question(i) for i in range(len(items))},
		}
		if self._model:
			payload["model"] = self._model
		try:
			answers = self._post(self._url, payload, self._timeout)["answers"]
			out = []
			for i in range(len(items)):
				a = answers[f"item_{i}"]
				if a["type"] != "noul":
					raise DeciderUnavailable(f"item_{i}: expected a noul answer, got {a['type']!r}")
				out.append(float(a["noul"]))
			return out
		except DeciderUnavailable:
			raise
		except (OSError, TimeoutError, KeyError, TypeError, ValueError) as e:  # urllib/socket errors are OSError
			raise DeciderUnavailable(f"{type(e).__name__}: {e}") from e
