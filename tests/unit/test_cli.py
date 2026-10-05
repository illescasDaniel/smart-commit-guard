import json
import subprocess
import sys

import pytest
from conftest import AWS_KEY, FakeDecider

from smart_commit_guard.cli import main


@pytest.fixture(autouse=True)
def tool_on_path(request, monkeypatch):
	"""Doctor checks that the hook can find the tool; in the test environment it may not be on PATH."""
	if "doctor" in request.node.name and "cannot_find" not in request.node.name:
		from smart_commit_guard import cli

		real = cli.shutil.which
		monkeypatch.setattr(cli.shutil, "which", lambda name, *a, **k: real(name, *a, **k) or ("/fake/smart-commit-guard" if name == "smart-commit-guard" else None))
		monkeypatch.setattr(cli, "_tool_version", lambda exe: "9.9.9")


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


# --- 0.6 / 0.6.1: hosted backends, and a hosted model used in CI only

HOSTED = {"SECRET_GUARD_BASE_URL": "https://llm.example.com", "SECRET_GUARD_ALLOW_HOSTED": "1"}
CANDIDATE = 'DB_PASS = "Winter2026!Admin"\n'


def staged_repo(tmp_path, monkeypatch, text=CANDIDATE, name="db.py"):
	git(tmp_path, "init", "-q")
	git(tmp_path, "config", "user.name", "t")
	git(tmp_path, "config", "user.email", "t@example.com")
	(tmp_path / name).write_text(text)
	git(tmp_path, "add", name)
	monkeypatch.chdir(tmp_path)


def test_given_a_hosted_backend_when_scanning_then_the_unmasked_candidate_line_is_sent(tmp_path):
	d = FakeDecider(lambda p, t: 0.1)
	assert main(["scan", "--files", write(tmp_path, "db.py", CANDIDATE)], env=HOSTED, decider=d) == 0
	assert d.seen_text == CANDIDATE.strip()


def test_given_hosted_scope_ci_when_scanning_staged_then_the_model_is_not_called_a_candidate_only_warns_and_the_note_says_why(tmp_path, monkeypatch, capsys):
	staged_repo(tmp_path, monkeypatch)
	d = FakeDecider(lambda p, t: 1.0)
	assert main(["scan", "--staged"], env={**HOSTED, "SECRET_GUARD_HOSTED_SCOPE": "ci"}, decider=d) == 0
	out = capsys.readouterr()
	assert d.batches == [] and "WARN" in out.out
	assert "hosted model not used for commits (SECRET_GUARD_HOSTED_SCOPE=ci)" in out.err and "CI will judge them" in out.err


def test_given_hosted_scope_ci_when_scanning_staged_then_json_says_the_model_was_skipped(tmp_path, monkeypatch, capsys):
	staged_repo(tmp_path, monkeypatch)
	main(["scan", "--staged", "--json"], env={**HOSTED, "SECRET_GUARD_HOSTED_SCOPE": "ci"}, decider=FakeDecider())
	data = json.loads(capsys.readouterr().out)
	assert data["model_skipped"] == "hosted_scope" and data["model_unavailable"] is False


def test_given_hosted_scope_ci_when_a_rule_hit_is_staged_then_it_still_blocks(tmp_path, monkeypatch):
	staged_repo(tmp_path, monkeypatch, f'KEY = "{AWS_KEY}"\n', "app.py")
	assert main(["scan", "--staged"], env={**HOSTED, "SECRET_GUARD_HOSTED_SCOPE": "ci"}, decider=FakeDecider()) == 1


def test_given_hosted_scope_ci_when_scanning_files_then_the_hosted_model_judges_the_unmasked_line(tmp_path):
	d = FakeDecider(lambda p, t: 0.95)
	env = {**HOSTED, "SECRET_GUARD_HOSTED_SCOPE": "ci"}
	assert main(["scan", "--files", write(tmp_path, "db.py", CANDIDATE)], env=env, decider=d) == 1
	assert d.seen_text == CANDIDATE.strip()


def test_given_hosted_scope_ci_when_the_range_adds_a_candidate_then_the_hosted_model_judges_it(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	git(tmp_path, "config", "user.name", "t")
	git(tmp_path, "config", "user.email", "t@example.com")
	git(tmp_path, "commit", "-q", "--allow-empty", "-m", "base")
	(tmp_path / "db.py").write_text(CANDIDATE)
	git(tmp_path, "add", "db.py")
	git(tmp_path, "commit", "-q", "-m", "add")
	monkeypatch.chdir(tmp_path)
	d = FakeDecider(lambda p, t: 0.95)
	assert main(["scan", "--diff", "HEAD~1..HEAD"], env={**HOSTED, "SECRET_GUARD_HOSTED_SCOPE": "ci"}, decider=d) == 1
	assert d.seen_text == CANDIDATE.strip()


def test_given_hosted_scope_ci_and_a_loopback_url_when_scanning_staged_then_the_model_is_still_used(tmp_path, monkeypatch):
	staged_repo(tmp_path, monkeypatch)
	d = FakeDecider(lambda p, t: 0.1)
	assert main(["scan", "--staged"], env={"SECRET_GUARD_HOSTED_SCOPE": "ci"}, decider=d) == 0
	assert d.batches


def test_given_repo_scope_ci_and_env_scope_all_when_scanning_staged_then_the_repo_narrowing_wins(tmp_path, monkeypatch):
	staged_repo(tmp_path, monkeypatch)
	(tmp_path / ".secret-guard.toml").write_text('[model]\nhosted_scope = "ci"\n')
	d = FakeDecider(lambda p, t: 1.0)
	assert main(["scan", "--staged"], env={**HOSTED, "SECRET_GUARD_HOSTED_SCOPE": "all"}, decider=d) == 0
	assert d.batches == []


def test_given_a_bad_scope_when_scanning_then_exit_2_names_the_allowed_values(tmp_path, capsys):
	f = write(tmp_path, "a.py", "x = 1\n")
	assert main(["scan", "--files", f], env={"SECRET_GUARD_HOSTED_SCOPE": "never"}, decider=FakeDecider()) == 2
	assert "all, ci" in capsys.readouterr().err


def test_given_a_hosted_http_url_when_scanning_then_exit_2_and_nothing_is_sent(tmp_path):
	d = FakeDecider()
	env = {"SECRET_GUARD_BASE_URL": "http://llm.example.com", "SECRET_GUARD_ALLOW_HOSTED": "1"}
	assert main(["scan", "--files", write(tmp_path, "db.py", CANDIDATE)], env=env, decider=d) == 2 and d.batches == []


def test_given_a_hosted_url_when_running_doctor_then_it_warns_that_candidate_lines_are_sent_unmasked(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	main(["install-hook", "--shared"], env={})
	assert main(["doctor"], env=HOSTED, decider=FakeDecider()) == 0
	out = capsys.readouterr().out
	assert "WARN" in out and "llm.example.com" in out and "unmasked" in out


def test_given_hosted_scope_ci_when_running_doctor_then_it_says_commits_fall_back_to_rules_and_does_not_call_the_model(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	main(["install-hook", "--shared"], env={})
	d = FakeDecider()
	main(["doctor"], env={**HOSTED, "SECRET_GUARD_HOSTED_SCOPE": "ci"}, decider=d)
	assert "used in CI only; commits fall back to rules" in capsys.readouterr().out and d.batches == []


def test_given_doctor_when_run_then_it_prints_the_version(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	main(["doctor"], env={}, decider=FakeDecider())
	assert "version" in capsys.readouterr().out


# --- baseline, allowlist migrate, [[allow]], inline pragma, install-hook --chain


def finding_fingerprint(capsys, *args):
	main(["scan", *args, "--json"], env={}, decider=FakeDecider(lambda p, t: 0.99))
	return json.loads(capsys.readouterr().out)["findings"][0]["fingerprint"]


def test_given_a_finding_when_printing_then_the_fingerprint_is_v2(tmp_path, monkeypatch, capsys):
	staged_repo(tmp_path, monkeypatch)
	assert finding_fingerprint(capsys, "--staged").startswith("v2:")


def test_given_an_allow_entry_with_a_reason_when_scanning_then_the_finding_is_accepted(tmp_path, monkeypatch, capsys):
	staged_repo(tmp_path, monkeypatch)
	fp = finding_fingerprint(capsys, "--staged")
	(tmp_path / ".secret-guard.toml").write_text(f'[[allow]]\nfingerprint = "{fp}"\nreason = "fixture"\npath = "db.py"\n')
	assert main(["scan", "--staged"], env={}, decider=FakeDecider(lambda p, t: 0.99)) == 0


def test_given_inline_allow_when_the_repo_enables_it_then_the_pragma_works_and_otherwise_not(tmp_path, monkeypatch):
	staged_repo(tmp_path, monkeypatch, 'DB_PASS = "Winter2026!Admin"  # smart-commit-guard: allow\n')
	assert main(["scan", "--staged"], env={}, decider=FakeDecider(lambda p, t: 0.99)) == 1
	(tmp_path / ".secret-guard.toml").write_text("allow_inline = true\n")
	assert main(["scan", "--staged"], env={}, decider=FakeDecider(lambda p, t: 0.99)) == 0


def test_given_an_existing_repo_with_findings_when_using_a_baseline_then_only_new_findings_fail(tmp_path, monkeypatch, capsys):
	staged_repo(tmp_path, monkeypatch)
	git(tmp_path, "commit", "-q", "-m", "old")
	assert main(["baseline", "create", "--no-model"], env={}) == 0
	baseline = json.loads((tmp_path / ".secret-guard-baseline.json").read_text())
	assert baseline["version"] == 1 and len(baseline["findings"]) == 1 and "Winter2026" not in json.dumps(baseline)
	capsys.readouterr()
	d = FakeDecider(lambda p, t: 0.99)
	assert main(["scan", "--all", "--baseline", ".secret-guard-baseline.json"], env={}, decider=d) == 0
	(tmp_path / "new.py").write_text('API_TOKEN = "Zq8Lm2Pr0dKx9Wv3TnHq7zLm2"\n')
	git(tmp_path, "add", "new.py")
	assert main(["scan", "--all", "--baseline", ".secret-guard-baseline.json"], env={}, decider=d) == 1


def test_given_a_missing_or_invalid_baseline_when_scanning_then_exit_2(tmp_path, capsys):
	f = write(tmp_path, "a.py", "x = 1\n")
	assert main(["scan", "--files", f, "--baseline", str(tmp_path / "nope.json")], env={}, decider=FakeDecider()) == 2
	bad = write(tmp_path, "bad.json", '{"nope": 1}')
	assert main(["scan", "--files", f, "--baseline", bad], env={}, decider=FakeDecider()) == 2
	assert "baseline" in capsys.readouterr().err


def test_given_v1_fingerprints_when_migrating_then_they_become_v2_and_comments_survive(tmp_path, monkeypatch, capsys):
	from smart_commit_guard.redact import fingerprint, mask

	staged_repo(tmp_path, monkeypatch)
	masked = 'DB_PASS = "' + mask("Winter2026!Admin") + '"'
	v1 = fingerprint("db.py", masked)
	(tmp_path / ".secret-guard.toml").write_text(f'# keep me\nallowlist = ["{v1}", "deadbeefdeadbeef"]\n')
	assert main(["allowlist", "migrate"], env={}) == 0
	text = (tmp_path / ".secret-guard.toml").read_text()
	err = capsys.readouterr().err
	assert text.startswith("# keep me") and f'"{v1}"' not in text and '"v2:' in text and "deadbeefdeadbeef" in text
	assert "deadbeefdeadbeef" in err   # reported as stale
	assert main(["scan", "--staged"], env={}, decider=FakeDecider(lambda p, t: 0.99)) == 0   # the v2 entry matches


def test_given_no_config_file_when_migrating_then_exit_2(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	assert main(["allowlist", "migrate"], env={}) == 2


def test_given_an_existing_hook_when_installing_with_chain_then_it_is_kept_and_runs_first(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	hook = tmp_path / ".git" / "hooks" / "pre-commit"
	hook.write_text("#!/bin/sh\necho mine >> ran.txt\n")
	monkeypatch.chdir(tmp_path)
	assert main(["install-hook"], env={}) == 2
	assert main(["install-hook", "--chain"], env={}) == 0
	local = tmp_path / ".git" / "hooks" / "pre-commit.local"
	assert "echo mine" in local.read_text() and "pre-commit.local" in hook.read_text() and "scan --staged" in hook.read_text()
	assert hook.read_text().index("pre-commit.local") < hook.read_text().index("scan --staged")


@pytest.mark.skipif(sys.platform == "win32", reason="runs a POSIX shell hook")
def test_given_a_chained_hook_when_the_local_hook_fails_then_the_commit_is_refused_before_the_scan(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	hooks = tmp_path / ".git" / "hooks"
	(hooks / "pre-commit").write_text("#!/bin/sh\nexit 7\n")
	(hooks / "pre-commit").chmod(0o755)
	monkeypatch.chdir(tmp_path)
	main(["install-hook", "--chain"], env={})
	r = subprocess.run([str(hooks / "pre-commit")], cwd=tmp_path, capture_output=True, check=False)
	assert r.returncode == 7


def test_given_chain_and_no_existing_hook_when_installing_then_a_plain_hook_is_written(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	assert main(["install-hook", "--chain"], env={}) == 0
	assert "pre-commit.local" not in (tmp_path / ".git" / "hooks" / "pre-commit").read_text()


def test_given_chain_and_shared_when_a_hook_exists_there_then_it_is_chained(tmp_path, monkeypatch):
	git(tmp_path, "init", "-q")
	shared = tmp_path / ".githooks"
	shared.mkdir()
	(shared / "pre-commit").write_text("#!/bin/sh\necho husky\n")
	monkeypatch.chdir(tmp_path)
	assert main(["install-hook", "--shared", "--chain"], env={}) == 0
	assert "echo husky" in (shared / "pre-commit.local").read_text() and "pre-commit.local" in (shared / "pre-commit").read_text()


# --- doctor: the hook can find the tool, and a stale shared hook is noticed; model settings in the repo file; push ranges


def test_given_a_hook_that_cannot_find_the_tool_when_running_doctor_then_it_fails(tmp_path, monkeypatch, capsys):
	from smart_commit_guard import cli

	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	main(["install-hook", "--shared"], env={})
	monkeypatch.setattr(cli.shutil, "which", lambda *a, **k: None)
	assert main(["doctor"], env={}, decider=FakeDecider()) == 1
	assert "cannot find smart-commit-guard" in capsys.readouterr().out


def test_given_a_healthy_hook_when_running_doctor_then_it_reports_the_tool_and_its_version(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	main(["install-hook", "--shared"], env={})
	assert main(["doctor"], env={}, decider=FakeDecider()) == 0
	out = capsys.readouterr().out
	assert "hook tool" in out and "9.9.9" in out and "shared hook" not in out


def test_given_a_stale_shared_hook_when_running_doctor_then_it_warns_but_does_not_fail(tmp_path, monkeypatch, capsys):
	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	main(["install-hook", "--shared"], env={})
	hook = tmp_path / ".githooks" / "pre-commit"
	hook.write_text(hook.read_text().replace("exec uvx", "exec uvx --old"))
	assert main(["doctor"], env={}, decider=FakeDecider()) == 0
	assert "WARN" in capsys.readouterr().out


def test_given_the_shared_hook_when_installing_then_the_uvx_fallback_is_pinned_to_the_minor_range(tmp_path, monkeypatch):
	from smart_commit_guard import cli

	git(tmp_path, "init", "-q")
	monkeypatch.chdir(tmp_path)
	monkeypatch.setattr(cli, "__version__", "0.2.3")
	main(["install-hook", "--shared"], env={})
	assert "uvx --from 'smart-commit-guard>=0.2,<0.3' smart-commit-guard scan --staged" in (tmp_path / ".githooks" / "pre-commit").read_text()
	monkeypatch.setattr(cli, "__version__", "unknown")
	main(["install-hook", "--shared", "--force"], env={})
	assert "exec uvx smart-commit-guard scan --staged" in (tmp_path / ".githooks" / "pre-commit").read_text()


def test_given_model_settings_in_the_repo_file_when_scanning_then_they_apply_unless_the_environment_overrides(tmp_path, monkeypatch):
	staged_repo(tmp_path, monkeypatch)
	(tmp_path / ".secret-guard.toml").write_text('[model]\nblock_at = 0.9\nwarn_at = 0.8\nname = "other:1b"\n')
	d = FakeDecider(lambda p, t: 0.7)
	assert main(["scan", "--staged"], env={}, decider=d) == 0   # 0.7 is below the repo's block and warn thresholds
	assert main(["scan", "--staged"], env={"SECRET_GUARD_BLOCK_AT": "0.5", "SECRET_GUARD_WARN_AT": "0.4"}, decider=d) == 1


def test_given_a_push_event_on_a_new_branch_when_scanning_the_range_then_the_whole_branch_is_scanned(tmp_path, monkeypatch):
	staged_repo(tmp_path, monkeypatch, f'KEY = "{AWS_KEY}"\n', "app.py")
	git(tmp_path, "commit", "-q", "-m", "x")
	zeros = "0" * 40
	assert main(["scan", "--diff", f"{zeros}..HEAD", "--no-model"], env={}) == 1
	assert main(["scan", "--diff", f"{zeros}...HEAD", "--no-model"], env={}) == 1


def test_given_a_missing_base_revision_when_scanning_a_diff_then_the_message_mentions_fetch_depth(tmp_path, monkeypatch, capsys):
	staged_repo(tmp_path, monkeypatch, "x = 1\n", "a.py")
	git(tmp_path, "commit", "-q", "-m", "x")
	assert main(["scan", "--diff", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef..HEAD", "--no-model"], env={}) == 2
	assert "fetch-depth: 0" in capsys.readouterr().err
