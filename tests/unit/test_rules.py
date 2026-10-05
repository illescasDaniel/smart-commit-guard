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
								  "api_key = settings.api_key", "# set the token in the environment"])
def test_given_ordinary_code_or_env_references_when_scanning_then_nothing_is_found(line):
	assert scan_line(line) is None
