"""Opt-in start of a local ollaya server, so the commit hook works without a service the user has to keep running.

Only the user's own settings file or environment can turn it on (`autostart`), never `.secret-guard.toml`: a pull request
must not be able to make a commit hook launch a program. It starts the first time a candidate line needs the model, so
commits without ambiguous lines never pay for it, and the server is left running afterwards (like a service)."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from urllib.parse import urlparse

from .config import is_loopback_host
from .decider import Decider, DeciderUnavailable

OLLAYA = "ollaya"
OLLAYA_PORT = 11435   # `ollaya serve` takes no options: it always listens here
START_WAIT = 20.0   # seconds to wait for the server to accept connections after starting it


def _reachable(host: str, port: int) -> bool:
	try:
		with socket.create_connection((host, port), timeout=0.5):
			return True
	except OSError:
		return False


def _spawn(exe: str) -> None:
	"""`<exe> serve`, detached from the hook: it must outlive the commit and must not hold the hook's pipes open."""
	kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
	if os.name == "nt":
		kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
	else:
		kwargs["start_new_session"] = True
	subprocess.Popen([exe, "serve"], **kwargs)


def ensure_server(base_url: str, *, wait: float = START_WAIT, which: Callable[[str], str | None] = shutil.which,
				  spawn: Callable[[str], None] = _spawn, reachable: Callable[[str, int], bool] = _reachable,
				  sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
	"""Returns once something accepts connections at `base_url`; starts `ollaya serve` first when nothing does.
	Raises DeciderUnavailable (with the reason) when it cannot."""
	parsed = urlparse(base_url)
	host, port = parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80)
	if reachable(host, port):
		return
	if not is_loopback_host(host):
		raise DeciderUnavailable(f"autostart only starts a local server, and {host} is not local")
	if port != OLLAYA_PORT:
		raise DeciderUnavailable(f"autostart starts `ollaya serve`, which listens on {OLLAYA_PORT}, not {port}")
	exe = which(OLLAYA)
	if exe is None:
		raise DeciderUnavailable(f"autostart: `{OLLAYA}` is not on PATH")
	print(f"smart-commit-guard: starting `{OLLAYA} serve` (autostart; it keeps running after this commit)", file=sys.stderr)
	try:
		spawn(exe)
	except OSError as e:
		raise DeciderUnavailable(f"autostart: cannot run {exe}: {e}") from e
	deadline = clock() + wait
	while clock() < deadline:
		if reachable(host, port):
			return
		sleep(0.2)
	raise DeciderUnavailable(f"autostart: {OLLAYA} did not accept connections within {wait:g} s")


class AutostartDecider:
	"""Starts the server on the first `judge` (and so never when no candidate needs the model); a failure is remembered."""

	def __init__(self, inner: Decider, ensure: Callable[[], None]):
		self._inner, self._ensure = inner, ensure
		self._done = False
		self._error: DeciderUnavailable | None = None

	def judge(self, items: Sequence[tuple[str, str]]) -> list[float]:
		if not self._done:
			self._done = True
			try:
				self._ensure()
			except DeciderUnavailable as e:
				self._error = e
		if self._error:
			raise self._error
		return self._inner.judge(items)
