import pytest

from secret_guard.skip import is_env_file, is_example_path, is_skipped


@pytest.mark.parametrize("path", ["package-lock.json", "web/yarn.lock", "uv.lock", "a/poetry.lock", ".env.example",
									 "logo.png", "dist/app.min.js", "x.pdf"])
def test_given_a_lockfile_binary_or_generated_path_when_checking_then_it_is_skipped(path):
	assert is_skipped(path)


@pytest.mark.parametrize("path", ["src/app.py", ".env", "config/settings.toml"])
def test_given_a_normal_source_path_when_checking_then_it_is_not_skipped(path):
	assert not is_skipped(path)


@pytest.mark.parametrize("path", ["tests/unit/test_a.py", "README.md", "docs/setup.md", "examples/demo.py",
									 "tests/fixtures/data.json", "conf.example.toml"])
def test_given_a_test_doc_or_example_path_when_checking_then_it_is_an_example_path(path):
	assert is_example_path(path)


@pytest.mark.parametrize("path", ["src/app.py", "config/prod.toml", ".env"])
def test_given_production_paths_when_checking_then_they_are_not_example_paths(path):
	assert not is_example_path(path)


@pytest.mark.parametrize("path", [".env", "app/.env", ".env.local", ".env.production", "prod.env"])
def test_given_an_environment_file_when_checking_then_it_is_an_env_file(path):
	assert is_env_file(path)


@pytest.mark.parametrize("path", [".env.example", ".env.sample", ".env.template", "env.py", "src/environment.py", "x.envelope"])
def test_given_a_template_or_unrelated_path_when_checking_then_it_is_not_an_env_file(path):
	assert not is_env_file(path)
