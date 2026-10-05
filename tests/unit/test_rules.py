import pytest
from conftest import AWS_KEY

from smart_commit_guard.rules import scan_line


def first(line):
	"""The first hit on the line, or None (most tests care about a single hit)."""
	hits = scan_line(line)
	return hits[0] if hits else None

PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"
URL = "postgres://admin:" + "hunter2hunter2@db.internal/app"


@pytest.mark.parametrize("line, rule", [
	(PRIVATE_KEY, "private key"), (f'AWS_KEY = "{AWS_KEY}"', "AWS access key"),
	(f"token: {GITHUB}", "GitHub token"), (f"DSN = '{URL}'", "connection string with password")])
def test_given_a_known_secret_shape_when_scanning_a_line_then_it_is_a_high_confidence_rule_hit(line, rule):
	hit = first(line)
	assert hit and hit.kind == "rule" and hit.rule == rule and hit.high_confidence


def test_given_a_secret_looking_name_with_a_literal_when_scanning_then_it_is_a_candidate_for_the_model():
	hit = first('DB_PASS = "Winter2026!Admin"')
	assert hit and hit.kind == "candidate" and not hit.high_confidence and hit.value == "Winter2026!Admin"


def test_given_a_long_high_entropy_literal_when_scanning_then_it_is_a_candidate():
	hit = first('blob = "x9Qm2LpV7sTr4KdW8zYb1NcE6hJf3AgU"')
	assert hit and hit.kind == "candidate"


@pytest.mark.parametrize("line", ["x = 1", "name = 'hello world'", "password = os.environ['PASSWORD']",
								  "api_key = settings.api_key", "# set the token in the environment",
								  'p = "/storage/emulated/0/Download/Camera2"', 'monkeypatch.setattr(m, "_build_h264_export_pipe2", f)'])
def test_given_ordinary_code_or_env_references_when_scanning_then_nothing_is_found(line):
	assert first(line) is None


def test_given_a_url_with_a_local_host_when_scanning_then_it_is_a_candidate_not_a_block():
	hit = first("url = 'postgresql://ci:ci-s3cure-Zq8@localhost:5432/t'")
	assert hit and hit.kind == "candidate" and not hit.high_confidence


def test_given_a_url_with_the_literal_word_password_when_scanning_then_it_is_a_placeholder():
	assert first("DSN: postgresql://user:password@host:5432/db") is None


@pytest.mark.parametrize("line, value", [
	("      POSTGRES_PASSWORD: Zk4!mQ9xLp27vRt", "Zk4!mQ9xLp27vRt"),
	("the admin password is Hq7!zLm2Pr0dKx9", "Hq7!zLm2Pr0dKx9"),
	('curl -H "Authorization: Bearer 9f8e7d6c5b4a39281706f5e4d3c2b1a0" https://x', "9f8e7d6c5b4a39281706f5e4d3c2b1a0"),
	('cs = "Server=db;User Id=sa;Password=Hq7!zLm2Pr0d;"', "Hq7!zLm2Pr0d"),
	("mysql -u root -pHq7zLm2Pr0d -e 'select 1'", "Hq7zLm2Pr0d")])
def test_given_a_credential_in_yaml_prose_bearer_header_or_cli_when_scanning_then_it_is_a_candidate(line, value):
	hit = first(line)
	assert hit and hit.kind == "candidate" and hit.value == value


@pytest.mark.parametrize("line", ["https://hooks" + ".slack.com/services/T0A1B2C3D/B4E5F6G7H/Zq8Lm2Pr0dKx9Wv3TnHq7zLm",
								  "https://discord" + ".com/api/webhooks/1122334455667788/Zq8Lm2Pr0dKx9Wv3TnHq7zLm2PrQ1abC"])
def test_given_a_chat_webhook_url_when_scanning_then_it_is_a_high_confidence_rule_hit(line):
	hit = first(line)
	assert hit and hit.kind == "rule" and hit.rule == "webhook URL" and hit.high_confidence


@pytest.mark.parametrize("line", ["password: str", "token: Optional[str] = None", "  password: ${DB_PASSWORD}",
								  "password: your-password", "Authorization: Bearer YOUR_TOKEN", "the password is required"])
def test_given_type_hints_references_and_prose_when_scanning_then_the_new_patterns_stay_quiet(line):
	assert first(line) is None


@pytest.mark.parametrize("line", ['API_KEY = "your-api-key-here"', 'TOKEN = "test-token-123"', 'DEMO_PASSWORD = "changeme"',
								  'api_key = "REPLACE_ME"', "token: xxxx-xxxx-xxxx-xxxx", 'password = "<redacted>"',
								  'MASKED_PASSWORD = "********"', 'client.post(json={"password": "wrong-password"})'])
def test_given_an_obvious_placeholder_value_when_scanning_then_the_model_is_not_needed(line):
	assert first(line) is None


def test_given_a_real_password_that_merely_contains_a_placeholder_word_when_scanning_then_it_is_still_a_candidate():
	hit = first('DB_PASS = "Contest2026!Admin"')
	assert hit and hit.kind == "candidate"


# --- 0.7 / 0.8: every hit on a line, not only the first


def values(line):
	return [h.value for h in scan_line(line)]


def test_given_two_secrets_on_one_line_when_scanning_then_both_are_found():
	line = f'creds = ("{AWS_KEY}", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzxk3Ntq9Lm")'
	assert AWS_KEY in values(line) and "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzxk3Ntq9Lm" in values(line)


def test_given_a_placeholder_before_a_real_secret_on_one_line_when_scanning_then_the_real_one_is_still_found():
	assert values('{"password": "changeme", "token": "q8Zr2LmW9vXp4TnK7"}') == ["q8Zr2LmW9vXp4TnK7"]
	assert values('docker run -e A_PASSWORD="changeme" -e B_TOKEN="q8Zr2LmW9vXp4TnK7" img') == ["q8Zr2LmW9vXp4TnK7"]


def test_given_a_placeholder_assignment_with_a_long_value_when_scanning_then_the_literal_check_does_not_resurrect_it():
	assert scan_line('api_key = "your-api-key-here-9f8e7d6c5b4a39281706f5e4"') == []


def test_given_overlapping_patterns_when_scanning_then_each_value_is_reported_once_with_its_span():
	line = f'token = "{GITHUB}"'
	(hit,) = scan_line(line)
	assert hit.kind == "rule" and line[hit.start:hit.end] == GITHUB


# --- 1.1 more known shapes: each rule has a positive and a negative example


def build(*parts):
	return "".join(parts)   # assembled so this file never holds a token-shaped literal


RULE_EXAMPLES = {
	"private key": (build("-----BEGIN ", "PGP PRIVATE KEY BLOCK-----"), "-----BEGIN PUBLIC KEY-----"),
	"AWS access key": (AWS_KEY, "AKIA-too-short"),
	"GitHub token": (build("ghp_", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"), "ghp_short"),
	"GitHub fine-grained token": (build("github_pat_", "11ABCDEFG0" * 7), "github_pat_short"),
	"Anthropic API key": (build("sk-ant-", "api03-a1B2c3D4e5F6g7H8i9J0k1L2m3N4"), "sk-ant-short"),
	"API token": (build("sk-", "proj-a1B2c3D4e5F6g7H8i9J0k1L2m3N4"), "sk-learn-contrib-projects"),
	"Stripe key": (build("rk_", "live_51Hq7zLm2Pr0dKx9Wv3Tn"), "rk_live_short"),
	"Stripe webhook secret": (build("whsec_", "a1B2c3D4e5F6g7H8i9J0k1L2"), "whsec_short"),
	"Slack token": (build("xapp-", "1-A0123456789-abcdefghij"), "xapp-short"),
	"Google API key": (build("AIza", "SyD4mQ8vL2pXz7Kc9RtNb3WfHjE6YaUs1Go"), "AIza-short"),
	"Google OAuth client secret": (build("GOCSPX-", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"), "GOCSPX-short"),
	"GitLab token": (build("glptt-", "a1B2c3D4e5F6g7H8i9J0"), "glptt-short"),
	"SendGrid API key": (build("SG.", "a1B2c3D4e5F6g7H8i9J0k1", ".", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V"), "SG.short.short"),
	"PyPI token": (build("pypi-", "AgEI", "a1B2c3D4e5F6g7H8i9J0" * 3), "pypi-AgEIshort"),
	"npm token": (build("npm_", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"[:36]), "npm_short"),
	"Shopify token": (build("shpat_", "0123456789abcdef0123456789abcdef"), "shpat_xyz"),
	"DigitalOcean token": (build("dop_v1_", "0123456789abcdef" * 4), "dop_v1_short"),
	"Doppler token": (build("dp.pt.", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0"), "dp.pt.short"),
	"Hugging Face token": (build("hf_", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5"), "hf_short"),
	"Telegram bot token": (build("123456789", ":AA", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q"), "123456789:AAshort"),
	"Azure storage key": (build("AccountKey=", "a1B2c3D4/e5F6g7H8+i9J0k1L2m3N4o5P6q7R8s9T0u1V2w3X4y5Z6a7B8c9D0e1F2g3H4i5J6k7L8==="), "AccountKey=short"),
	"webhook URL": (build("https://hooks", ".slack.com/services/T0A1B2C3D/B4E5F6G7H/Zq8Lm2Pr0dKx9Wv3TnHq7zLm"), "https://hooks.slack.com/docs"),
	"connection string with password": (URL, "postgres://admin@db.internal/app"),
}


def test_given_the_rule_table_when_checking_examples_then_every_rule_has_a_positive_and_a_negative_one():
	from smart_commit_guard.rules import RULES

	assert {r.name for r in RULES} == set(RULE_EXAMPLES)


@pytest.mark.parametrize("name", sorted(RULE_EXAMPLES))
def test_given_a_rule_when_scanning_its_positive_example_then_that_rule_names_the_hit(name):
	positive, _ = RULE_EXAMPLES[name]
	rule_hits = [h for h in scan_line(f"x = {positive}") if h.kind == "rule"]
	assert [h.rule for h in rule_hits] == [name] and rule_hits[0].high_confidence


@pytest.mark.parametrize("name", sorted(RULE_EXAMPLES))
def test_given_a_rule_when_scanning_its_negative_example_then_no_rule_hit(name):
	_, negative = RULE_EXAMPLES[name]
	assert [h for h in scan_line(f"x = {negative}") if h.kind == "rule"] == []


def test_given_a_rule_prefix_when_masking_then_every_rule_prefix_stays_visible():
	from smart_commit_guard.redact import mask
	from smart_commit_guard.rules import KNOWN_PREFIXES

	assert all(mask(p + "a1B2c3D4").startswith(p) for p in KNOWN_PREFIXES)
	assert mask(build("sk-ant-", "a1B2")) == "sk-ant-a9A9"   # the longest prefix wins over `sk-`


# --- 1.1 / 1.2 candidates and false positives from the probes


def test_given_a_jwt_when_scanning_then_it_is_a_candidate_for_the_model_not_a_block():
	jwt = build("eyJ", "hbGciOiJIUzI1NiJ9", ".", "eyJ", "zdWIiOiIxMjM0NTY3ODkwIn0", ".", "dBjftJeZ4CVPmB92K27uhbUJU1p1r")
	hit = first(f'token = "{jwt}"')
	assert hit and hit.kind == "candidate" and not hit.high_confidence


@pytest.mark.parametrize("line", ["//registry.npmjs.org/:_authToken=NpmAuthXq8Zr2LmW9vXp4TnK7",
								  'npmAuthToken: "q8Zr2LmW9vXp4TnK7yH"'])
def test_given_an_npm_registry_credential_when_scanning_then_it_is_a_candidate(line):
	hit = first(line)
	assert hit and hit.kind == "candidate"


@pytest.mark.parametrize("line", ["//registry.npmjs.org/:_authToken=${NPM_TOKEN}", "_authToken = os.getenv(KEY)",
								  'DB_PASSWORD = os.getenv("DB_PASSWORD", "")'])
def test_given_an_npm_style_name_with_a_reference_when_scanning_then_nothing_is_found(line):
	assert scan_line(line) == []


def test_given_an_aws_secret_key_with_slashes_and_no_secret_looking_name_when_scanning_then_it_is_a_candidate():
	hit = first('x = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzxk3Ntq9Lm"')
	assert hit and hit.kind == "candidate"


@pytest.mark.parametrize("line", ['p = "src/main/java/com/example/service"', 'p = "/var/lib/some/deeply/nested/dir1"',
								  'p = "./relative/path/to/some/place1"', 'p = "Library/Application/Support/Thing1"'])
def test_given_a_path_when_scanning_then_it_is_still_not_a_candidate(line):
	assert scan_line(line) == []


@pytest.mark.parametrize("line", ['name = "sk-learn-contrib-projects"', 'id = "3f2b8c1e-9a4d-4e7b-8c21-5d6f7a8b9c0d"',
								  'sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"',
								  'COMMIT = "9fceb02d0ae598e95dc970b74767f19372d61af8"', 'integrity = "a3f9c2e1b7d84056a1f9c3e87b2d5a10"'])
def test_given_a_package_name_uuid_or_digest_when_scanning_then_nothing_is_found(line):
	assert scan_line(line) == []


def test_given_a_hex_value_with_a_secret_looking_name_when_scanning_then_it_is_still_a_candidate():
	hit = first('JWT_SECRET = "d8f3a91c7e5b4026a1f9c3e87b2d5a10"')
	assert hit and hit.kind == "candidate"


def test_given_rules_only_when_scanning_then_candidates_are_not_extracted_but_rule_hits_are():
	assert scan_line('DB_PASS = "Winter2026!Admin"', rules_only=True) == []
	assert [h.rule for h in scan_line(f'k = "{AWS_KEY}"', rules_only=True)] == ["AWS access key"]


# --- base64-encoded secrets, sequential strings (ideas from gitleaks and detect-secrets)


def b64(text):
	import base64

	return base64.b64encode(text.encode()).decode()


def test_given_a_base64_encoded_token_when_scanning_then_the_rule_is_found_and_marked_encoded():
	line = "  token: " + b64(GITHUB)
	(hit,) = scan_line(line)
	assert hit.kind == "rule" and hit.rule == "GitHub token (base64-encoded)" and hit.high_confidence and hit.value in line


def test_given_a_kubernetes_secret_with_an_encoded_private_key_when_scanning_then_it_is_found():
	assert [h.rule for h in scan_line("  tls.key: " + b64(PRIVATE_KEY + "\nMIIEvQ"))] == ["private key (base64-encoded)"]


def test_given_a_doubly_encoded_token_when_scanning_then_it_is_still_found():
	assert [h.rule for h in scan_line("x: " + b64(b64(GITHUB)))] == ["GitHub token (base64-encoded)"]


@pytest.mark.parametrize("line", ["integrity: sha512-" + b64("\x00\x01binary\xfe")[:30], 'x = "' + b64("just some harmless words in a row") + '"',
								  'h = "' + "A" * 40 + '"'])
def test_given_base64_that_is_not_a_secret_when_scanning_then_nothing_is_found(line):
	assert [h for h in scan_line(line) if h.kind == "rule"] == []


@pytest.mark.parametrize("line", ['API_KEY = "abcdefghijklmnop"', 'TOKEN = "1234567890123456"', 'secret = "0123456789abcdef"',
								  'password = "aaaaaaaa"', 'token = "ZYXWVUTSRQ"'])
def test_given_a_sequential_or_repeated_value_when_scanning_then_it_is_a_placeholder(line):
	assert scan_line(line) == []
