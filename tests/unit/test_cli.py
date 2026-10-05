import json
import subprocess
import sys

from conftest import AWS_KEY, FakeDecider

from smart_commit_guard.cli import main


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
	assert main(["install-hook", "--force"], env={}) == 0 and "scan --staged" in hook.read_text() and "SKIP_SECRET_GUARD" in hook.read_text()


def test_given_skip_smart_commit_guard_when_scanning_staged_then_it_allows_the_commit_and_says_it_was_skipped(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	(tmp_path / "app.py").write_text(f'KEY = "{AWS_KEY}"\n')
	git(tmp_path, "add", "app.py")
	monkeypatch.chdir(tmp_path)
	d = FakeDecider()
	assert main(["scan", "--staged"], env={"SKIP_SECRET_GUARD": "1"}, decider=d) == 0
	err = capsys.readouterr().err
	assert "SKIPPED" in err and "SKIP_SECRET_GUARD" in err and d.batches == []


def test_given_skip_smart_commit_guard_with_any_other_value_when_scanning_staged_then_it_still_blocks(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	(tmp_path / "app.py").write_text(f'KEY = "{AWS_KEY}"\n')
	git(tmp_path, "add", "app.py")
	monkeypatch.chdir(tmp_path)
	for value in ("0", "", "true", "yes"):
		assert main(["scan", "--staged"], env={"SKIP_SECRET_GUARD": value}, decider=FakeDecider()) == 1


def test_given_skip_smart_commit_guard_when_scanning_files_or_a_diff_range_then_it_is_ignored_so_ci_still_gates(tmp_path):
	f = write(tmp_path, "app.py", f'KEY = "{AWS_KEY}"\n')
	assert main(["scan", "--files", f], env={"SKIP_SECRET_GUARD": "1"}, decider=FakeDecider()) == 1


def staged_secret_repo(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	(tmp_path / "app.py").write_text(f'KEY = "{AWS_KEY}"\n')
	git(tmp_path, "add", "app.py")
	monkeypatch.chdir(tmp_path)


def test_given_a_skipped_commit_when_scanning_staged_then_an_entry_is_appended_to_the_skips_log_without_the_secret(tmp_path, monkeypatch):
	staged_secret_repo(tmp_path, monkeypatch)
	for _ in range(2):
		assert main(["scan", "--staged"], env={"SKIP_SECRET_GUARD": "1"}, decider=FakeDecider()) == 0
	log = (tmp_path / ".git" / "secret-guard-skips.log").read_text()
	assert log.count("SKIP ") == 2 and "app.py" in log and "BLOCK" in log and "branch=" in log
	assert AWS_KEY not in log


def test_given_not_a_git_repo_when_skipping_then_the_commit_is_still_allowed(tmp_path, monkeypatch):
	monkeypatch.chdir(tmp_path)
	assert main(["scan", "--staged"], env={"SKIP_SECRET_GUARD": "1"}, decider=FakeDecider()) == 0


def test_given_install_hook_shared_then_it_writes_a_tracked_hooks_folder_and_points_git_at_it(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	assert main(["install-hook", "--shared"], env={}) == 0
	hook = tmp_path / ".githooks" / "pre-commit"
	assert (sys.platform == "win32" or hook.stat().st_mode & 0o100) and "scan --staged" in hook.read_text() and str(tmp_path) not in hook.read_text()
	assert "/.githooks/* text eol=lf" in (tmp_path / ".gitattributes").read_text()
	out = subprocess.run(["git", "config", "core.hooksPath"], cwd=tmp_path, capture_output=True, text=True, check=False).stdout
	assert out.strip() == ".githooks"


def test_given_a_shared_hook_when_installing_again_then_it_is_refused_without_force_and_gitattributes_is_not_duplicated(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	main(["install-hook", "--shared"], env={})
	assert main(["install-hook", "--shared"], env={}) == 2
	assert main(["install-hook", "--shared", "--force"], env={}) == 0
	assert (tmp_path / ".gitattributes").read_text().count(".githooks") == 1


def test_given_another_hooks_path_when_installing_shared_then_it_is_refused_without_force(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	git(tmp_path, "config", "core.hooksPath", "other")
	monkeypatch.chdir(tmp_path)
	assert main(["install-hook", "--shared"], env={}) == 2


def test_given_a_healthy_setup_when_running_doctor_then_exit_0(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	main(["install-hook", "--shared"], env={})
	assert main(["doctor"], env={}, decider=FakeDecider()) == 0
	out = capsys.readouterr().out
	assert "FAIL" not in out and "ok" in out


def test_given_no_hook_when_running_doctor_then_it_fails_and_says_how_to_fix_it(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	assert main(["doctor"], env={}, decider=FakeDecider()) == 1
	assert "install-hook" in capsys.readouterr().out


def test_given_an_unreachable_model_when_running_doctor_then_it_only_warns(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	main(["install-hook", "--shared"], env={})
	d = FakeDecider()
	d.down = True
	assert main(["doctor"], env={}, decider=d) == 0
	assert "WARN" in capsys.readouterr().out


def test_given_skip_smart_commit_guard_exported_when_running_doctor_then_it_warns(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	main(["install-hook", "--shared"], env={})
	main(["doctor"], env={"SKIP_SECRET_GUARD": "1"}, decider=FakeDecider())
	assert "SKIP_SECRET_GUARD" in capsys.readouterr().out


def test_given_a_staged_binary_key_store_when_scanning_staged_then_it_blocks_by_name(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	(tmp_path / "prod.p12").write_bytes(bytes(range(256)))
	git(tmp_path, "add", "prod.p12")
	monkeypatch.chdir(tmp_path)
	assert main(["scan", "--staged"], env={}, decider=FakeDecider()) == 1
	assert "prod.p12" in capsys.readouterr().out


def test_given_a_skipped_glob_when_scanning_a_sensitive_file_then_it_passes(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	(tmp_path / "prod.p12").write_bytes(bytes(range(256)))
	(tmp_path / ".secret-guard.toml").write_text('skip = ["prod.p12"]\n')
	git(tmp_path, "add", "prod.p12")
	monkeypatch.chdir(tmp_path)
	assert main(["scan", "--staged"], env={}, decider=FakeDecider()) == 0


def test_given_files_mode_with_a_sensitive_name_when_scanning_then_it_blocks(tmp_path):
	d = tmp_path / ".ssh"
	d.mkdir()
	(d / "id_rsa").write_text("not really a key\n")
	assert main(["scan", "--files", str(d / "id_rsa")], env={}, decider=FakeDecider()) == 1
