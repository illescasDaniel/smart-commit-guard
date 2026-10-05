"""Real temp repos: a user's git config, attributes or file names must never make the scan see less than is staged."""
import json
import shutil
import subprocess
import sys

import pytest
from conftest import AWS_KEY, FakeDecider

from smart_commit_guard import git
from smart_commit_guard.cli import main

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX shell tool or POSIX file names")


def run(repo, *args):
	subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
	run(tmp_path, "init", "-q")
	run(tmp_path, "config", "user.name", "t")
	run(tmp_path, "config", "user.email", "t@example.com")
	monkeypatch.chdir(tmp_path)
	return tmp_path


def stage(repo, name, content=f'KEY = "{AWS_KEY}"\n'):
	path = repo / name
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(content if isinstance(content, bytes) else content.encode())
	run(repo, "add", "--", name)


def scan_staged(capsys, *extra):
	code = main(["scan", "--staged", "--json", *extra], env={}, decider=FakeDecider())
	return code, json.loads(capsys.readouterr().out)


# --- 0.1 user git config can make the scan see nothing


@posix_only
def test_given_an_external_diff_tool_when_scanning_staged_then_the_secret_is_still_found(repo, capsys):
	run(repo, "config", "diff.external", shutil.which("true") or "/bin/true")
	stage(repo, "app.py")
	assert scan_staged(capsys)[0] == 1


@pytest.mark.parametrize("attribute", ["binary", "-diff"])
def test_given_a_file_marked_binary_in_gitattributes_when_scanning_staged_then_the_secret_is_still_found(repo, capsys, attribute):
	(repo / ".gitattributes").write_text(f"app.py {attribute}\n")
	stage(repo, "app.py")
	code, data = scan_staged(capsys)
	assert code == 1 and data["findings"][0]["path"] == "app.py"


@posix_only
def test_given_a_textconv_filter_when_scanning_staged_then_the_secret_is_still_found(repo, capsys):
	(repo / ".gitattributes").write_text("*.py diff=hide\n")
	run(repo, "config", "diff.hide.textconv", shutil.which("true") or "/bin/true")
	stage(repo, "app.py")
	assert scan_staged(capsys)[0] == 1


@pytest.mark.parametrize("key, value", [("diff.mnemonicPrefix", "true"), ("diff.noprefix", "true")])
def test_given_a_diff_prefix_option_when_scanning_staged_then_paths_are_still_plain(repo, capsys, key, value):
	run(repo, "config", key, value)
	stage(repo, "app.py")
	code, data = scan_staged(capsys)
	assert code == 1 and [f["path"] for f in data["findings"]] == ["app.py"]


def test_given_diff_relative_and_a_subdirectory_when_scanning_staged_then_paths_stay_relative_to_the_repo_root(repo, capsys, monkeypatch):
	run(repo, "config", "diff.relative", "true")
	stage(repo, "sub/app.py")
	monkeypatch.chdir(repo / "sub")
	code, data = scan_staged(capsys)
	assert code == 1 and [f["path"] for f in data["findings"]] == ["sub/app.py"]


def test_given_a_real_binary_when_scanning_staged_then_it_is_not_read_as_text(repo, capsys):
	stage(repo, "logo.png", b"\x89PNG\r\n\x1a\n" + AWS_KEY.encode())
	stage(repo, "data.bin", b"\0\0\0" + AWS_KEY.encode() + b"\0\0")   # no binary suffix: the NUL bytes give it away
	code, data = scan_staged(capsys)
	assert code == 0 and data["findings"] == []


def test_given_a_large_binary_next_to_text_when_scanning_staged_then_the_text_is_still_scanned(repo, capsys):
	stage(repo, "blob.zip", bytes(range(256)) * 4000)
	stage(repo, "app.py")
	code, data = scan_staged(capsys)
	assert code == 1 and [f["path"] for f in data["findings"]] == ["app.py"]


# --- 0.2 non-ASCII and special file names


@pytest.mark.parametrize("name", ["café.py", "with space.py", "-dash.py", "日本語.py"])
def test_given_an_unusual_file_name_when_scanning_staged_then_the_finding_has_the_real_name(repo, capsys, name):
	stage(repo, name)
	code, data = scan_staged(capsys)
	assert code == 1 and [f["path"] for f in data["findings"]] == [name]


@posix_only
@pytest.mark.parametrize("name", ['quote".py', "tab\there.py", "back\\slash.py"])
def test_given_a_file_name_git_quotes_when_scanning_staged_then_the_finding_has_the_real_name(repo, capsys, name):
	stage(repo, name)
	code, data = scan_staged(capsys)
	assert code == 1 and [f["path"] for f in data["findings"]] == [name]


def test_given_a_skip_glob_and_a_non_ascii_name_when_scanning_staged_then_the_glob_matches(repo, capsys):
	(repo / ".secret-guard.toml").write_text('skip = ["café*"]\n')
	stage(repo, "café.py")
	assert scan_staged(capsys)[0] == 0


def test_given_a_file_renamed_to_a_sensitive_name_when_scanning_staged_then_it_blocks_by_name(repo, capsys):
	stage(repo, "config.json", "{}\n")
	run(repo, "commit", "-q", "-m", "init")
	run(repo, "mv", "config.json", ".env")
	code, data = scan_staged(capsys)
	assert code == 1 and [f["path"] for f in data["findings"]] == [".env"]


@pytest.mark.parametrize("raw, expected", [
	('"caf\\303\\251.py"', "café.py"), ('"a\\tb"', "a\tb"), ('"say \\"hi\\".py"', 'say "hi".py'), ('"back\\\\slash"', "back\\slash"),
	('"line\\nbreak"', "line\nbreak"), ('"\\346\\227\\245.py"', "日.py"), ("plain.py", "plain.py"), ('"unterminated', '"unterminated')])
def test_given_a_c_quoted_path_when_unquoting_then_it_is_the_real_name(raw, expected):
	assert git.unquote_path(raw) == expected


# --- 0.3 non-UTF-8 content and crashes


def test_given_a_latin_1_file_when_scanning_staged_then_it_does_not_crash_and_the_secret_is_found(repo, capsys):
	stage(repo, "app.py", b"# caf\xe9\n" + f'KEY = "{AWS_KEY}"\n'.encode())
	assert scan_staged(capsys)[0] == 1


def test_given_a_clean_latin_1_file_when_scanning_staged_then_it_passes(repo, capsys):
	stage(repo, "app.py", b"# caf\xe9\nx = 1\n")
	assert scan_staged(capsys)[0] == 0


def test_given_a_latin_1_file_when_scanning_files_then_it_does_not_crash(tmp_path):
	f = tmp_path / "a.py"
	f.write_bytes(b"# caf\xe9\nx = 1\n")
	assert main(["scan", "--files", str(f)], env={}, decider=FakeDecider()) == 0


def test_given_an_unexpected_crash_when_scanning_then_exit_2_not_1_and_json_says_why(repo, capsys, monkeypatch):
	from smart_commit_guard import cli

	def boom(*a, **k):
		raise RuntimeError("kaboom")

	monkeypatch.setattr(cli, "scan", boom)
	stage(repo, "app.py", "x = 1\n")
	assert main(["scan", "--staged", "--json"], env={}) == 2
	out = capsys.readouterr()
	assert json.loads(out.out) == {"exit_code": 2, "error": "unexpected RuntimeError: kaboom"} and "kaboom" in out.err


def test_given_the_debug_variable_when_a_crash_happens_then_the_traceback_is_printed(repo, capsys, monkeypatch):
	from smart_commit_guard import cli

	monkeypatch.setattr(cli, "scan", lambda *a, **k: 1 / 0)
	stage(repo, "app.py", "x = 1\n")
	assert main(["scan", "--staged"], env={"SMART_COMMIT_GUARD_DEBUG": "1"}) == 2
	assert "Traceback" in capsys.readouterr().err


def test_given_a_tool_error_with_json_when_scanning_then_the_json_carries_the_error(tmp_path, monkeypatch, capsys):
	monkeypatch.chdir(tmp_path)
	assert main(["scan", "--staged", "--json"], env={}) == 2
	assert json.loads(capsys.readouterr().out)["exit_code"] == 2


# --- 0.4 / 2.1 repo config and repo root


@pytest.mark.parametrize("toml", ['skip = "tests/*"', 'allowlist = "abc"', 'skip = [1, 2]', 'allow_list = ["abc"]',
								  'model = "ci"', '[model]\nbase_url = "https://x.example"', '[model]\nhosted_scope = "everywhere"',
								  'skip = [', '[model]\nhosted_scope = 3'])
def test_given_an_invalid_repo_config_when_scanning_then_exit_2_instead_of_scanning_nothing(repo, capsys, toml):
	(repo / ".secret-guard.toml").write_text(toml + "\n")
	stage(repo, "app.py")
	assert main(["scan", "--staged"], env={}, decider=FakeDecider()) == 2
	assert ".secret-guard.toml" in capsys.readouterr().err


def test_given_a_skip_that_matches_everything_when_scanning_then_it_warns_loudly(repo, capsys):
	(repo / ".secret-guard.toml").write_text('skip = ["*"]\n')
	stage(repo, "app.py")
	assert main(["scan", "--staged"], env={}, decider=FakeDecider()) == 0
	assert "cover every changed file" in capsys.readouterr().err


def test_given_a_subdirectory_when_scanning_files_then_the_root_config_applies_and_paths_are_repo_relative(repo, capsys, monkeypatch):
	(repo / ".secret-guard.toml").write_text('skip = ["sub/*"]\n')
	(repo / "sub").mkdir()
	(repo / "sub" / "x.py").write_text(f'KEY = "{AWS_KEY}"\n')
	monkeypatch.chdir(repo / "sub")
	assert main(["scan", "--files", "x.py"], env={}, decider=FakeDecider()) == 0
	assert main(["scan", "--files", "./x.py", str(repo / "sub" / "x.py")], env={}, decider=FakeDecider()) == 0


def test_given_files_paths_spelled_differently_when_fingerprinting_then_the_fingerprint_is_the_same(repo, capsys, monkeypatch):
	(repo / "sub").mkdir()
	(repo / "sub" / "x.py").write_text(f'KEY = "{AWS_KEY}"\n')
	prints = []
	for spelling, cwd in (("sub/x.py", repo), ("./sub/x.py", repo), ("x.py", repo / "sub")):
		monkeypatch.chdir(cwd)
		main(["scan", "--files", spelling, "--json"], env={}, decider=FakeDecider())
		prints.append(json.loads(capsys.readouterr().out)["findings"][0]["fingerprint"])
	assert len(set(prints)) == 1


def test_given_diff_mode_with_a_single_revision_when_scanning_then_it_is_rejected(repo, capsys):
	stage(repo, "a.py", "x = 1\n")
	run(repo, "commit", "-q", "-m", "init")
	assert main(["scan", "--diff", "HEAD"], env={}, decider=FakeDecider()) == 2
	assert "revision range" in capsys.readouterr().err


def test_given_a_diff_range_when_scanning_then_only_lines_added_in_it_are_found(repo, capsys):
	run(repo, "commit", "-q", "--allow-empty", "-m", "zero")
	stage(repo, "a.py")
	run(repo, "commit", "-q", "-m", "one")
	stage(repo, "b.py", "x = 1\n")
	run(repo, "commit", "-q", "-m", "two")
	assert main(["scan", "--diff", "HEAD~1..HEAD"], env={}, decider=FakeDecider()) == 0
	assert main(["scan", "--diff", "HEAD~2..HEAD"], env={}, decider=FakeDecider()) == 1


def test_given_a_config_change_in_the_range_when_scanning_a_diff_then_it_warns_and_config_from_ignores_the_new_skip(repo, capsys):
	stage(repo, "app.py", "x = 1\n")
	run(repo, "commit", "-q", "-m", "base")
	run(repo, "branch", "base")
	stage(repo, "app.py")
	stage(repo, ".secret-guard.toml", 'skip = ["app.py"]\n')
	run(repo, "commit", "-q", "-m", "sneaky")
	assert main(["scan", "--diff", "base..HEAD"], env={}, decider=FakeDecider()) == 0
	assert ".secret-guard.toml changes in this range" in capsys.readouterr().err
	assert main(["scan", "--diff", "base..HEAD", "--config-from", "base"], env={}, decider=FakeDecider()) == 1


# --- 3.1 scan --all, --files -, formats


def test_given_all_when_scanning_then_every_tracked_file_is_checked_from_any_directory(repo, monkeypatch):
	stage(repo, "deep/app.py")
	monkeypatch.chdir(repo / "deep")
	assert main(["scan", "--all", "--no-model"], env={}) == 1


def test_given_paths_on_stdin_when_scanning_files_dash_then_they_are_read_nul_separated(repo, monkeypatch):
	import io

	(repo / "a b.py").write_text(f'KEY = "{AWS_KEY}"\n')
	(repo / "ok.py").write_text("x = 1\n")
	monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(b"ok.py\0a b.py\0")})())
	assert main(["scan", "--files", "-", "--no-model"], env={}) == 1


def test_given_sarif_format_when_scanning_then_the_report_is_valid_json_with_masked_snippets(repo, capsys):
	stage(repo, "app.py")
	assert main(["scan", "--staged", "--format", "sarif"], env={}, decider=FakeDecider()) == 1
	sarif = json.loads(capsys.readouterr().out)
	result = sarif["runs"][0]["results"][0]
	assert sarif["version"] == "2.1.0" and result["level"] == "error"
	assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "app.py"
	assert AWS_KEY not in json.dumps(sarif)


def test_given_github_actions_when_scanning_then_findings_are_also_printed_as_annotations(repo, capsys):
	stage(repo, "app.py")
	main(["scan", "--staged"], env={"GITHUB_ACTIONS": "true"}, decider=FakeDecider())
	assert "::error file=app.py,line=1::" in capsys.readouterr().out


def test_given_a_large_file_when_scanning_files_then_it_is_skipped_with_a_note(tmp_path, capsys, monkeypatch):
	from smart_commit_guard import cli

	monkeypatch.setattr(cli, "MAX_FILE_BYTES", 10)
	f = tmp_path / "big.py"
	f.write_text(f'KEY = "{AWS_KEY}"\n')
	assert main(["scan", "--files", str(f), "--no-model"], env={}) == 0
	assert "over the 10 byte limit" in capsys.readouterr().err


def test_given_a_binary_file_without_a_binary_suffix_when_scanning_files_then_it_is_skipped(tmp_path):
	f = tmp_path / "data.bin"
	f.write_bytes(b"\0" + AWS_KEY.encode())
	assert main(["scan", "--files", str(f), "--no-model"], env={}) == 0


def test_given_version_flag_when_running_then_it_prints_the_version(capsys):
	assert main(["--version"], env={}) == 0
	assert "smart-commit-guard" in capsys.readouterr().out
