import json
import subprocess

from conftest import AWS_KEY, FakeDecider

from secret_guard.cli import main


def write(tmp_path, name, text):
	p = tmp_path / name
	p.write_text(text)
	return str(p)


def test_given_a_file_with_an_aws_key_when_scanning_files_then_exit_1_and_the_secret_is_not_printed(tmp_path, capsys):
	f = write(tmp_path, "app.py", f'KEY = "{AWS_KEY}"\n')
	assert main(["scan", "--files", f], env={}, decider=FakeDecider()) == 1
	assert AWS_KEY not in capsys.readouterr().out


def test_given_a_clean_file_when_scanning_files_then_exit_0(tmp_path):
	assert main(["scan", "--files", write(tmp_path, "a.py", "x = 1\n")], env={}, decider=FakeDecider()) == 0


def test_given_json_when_scanning_then_findings_are_machine_readable(tmp_path, capsys):
	f = write(tmp_path, "app.py", f'KEY = "{AWS_KEY}"\n')
	main(["scan", "--files", f, "--json"], env={}, decider=FakeDecider())
	data = json.loads(capsys.readouterr().out)
	assert data["exit_code"] == 1 and data["findings"][0]["level"] == "block"


def test_given_no_model_flag_when_scanning_then_the_decider_is_not_used(tmp_path):
	d = FakeDecider(lambda p, t: 1.0)
	f = write(tmp_path, "db.py", 'DB_PASS = "Winter2026!Admin"\n')
	assert main(["scan", "--files", f, "--no-model"], env={}, decider=d) == 0 and d.batches == []


def test_given_a_hosted_url_without_opt_in_when_scanning_then_exit_2_and_nothing_is_sent(tmp_path):
	d = FakeDecider()
	f = write(tmp_path, "db.py", 'DB_PASS = "Winter2026!Admin"\n')
	assert main(["scan", "--files", f], env={"SECRET_GUARD_BASE_URL": "https://api.example.com"}, decider=d) == 2
	assert d.batches == []


def test_given_a_directory_among_the_files_when_scanning_then_it_is_skipped(tmp_path):
	f = write(tmp_path, "a.py", "x = 1\n")
	assert main(["scan", "--files", str(tmp_path), f], env={}, decider=FakeDecider()) == 0


def test_given_a_missing_file_when_scanning_then_exit_2(tmp_path):
	assert main(["scan", "--files", str(tmp_path / "nope.py")], env={}, decider=FakeDecider()) == 2


def git(cwd, *args):
	subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_given_a_staged_secret_when_scanning_staged_then_exit_1(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	(tmp_path / "app.py").write_text(f'KEY = "{AWS_KEY}"\n')
	git(tmp_path, "add", "app.py")
	monkeypatch.chdir(tmp_path)
	assert main(["scan", "--staged"], env={}, decider=FakeDecider()) == 1


def test_given_not_a_git_repo_when_scanning_staged_then_exit_2(tmp_path, monkeypatch):
	monkeypatch.chdir(tmp_path)
	assert main(["scan", "--staged"], env={}, decider=FakeDecider()) == 2


def test_given_install_hook_when_a_hook_exists_then_it_is_not_overwritten_without_force(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	hook = tmp_path / ".git" / "hooks" / "pre-commit"
	hook.write_text("#!/bin/sh\necho mine\n")
	monkeypatch.chdir(tmp_path)
	assert main(["install-hook"], env={}) == 2 and "mine" in hook.read_text()
	assert main(["install-hook", "--force"], env={}) == 0 and "secret-guard scan --staged" in hook.read_text()
