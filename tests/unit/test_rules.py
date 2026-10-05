import pytest
from conftest import AWS_KEY

from secret_guard.rules import scan_line

PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"
URL = "postgres://admin:" + "hunter2hunter2@db.internal/app"


@pytest.mark.parametrize("line, rule", [
	(PRIVATE_KEY, "private key"), (f'AWS_KEY = "{AWS_KEY}"', "AWS access key"),
	(f"token: {GITHUB}", "API token"), (f"DSN = '{URL}'", "connection string with password")])
def test_given_a_known_secret_shape_when_scanning_a_line_then_it_is_a_high_confidence_rule_hit(line, rule):
	hit = scan_line(line)
	assert hit and hit.kind == "rule" and hit.rule == rule and hit.high_confidence


def test_given_a_secret_looking_name_with_a_literal_when_scanning_then_it_is_a_candidate_for_the_model():
	hit = scan_line('DB_PASS = "Winter2026!Admin"')
	assert hit and hit.kind == "candidate" and not hit.high_confidence and hit.value == "Winter2026!Admin"


def test_given_a_long_high_entropy_literal_when_scanning_then_it_is_a_candidate():
	hit = scan_line('blob = "x9Qm2LpV7sTr4KdW8zYb1NcE6hJf3AgU"')
	assert hit and hit.kind == "candidate"


@pytest.mark.parametrize("line", ["x = 1", "name = 'hello world'", "password = os.environ['PASSWORD']",
								  "api_key = settings.api_key", "# set the token in the environment",
								  'p = "/storage/emulated/0/Download/Camera2"', 'monkeypatch.setattr(m, "_build_h264_export_pipe2", f)'])
def test_given_ordinary_code_or_env_references_when_scanning_then_nothing_is_found(line):
	assert scan_line(line) is None


def test_given_a_url_with_a_local_host_when_scanning_then_it_is_a_candidate_not_a_block():
	hit = scan_line("url = 'postgresql://ci:ci-s3cure-Zq8@localhost:5432/t'")
	assert hit and hit.kind == "candidate" and not hit.high_confidence


def test_given_a_url_with_the_literal_word_password_when_scanning_then_it_is_a_placeholder():
	assert scan_line("DSN: postgresql://user:password@host:5432/db") is None


@pytest.mark.parametrize("line, value", [
	("      POSTGRES_PASSWORD: Zk4!mQ9xLp27vRt", "Zk4!mQ9xLp27vRt"),
	("the admin password is Hq7!zLm2Pr0dKx9", "Hq7!zLm2Pr0dKx9"),
	('curl -H "Authorization: Bearer 9f8e7d6c5b4a39281706f5e4d3c2b1a0" https://x', "9f8e7d6c5b4a39281706f5e4d3c2b1a0"),
	('cs = "Server=db;User Id=sa;Password=Hq7!zLm2Pr0d;"', "Hq7!zLm2Pr0d"),
	("mysql -u root -pHq7zLm2Pr0d -e 'select 1'", "Hq7zLm2Pr0d")])
def test_given_a_credential_in_yaml_prose_bearer_header_or_cli_when_scanning_then_it_is_a_candidate(line, value):
	hit = scan_line(line)
	assert hit and hit.kind == "candidate" and hit.value == value


@pytest.mark.parametrize("line", ["https://hooks" + ".slack.com/services/T0A1B2C3D/B4E5F6G7H/Zq8Lm2Pr0dKx9Wv3TnHq7zLm",
								  "https://discord" + ".com/api/webhooks/1122334455667788/Zq8Lm2Pr0dKx9Wv3TnHq7zLm2PrQ1abC"])
def test_given_a_chat_webhook_url_when_scanning_then_it_is_a_high_confidence_rule_hit(line):
	hit = scan_line(line)
	assert hit and hit.kind == "rule" and hit.rule == "webhook URL" and hit.high_confidence


@pytest.mark.parametrize("line", ["password: str", "token: Optional[str] = None", "  password: ${DB_PASSWORD}",
								  "password: your-password", "Authorization: Bearer YOUR_TOKEN", "the password is required"])
def test_given_type_hints_references_and_prose_when_scanning_then_the_new_patterns_stay_quiet(line):
	assert scan_line(line) is None


@pytest.mark.parametrize("line", ['API_KEY = "your-api-key-here"', 'TOKEN = "test-token-123"', 'DEMO_PASSWORD = "changeme"',
								  'api_key = "REPLACE_ME"', "token: xxxx-xxxx-xxxx-xxxx", 'password = "<redacted>"',
								  'MASKED_PASSWORD = "********"', 'client.post(json={"password": "wrong-password"})'])
def test_given_an_obvious_placeholder_value_when_scanning_then_the_model_is_not_needed(line):
	assert scan_line(line) is None


def test_given_a_real_password_that_merely_contains_a_placeholder_word_when_scanning_then_it_is_still_a_candidate():
	hit = scan_line('DB_PASS = "Contest2026!Admin"')
	assert hit and hit.kind == "candidate"
