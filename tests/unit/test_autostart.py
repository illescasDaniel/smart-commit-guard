import pytest

from smart_commit_guard import user_config
from smart_commit_guard.autostart import AutostartDecider, ensure_server
from smart_commit_guard.config import Config, ConfigError, RepoSettings
from smart_commit_guard.decider import DeciderUnavailable

URL = "http://localhost:11435"


class Server:
	"""A fake machine: `up` says whether something listens, `spawn` can bring it up."""

	def __init__(self, up=False, comes_up=True, exe="/usr/bin/ollaya", spawn_error=None):
		self.up, self.comes_up, self.exe, self.spawn_error, self.spawned, self.now = up, comes_up, exe, spawn_error, [], 0.0

	def which(self, name):
		return self.exe if name == "ollaya" else None

	def spawn(self, exe):
		if self.spawn_error:
			raise self.spawn_error
		self.spawned.append(exe)
		if self.comes_up:
			self.up = True

	def reachable(self, host, port):
		return self.up

	def sleep(self, seconds):
		self.now += seconds

	def clock(self):
		return self.now


def ensure(server, url=URL, wait=20.0):
	ensure_server(url, wait=wait, which=server.which, spawn=server.spawn, reachable=server.reachable, sleep=server.sleep,
				  clock=server.clock)


def test_given_a_running_server_when_ensuring_then_nothing_is_started():
	s = Server(up=True)
	ensure(s)
	assert s.spawned == []


def test_given_no_server_when_ensuring_then_ollaya_serve_is_started_and_awaited(capsys):
	s = Server()
	ensure(s)
	assert s.spawned == ["/usr/bin/ollaya"] and "starting `ollaya serve`" in capsys.readouterr().err


def test_given_a_server_that_never_comes_up_when_ensuring_then_it_gives_up_after_the_wait():
	s = Server(comes_up=False)
	with pytest.raises(DeciderUnavailable, match="did not accept connections within 5 s"):
		ensure(s, wait=5.0)
	assert s.now >= 5.0


def test_given_ollaya_is_not_installed_when_ensuring_then_it_says_so():
	with pytest.raises(DeciderUnavailable, match="not on PATH"):
		ensure(Server(exe=None))


@pytest.mark.parametrize("url", ["https://api.typesafe.ai", "http://10.0.0.5:11435"])
def test_given_a_remote_server_when_ensuring_then_nothing_is_started(url):
	s = Server()
	with pytest.raises(DeciderUnavailable, match="not local"):
		ensure(s, url)
	assert s.spawned == []


def test_given_another_local_port_when_ensuring_then_nothing_is_started():
	s = Server()
	with pytest.raises(DeciderUnavailable, match="11435, not 8080"):
		ensure(s, "http://localhost:8080")
	assert s.spawned == []


def test_given_a_spawn_failure_when_ensuring_then_it_is_unavailable():
	with pytest.raises(DeciderUnavailable, match="cannot run"):
		ensure(Server(spawn_error=PermissionError("denied")))


class Inner:
	def __init__(self):
		self.calls = 0

	def judge(self, items):
		self.calls += 1
		return [0.9] * len(items)


def test_given_autostart_when_judging_twice_then_the_server_is_ensured_once_before_the_first_call():
	order, inner = [], Inner()
	d = AutostartDecider(inner, lambda: order.append(("ensure", inner.calls)))
	assert d.judge([("a", "b")]) == [0.9] and d.judge([("a", "b")]) == [0.9]
	assert order == [("ensure", 0)] and inner.calls == 2


def test_given_autostart_never_judging_then_the_server_is_never_started():
	ensured = []
	AutostartDecider(Inner(), lambda: ensured.append(1))
	assert ensured == []


def test_given_a_failed_start_when_judging_then_every_call_is_unavailable_and_the_model_is_not_called():
	inner = Inner()

	def fail():
		raise DeciderUnavailable("no ollaya")
	d = AutostartDecider(inner, fail)
	for _ in range(2):
		with pytest.raises(DeciderUnavailable, match="no ollaya"):
			d.judge([("a", "b")])
	assert inner.calls == 0


def test_autostart_is_off_by_default_and_the_settings_file_or_environment_turns_it_on(tmp_path):
	path = tmp_path / "config.json"
	path.write_text('{"autostart": true}', encoding="utf-8")
	path.chmod(0o600)
	assert Config.from_env({}).autostart is False
	assert Config.from_env({user_config.CONFIG_ENV: str(path)}).autostart is True
	assert Config.from_env({"SECRET_GUARD_AUTOSTART": "1"}).autostart is True
	assert Config.from_env({user_config.CONFIG_ENV: str(path), "SECRET_GUARD_AUTOSTART": "0"}).autostart is False


def test_given_autostart_in_the_repo_file_when_parsing_then_it_is_refused():
	with pytest.raises(ConfigError, match="unknown key"):
		RepoSettings.parse("[model]\nautostart = true\n")
	with pytest.raises(ConfigError, match="unknown key"):
		RepoSettings.parse("autostart = true\n")
