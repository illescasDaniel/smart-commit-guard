"""Property: whatever else is on the line, an injected secret never appears in a finding's preview, `--json` or the skips log."""
import json

from conftest import AWS_KEY, FakeDecider
from hypothesis import given, settings
from hypothesis import strategies as st

from smart_commit_guard.cli import main
from smart_commit_guard.policy import scan
from smart_commit_guard.types import AddedLine

# Values with a known prefix keep the prefix in the preview by design, so the checked part is what follows it.
ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
bodies = st.text(alphabet=ALPHABET, min_size=24, max_size=40).filter(lambda s: any(c.isdigit() for c in s) and any(c.isalpha() for c in s))
shapes = st.sampled_from([
	("ghp_{}", "ghp_"), ("AKIA{}", "AKIA"), ('password = "{}"', ""), ("token: {}", ""), ('secret_key = "{}"', ""), ("sk_live_{}", "sk_live_"),
	('x = "{}"', "")])
fillers = st.sampled_from(["", "# ", "call(", "{'a': 1, ", "echo "])


def sample(shape, body):
	template, prefix = shape
	if prefix == "AKIA":
		body = body.upper()[:16].ljust(16, "A")
	return template.format(body), body


@settings(max_examples=150, deadline=None)
@given(st.lists(st.tuples(shapes, bodies), min_size=1, max_size=3), fillers)
def test_given_one_to_three_secrets_on_a_line_when_scanning_then_none_appears_in_the_preview(parts, filler):
	made = [sample(shape, body) for shape, body in parts]
	line = filler + ", ".join(text for text, _ in made)
	result = scan([AddedLine("src/app.py", 1, line)], FakeDecider(lambda p, t: 0.9))
	shown = "\n".join(f.preview + f.reason for f in result.findings)
	for _, body in made:
		assert body not in shown


def test_given_secrets_when_reporting_json_or_logging_a_skip_then_none_appears(tmp_path, monkeypatch, capsys):
	import subprocess

	subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
	secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzxk3Ntq9Lm"
	(tmp_path / "app.py").write_text(f'creds = ("{AWS_KEY}", "{secret}")\n')
	subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
	monkeypatch.chdir(tmp_path)
	main(["scan", "--staged", "--json"], env={}, decider=FakeDecider(lambda p, t: 0.9))
	out = capsys.readouterr().out
	main(["scan", "--staged"], env={"SKIP_SECRET_GUARD": "1"}, decider=FakeDecider())
	log = (tmp_path / ".git" / "secret-guard-skips.log").read_text()
	for text in (out, log, capsys.readouterr().out):
		assert secret not in text and AWS_KEY not in text
	assert json.loads(out)["exit_code"] == 1
