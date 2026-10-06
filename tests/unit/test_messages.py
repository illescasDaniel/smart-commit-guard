"""Commit messages: the commit-msg hook, `--message`, `--text -` and `--diff --messages`."""
import json
import os
import subprocess
import sys

import pytest
from conftest import AWS_KEY, FakeDecider

from smart_commit_guard.cli import main
from smart_commit_guard.messages import message_lines

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="runs POSIX shell hooks")
CANDIDATE = "the admin password is Hq7!zLm2Pr0dKx9"


def git(cwd, *args, env=None):
	return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False, env=env)


def msg(tmp_path, text, name="COMMIT_EDITMSG"):
	p = tmp_path / name
	p.write_text(text)
	return str(p)


# --- parsing


def test_given_a_message_when_splitting_then_every_line_is_numbered_and_comments_are_kept():
	lines = message_lines("subject\n\nbody\n# token note\n")
	assert [(l.number, l.text) for l in lines[:4]] == [(1, "subject"), (2, ""), (3, "body"), (4, "# token note")]
	assert {l.path for l in lines} == {"COMMIT_EDITMSG"}


def test_given_a_verbose_commit_when_splitting_then_the_diff_below_the_scissors_is_not_message_text():
	text = "subject\n# ------------------------ >8 ------------------------\n# Do not modify or remove the line above.\n+KEY=1\n"
	assert [l.text for l in message_lines(text)] == ["subject"]
	assert [l.text for l in message_lines("a\n; ------------------------ >8 ------------------------\nb\n")] == ["a"]


def test_given_crlf_when_splitting_then_the_carriage_returns_are_dropped():
	assert [l.text for l in message_lines("a\r\nb\r\n")][:2] == ["a", "b"]


# --- scan --message


def test_given_a_secret_in_the_message_when_scanning_it_then_it_blocks_with_a_masked_preview_and_a_recovery_hint(tmp_path, capsys):
	f = msg(tmp_path, f"Fix deploy\n\nUsed key {AWS_KEY} to test\n")
	assert main(["scan", "--message", f], env={}, decider=FakeDecider()) == 1
	out = capsys.readouterr()
	assert "COMMIT_EDITMSG:3" in out.out and AWS_KEY not in out.out + out.err
	assert f"git commit -e -F {f}" in out.err


def test_given_a_clean_message_when_scanning_it_then_exit_0(tmp_path):
	assert main(["scan", "--message", msg(tmp_path, "Add retries\n\nCloses #12\n")], env={}, decider=FakeDecider()) == 0


def test_given_a_prose_candidate_in_the_message_when_scanning_it_then_it_only_warns_and_the_model_is_never_called(tmp_path, capsys):
	d = FakeDecider(lambda p, t: 1.0)
	assert main(["scan", "--message", msg(tmp_path, f"Notes\n\n{CANDIDATE}\n")], env={}, decider=d) == 0
	assert "WARN" in capsys.readouterr().out and d.batches == []


def test_given_a_secret_below_the_scissors_line_when_scanning_it_then_it_is_ignored(tmp_path):
	text = f"subject\n# ------------------------ >8 ------------------------\n+KEY = \"{AWS_KEY}\"\n"
	assert main(["scan", "--message", msg(tmp_path, text)], env={}, decider=FakeDecider()) == 0


def test_given_a_broken_model_configuration_when_scanning_a_message_then_the_commit_is_not_refused_for_it(tmp_path):
	env = {"SECRET_GUARD_BASE_URL": "https://api.example.com", "SECRET_GUARD_TIMEOUT": "0"}
	assert main(["scan", "--message", msg(tmp_path, "fine\n")], env=env, decider=FakeDecider()) == 0


def test_given_skip_secret_guard_when_scanning_a_message_then_it_passes_with_a_notice(tmp_path, capsys):
	f = msg(tmp_path, f"key {AWS_KEY}\n")
	assert main(["scan", "--message", f], env={"SKIP_SECRET_GUARD": "1"}, decider=FakeDecider()) == 0
	assert "SKIPPED" in capsys.readouterr().err


def test_given_a_missing_message_file_when_scanning_it_then_exit_2(tmp_path):
	assert main(["scan", "--message", str(tmp_path / "nope")], env={}, decider=FakeDecider()) == 2


def test_given_json_when_scanning_a_message_then_the_finding_has_the_line_and_no_secret(tmp_path, capsys):
	main(["scan", "--message", msg(tmp_path, f"a\nkey {AWS_KEY}\n"), "--json"], env={}, decider=FakeDecider())
	out = capsys.readouterr().out
	data = json.loads(out)
	assert data["exit_code"] == 1 and data["findings"][0]["line"] == 2 and AWS_KEY not in out


def test_given_the_inline_marker_when_the_repo_allows_it_then_a_message_line_can_opt_out(tmp_path, monkeypatch):
	subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
	(tmp_path / ".secret-guard.toml").write_text("allow_inline = true\n")
	monkeypatch.chdir(tmp_path)
	f = msg(tmp_path, f"example key {AWS_KEY} # smart-commit-guard: allow\n")
	assert main(["scan", "--message", f], env={}, decider=FakeDecider()) == 0


def test_given_text_on_stdin_when_scanning_it_then_it_is_scanned_like_a_message(monkeypatch, capsys):
	import io

	monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(f"PR body\nkey {AWS_KEY}\n".encode())})())
	assert main(["scan", "--text", "-"], env={}, decider=FakeDecider()) == 1
	assert "stdin:2" in capsys.readouterr().out


# --- scan --diff --messages (the CI backstop)


@pytest.fixture
def repo(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	git(tmp_path, "config", "user.name", "t")
	git(tmp_path, "config", "user.email", "t@example.com")
	monkeypatch.chdir(tmp_path)
	return tmp_path


def commit(repo, message, name="f.txt"):
	(repo / name).write_text(f"content of {name}\n")   # the file is clean: only the message may hold a secret
	git(repo, "add", name)
	r = git(repo, "commit", "-q", "--no-verify", "-m", message)
	assert r.returncode == 0, r.stderr


def test_given_a_secret_in_a_commit_message_when_scanning_a_range_with_messages_then_it_blocks_naming_the_commit(repo, capsys):
	commit(repo, "base")
	commit(repo, f"oops key {AWS_KEY}", "g.txt")
	assert main(["scan", "--diff", "HEAD~1..HEAD", "--no-model"], env={}) == 0   # the diff itself is clean
	capsys.readouterr()
	assert main(["scan", "--diff", "HEAD~1..HEAD", "--messages", "--no-model"], env={}) == 1
	out = capsys.readouterr().out
	assert "commit " in out and AWS_KEY not in out


def test_given_only_older_commits_have_the_secret_when_scanning_a_later_range_then_it_passes(repo):
	commit(repo, f"oops key {AWS_KEY}")
	commit(repo, "clean", "g.txt")
	assert main(["scan", "--diff", "HEAD~1..HEAD", "--messages", "--no-model"], env={}) == 0


def test_given_a_new_branch_push_when_scanning_with_messages_then_every_commit_message_is_scanned(repo):
	commit(repo, f"oops key {AWS_KEY}")
	commit(repo, "clean", "g.txt")
	assert main(["scan", "--diff", f"{'0' * 40}..HEAD", "--messages", "--no-model"], env={}) == 1


def test_given_messages_without_a_diff_when_scanning_then_exit_2(repo, capsys):
	assert main(["scan", "--staged", "--messages"], env={}) == 2
	assert "--diff" in capsys.readouterr().err


# --- installation


def hooks_dir(repo):
	return repo / ".git" / "hooks"


def test_given_install_hook_when_run_then_both_the_pre_commit_and_the_commit_msg_hooks_are_written(repo):
	assert main(["install-hook"], env={}) == 0
	assert "scan --staged" in (hooks_dir(repo) / "pre-commit").read_text()
	text = (hooks_dir(repo) / "commit-msg").read_text()
	assert 'scan --message "$1"' in text and "@ARGS@" not in text and "@CHAIN@" not in text


def test_given_install_hook_shared_when_run_then_both_hooks_are_path_free_and_committable(repo):
	assert main(["install-hook", "--shared"], env={}) == 0
	for name, arg in (("pre-commit", "scan --staged"), ("commit-msg", 'scan --message "$1"')):
		text = (repo / ".githooks" / name).read_text()
		assert arg in text and str(repo) not in text


def test_given_an_existing_commit_msg_hook_when_installing_without_force_then_nothing_is_written_at_all(repo):
	(hooks_dir(repo) / "commit-msg").write_text("#!/bin/sh\necho mine\n")
	assert main(["install-hook"], env={}) == 2
	assert not (hooks_dir(repo) / "pre-commit").exists()   # no half-installed state


def test_given_existing_hooks_when_installing_with_chain_then_both_are_kept_and_run_first(repo):
	for name in ("pre-commit", "commit-msg"):
		(hooks_dir(repo) / name).write_text(f"#!/bin/sh\necho {name}-mine\n")
	assert main(["install-hook", "--chain"], env={}) == 0
	for name in ("pre-commit", "commit-msg"):
		assert f"{name}-mine" in (hooks_dir(repo) / f"{name}.local").read_text()
		text = (hooks_dir(repo) / name).read_text()
		assert f"{name}.local" in text and text.index(f"{name}.local") < text.index("scan ")


def test_given_a_missing_commit_msg_hook_when_running_doctor_then_it_warns_and_does_not_fail(repo, capsys, monkeypatch):
	from smart_commit_guard import cli

	main(["install-hook", "--shared"], env={})
	(repo / ".githooks" / "commit-msg").unlink()
	monkeypatch.setattr(cli.shutil, "which", lambda n, *a, **k: "/fake/" + n)
	monkeypatch.setattr(cli, "_tool_version", lambda exe: "9.9.9")
	assert main(["doctor"], env={}, decider=FakeDecider()) == 0
	assert "commit-msg hook" in capsys.readouterr().out


# --- end to end with real git


@posix_only
def test_given_the_installed_hooks_when_committing_with_a_secret_in_the_message_then_git_refuses_and_keeps_the_message(repo, tmp_path_factory):
	bin_dir = tmp_path_factory.mktemp("bin")
	tool = bin_dir / "smart-commit-guard"
	tool.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m smart_commit_guard "$@"\n')
	tool.chmod(0o755)
	src = os.path.join(os.path.dirname(__file__), "..", "..", "src")
	env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "PYTHONPATH": os.path.abspath(src),
		   "SECRET_GUARD_BASE_URL": "http://127.0.0.1:9", "SECRET_GUARD_TIMEOUT": "1"}
	assert main(["install-hook", "--shared"], env={}) == 0
	(repo / "ok.txt").write_text("fine\n")
	git(repo, "add", "ok.txt")
	bad = git(repo, "commit", "-m", f"debugging with {AWS_KEY}", env=env)
	assert bad.returncode == 1 and "commit message blocked" in bad.stderr and AWS_KEY not in bad.stdout + bad.stderr
	assert git(repo, "rev-parse", "--verify", "HEAD").returncode != 0   # nothing was committed
	good = git(repo, "commit", "-m", "debugging the deploy", env=env)
	assert good.returncode == 0, good.stderr
