import pytest

from smart_commit_guard import user_config
from smart_commit_guard.cli import main
from smart_commit_guard.config import Config, ConfigError


def _env(tmp_path, text=None, **extra):
	path = tmp_path / "config.json"
	if text is not None:
		path.write_text(text, encoding="utf-8")
		path.chmod(0o600)
	return {"SECRET_GUARD_CONFIG": str(path), **extra}


def test_given_no_file_when_loading_then_the_defaults_apply(tmp_path):
	assert Config.from_env(_env(tmp_path)) == Config.from_env({})


def test_given_a_file_when_loading_then_its_keys_become_the_settings(tmp_path):
	env = _env(tmp_path, '{"model": "jeb:4b", "block_at": 0.6, "timeout": 3}')
	c = Config.from_env(env)
	assert (c.model, c.block_at, c.timeout) == ("jeb:4b", 0.6, 3.0)


def test_given_comments_when_loading_then_they_are_ignored_even_inside_urls(tmp_path):
	text = '// top\n{\n\t"base_url": "http://localhost:11435", /* x */ "model": "jeb:4b" // end\n}\n'
	assert Config.from_env(_env(tmp_path, text)).model == "jeb:4b"


def test_given_an_environment_variable_when_loading_then_it_beats_the_file(tmp_path):
	env = _env(tmp_path, '{"model": "jeb:4b"}', SECRET_GUARD_MODEL="snap:2b")
	assert Config.from_env(env).model == "snap:2b"


def test_given_an_empty_environment_variable_when_loading_then_the_file_still_applies(tmp_path):
	assert Config.from_env(_env(tmp_path, '{"model": "jeb:4b"}', SECRET_GUARD_MODEL="")).model == "jeb:4b"


def test_given_the_file_beats_the_repo_when_both_name_a_model(tmp_path):
	from smart_commit_guard.config import RepoSettings
	repo = RepoSettings.parse('[model]\nname = "snap:2b"\n')
	assert Config.from_env(_env(tmp_path, '{"model": "jeb:4b"}'), repo).model == "jeb:4b"


def test_given_a_hosted_url_without_the_opt_in_when_loading_then_it_is_refused(tmp_path):
	with pytest.raises(ConfigError, match="not a local server"):
		Config.from_env(_env(tmp_path, '{"base_url": "https://api.example.com"}'))


def test_given_a_hosted_file_with_the_opt_in_when_loading_then_it_works(tmp_path):
	text = '{"base_url": "https://api.example.com", "allow_hosted": true, "api_key_env": "MY_KEY", "hosted_scope": "ci"}'
	c = Config.from_env(_env(tmp_path, text, MY_KEY="k-123"))
	assert (c.is_hosted, c.api_key, c.hosted_scope) == (True, "k-123", "ci")


@pytest.mark.parametrize("text", ["[]", "{not json", '{"nope": 1}', '{"timeout": "3"}', '{"allow_hosted": 1}', '{"api_key_env": ""}'])
def test_given_a_malformed_file_when_loading_then_it_is_a_config_error(tmp_path, text):
	with pytest.raises(ConfigError, match="config.json"):
		Config.from_env(_env(tmp_path, text))


def test_the_template_is_valid_and_selects_the_default_model(tmp_path):
	c = Config.from_env(_env(tmp_path, user_config.TEMPLATE))
	assert (c.model, c.base_url) == ("jevk5:4b", "http://localhost:11435")


def test_the_hosted_example_in_the_template_is_valid_once_uncommented(tmp_path):
	lines = [ln.strip().removeprefix("//").strip() for ln in user_config.TEMPLATE.splitlines() if ln.strip().startswith('//   "')]
	text = "{" + "\n".join(lines) + "\n}"
	c = Config.from_env(_env(tmp_path, text, TYPESAFE_API_KEY="k"))
	assert (c.base_url, c.model, c.is_hosted, c.hosted_scope, c.api_key) == ("https://api.typesafe.ai", "jev-latest", True, "ci", "k")


def test_config_init_writes_the_template_once(tmp_path, capsys):
	env = _env(tmp_path)
	assert main(["config", "init"], env=env) == 0
	assert main(["config", "init"], env=env) == 2
	assert "already exists" in capsys.readouterr().err
	assert main(["config", "init", "--force"], env=env) == 0
	assert main(["config", "path"], env=env) == 0
