import pytest

from secret_guard.config import Config, ConfigError


def test_given_no_env_when_loading_then_defaults_point_at_a_local_server():
	c = Config.from_env({})
	assert not c.is_hosted and c.block_at > c.warn_at


@pytest.mark.parametrize("url", ["http://localhost:11435", "http://127.0.0.1:9", "http://[::1]:9"])
def test_given_a_loopback_url_when_loading_then_it_is_not_hosted(url):
	assert not Config.from_env({"SECRET_GUARD_BASE_URL": url}).is_hosted


def test_given_a_hosted_url_without_opt_in_when_loading_then_it_is_refused():
	with pytest.raises(ConfigError):
		Config.from_env({"SECRET_GUARD_BASE_URL": "https://api.example.com"})


def test_given_a_hosted_url_with_opt_in_when_loading_then_it_is_hosted_and_allowed():
	c = Config.from_env({"SECRET_GUARD_BASE_URL": "https://api.example.com", "SECRET_GUARD_ALLOW_HOSTED": "1"})
	assert c.is_hosted and c.allow_hosted


def test_given_threshold_and_timeout_env_when_loading_then_they_are_parsed():
	c = Config.from_env({"SECRET_GUARD_BLOCK_AT": "0.9", "SECRET_GUARD_WARN_AT": "0.4", "SECRET_GUARD_TIMEOUT": "3"})
	assert (c.block_at, c.warn_at, c.timeout) == (0.9, 0.4, 3.0)
