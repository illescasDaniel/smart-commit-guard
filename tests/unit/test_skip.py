import pytest

from secret_guard.skip import (
	is_env_file,
	is_example_path,
	is_skipped,
	sensitive_file_reason,
)


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


@pytest.mark.parametrize("path", [
	"id_rsa", "home/.ssh/id_ed25519", "certs/keystore.p12", "a/b.pfx", "app.jks", "release.keystore", "key.ppk", "vault.kdbx",
	".netrc", ".pgpass", ".pypirc", ".htpasswd", ".git-credentials", "terraform.tfstate", "infra/prod.tfstate.backup",
	"infra/prod.tfvars", ".aws/credentials", "home/.docker/config.json", ".kube/config", "kubeconfig", "credentials.json",
	"client_secret_123.apps.googleusercontent.com.json", "service-account-prod.json", ".env", "dist.mobileprovision"])
def test_given_a_sensitive_file_name_when_checking_then_it_has_a_reason(path):
	assert sensitive_file_reason(path)


@pytest.mark.parametrize("path", [
	"id_rsa.pub", "src/app.py", "terraform.tfvars.example", "prod.tfvars.sample", "config.json", "docs/credentials.md",
	"cert.pem", "server.crt", ".env.example", "package.json", "kube/config.py", "aws/credentials.py"])
def test_given_a_public_template_or_ordinary_name_when_checking_then_it_has_no_reason(path):
	assert sensitive_file_reason(path) is None


def test_given_windows_style_paths_when_checking_then_names_and_directories_are_still_recognised():
	assert sensitive_file_reason("C:\\Users\\me\\.ssh\\id_rsa") == "SSH private key"
	assert sensitive_file_reason("C:\\Users\\me\\.aws\\credentials") == "AWS credentials"
	assert is_skipped("C:\\repo\\package-lock.json") and is_example_path("repo\\tests\\a.py")
