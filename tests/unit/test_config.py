import pytest

from smart_commit_guard.config import Config, ConfigError


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


from smart_commit_guard.config import RepoSettings


def test_given_a_hosted_url_without_opt_in_when_loading_then_the_message_says_candidate_lines_may_hold_real_secrets():
	with pytest.raises(ConfigError, match=r"SECRET_GUARD_ALLOW_HOSTED=1 to send candidate lines \(which may contain real secrets\)"):
		Config.from_env({"SECRET_GUARD_BASE_URL": "https://api.example.com"})


def test_given_a_hosted_http_url_when_loading_then_it_is_refused_unless_insecure_is_explicitly_allowed():
	env = {"SECRET_GUARD_BASE_URL": "http://llm.internal:8080", "SECRET_GUARD_ALLOW_HOSTED": "1"}
	with pytest.raises(ConfigError, match="not https"):
		Config.from_env(env)
	assert Config.from_env({**env, "SECRET_GUARD_ALLOW_INSECURE": "1"}).is_hosted


@pytest.mark.parametrize("value", ["0", "-1"])
def test_given_a_non_positive_timeout_when_loading_then_it_is_refused(value):
	with pytest.raises(ConfigError, match="TIMEOUT"):
		Config.from_env({"SECRET_GUARD_TIMEOUT": value})


def test_given_a_budget_when_loading_then_it_is_parsed_and_unset_means_the_scan_default():
	assert Config.from_env({"SECRET_GUARD_BUDGET": "2.5"}).budget == 2.5
	assert Config.from_env({}).budget is None
	with pytest.raises(ConfigError):
		Config.from_env({"SECRET_GUARD_BUDGET": "-3"})


# 0.6.1: the scope can only be narrowed by the repo file, never widened


def test_given_no_setting_when_loading_then_the_hosted_scope_is_all():
	assert Config.from_env({}).hosted_scope == "all"


@pytest.mark.parametrize("env, repo, expected", [
	({}, None, "all"), ({"SECRET_GUARD_HOSTED_SCOPE": "ci"}, None, "ci"), ({}, "ci", "ci"),
	({"SECRET_GUARD_HOSTED_SCOPE": "all"}, "ci", "ci"), ({"SECRET_GUARD_HOSTED_SCOPE": "ci"}, "all", "ci"), ({}, "all", "all")])
def test_given_env_and_repo_scopes_when_loading_then_the_most_restrictive_wins(env, repo, expected):
	assert Config.from_env(env, RepoSettings(hosted_scope=repo)).hosted_scope == expected


def test_given_an_invalid_scope_in_the_environment_when_loading_then_it_is_refused_with_the_allowed_values():
	with pytest.raises(ConfigError, match="all, ci"):
		Config.from_env({"SECRET_GUARD_HOSTED_SCOPE": "sometimes"})


# 0.4: the repo file is validated


def test_given_a_valid_repo_file_when_parsing_then_the_settings_are_read():
	s = RepoSettings.parse('skip = ["tests/*"]\nallowlist = ["abc"]\n[model]\nhosted_scope = "ci"\n')
	assert s.skip == ("tests/*",) and s.allowlist == {"abc"} and s.hosted_scope == "ci"


@pytest.mark.parametrize("text, key", [('skip = "tests/*"', "skip"), ('allowlist = "abc"', "allowlist"), ('allow_list = []', "allow_list"),
									   ('skip = [1]', "skip"), ('[model]\nfoo = 1', "foo"), ('[model]\nhosted_scope = "x"', "hosted_scope")])
def test_given_an_invalid_repo_file_when_parsing_then_the_error_names_the_key(text, key):
	with pytest.raises(ConfigError, match=key):
		RepoSettings.parse(text)


def test_given_no_repo_file_when_loading_then_the_settings_are_empty(tmp_path):
	assert RepoSettings.load(tmp_path) == RepoSettings()


# [[allow]] entries and allow_inline


def test_given_allow_entries_when_parsing_then_fingerprints_and_path_globs_are_available():
	s = RepoSettings.parse('allowlist = ["a1"]\n[[allow]]\nfingerprint = "v2:b2"\nreason = "fixture"\npath = "tests/*"\n'
						   '[[allow]]\nfingerprint = "c3"\nreason = "docs example"\n')
	assert s.fingerprints == {"a1", "v2:b2", "c3"} and s.allow_paths == {"v2:b2": "tests/*"}


@pytest.mark.parametrize("text, needle", [
	('[[allow]]\nfingerprint = "x"', "reason"), ('[[allow]]\nfingerprint = "x"\nreason = " "', "reason"),
	('[[allow]]\nreason = "r"', "fingerprint"), ('[[allow]]\nfingerprint = "x"\nreason = "r"\nwhy = 1', "why"),
	('[[allow]]\nfingerprint = "x"\nreason = "r"\npath = 3', "path"), ('allow = ["x"]', "allow"), ('allow_inline = "yes"', "allow_inline")])
def test_given_a_malformed_allow_entry_when_parsing_then_the_error_names_the_problem(text, needle):
	with pytest.raises(ConfigError, match=needle):
		RepoSettings.parse(text)


def test_given_allow_inline_when_parsing_then_it_defaults_to_off():
	assert RepoSettings.parse("").allow_inline is False and RepoSettings.parse("allow_inline = true").allow_inline is True
