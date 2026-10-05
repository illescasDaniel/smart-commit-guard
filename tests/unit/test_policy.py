import pytest
from conftest import AWS_KEY, FakeDecider

from smart_commit_guard.decider import MAX_BATCH
from smart_commit_guard.policy import MAX_CALLS, scan
from smart_commit_guard.redact import fingerprint, mask
from smart_commit_guard.types import AddedLine

AWS = AddedLine("src/app.py", 1, f'AWS_KEY = "{AWS_KEY}"')
PASS = AddedLine("src/db.py", 4, 'DB_PASS = "Winter2026!Admin"')
PLACEHOLDER = AddedLine("README.md", 9, 'API_KEY = "your-api-key-here"')


def test_given_an_aws_key_in_source_when_scanning_then_it_blocks_with_a_masked_preview_and_no_model_call():
	d = FakeDecider()
	r = scan([AWS], d)
	assert r.exit_code == 1 and d.batches == []
	assert AWS_KEY not in r.findings[0].preview and r.findings[0].reason


def test_given_a_placeholder_in_a_readme_and_a_low_model_score_when_scanning_then_it_passes():
	r = scan([PLACEHOLDER], FakeDecider(lambda p, t: 0.03))
	assert r.exit_code == 0 and r.findings == []


def test_given_a_rule_hit_in_a_test_path_when_scanning_then_the_model_decides():
	line = AddedLine("tests/test_x.py", 2, f'KEY = "{AWS_KEY}"')
	assert scan([line], FakeDecider(lambda p, t: 0.02)).exit_code == 0
	assert scan([line], FakeDecider(lambda p, t: 0.95)).exit_code == 1


def test_given_a_candidate_above_the_block_threshold_when_scanning_then_it_blocks():
	r = scan([PASS], FakeDecider(lambda p, t: 0.92))
	assert r.exit_code == 1 and r.findings[0].p == 0.92


def test_given_a_candidate_between_warn_and_block_when_scanning_then_it_warns_and_allows():
	r = scan([PASS], FakeDecider(lambda p, t: 0.45))
	assert r.exit_code == 0 and [f.level for f in r.findings] == ["warn"]


def test_given_the_model_is_down_and_a_rule_hit_when_scanning_then_it_still_blocks():
	d = FakeDecider()
	d.down = True
	assert scan([AWS, PASS], d).exit_code == 1


def test_given_the_model_is_down_and_only_a_candidate_when_scanning_then_it_warns_that_the_model_was_unavailable():
	d = FakeDecider()
	d.down = True
	r = scan([PASS], d)
	assert r.exit_code == 0 and r.model_unavailable and [f.level for f in r.findings] == ["warn"]


def test_given_no_decider_when_scanning_then_only_rules_apply_and_candidates_are_warned_as_unjudged():
	r = scan([AWS, PASS], None)
	assert r.exit_code == 1 and any(f.level == "warn" and f.number == 4 for f in r.findings)


def test_given_a_candidate_when_scanning_then_the_model_sees_the_line_as_written_whatever_the_backend():
	d = FakeDecider(lambda p, t: 0.1)
	scan([PASS], d)
	assert "Winter2026!Admin" in d.seen_text


def test_given_an_allowlisted_fingerprint_when_scanning_then_the_finding_is_not_reported():
	fp = fingerprint(PASS.path, PASS.text.replace("Winter2026!Admin", mask("Winter2026!Admin")))
	assert scan([PASS], FakeDecider(lambda p, t: 0.99), allowlist={fp}).findings == []


def test_given_a_binary_path_when_scanning_then_it_is_not_scanned():
	line = AddedLine("logo.png", 1, f'"k": "{AWS_KEY}"')
	d = FakeDecider()
	assert scan([line], d).findings == [] and d.batches == []


def test_given_a_lockfile_or_minified_file_when_scanning_then_only_the_rules_run_and_the_model_is_never_called():
	d = FakeDecider(lambda p, t: 1.0)
	key = AddedLine("package-lock.json", 1, f'"k": "{AWS_KEY}"')
	noise = [AddedLine("dist/app.min.js", 1, 'DB_PASS = "Winter2026!Admin"'), AddedLine("uv.lock", 2, 'blob = "x9Qm2LpV7sTr4KdW8zYb1NcE6hJf3AgU"')]
	r = scan([key, *noise], d)
	assert [f.path for f in r.findings] == ["package-lock.json"] and r.exit_code == 1 and d.batches == []


def test_given_many_candidates_when_scanning_then_calls_are_capped_and_the_rest_is_warned_unjudged():
	lines = [AddedLine("src/a.py", i, f'PASS_{i} = "Winter{i:04d}!Admin"') for i in range(1, 60)]
	d = FakeDecider(lambda p, t: 0.0)
	r = scan(lines, d)
	assert len(d.batches) == MAX_CALLS and all(len(b) <= MAX_BATCH for b in d.batches)
	assert r.exit_code == 0 and sum(f.level == "warn" for f in r.findings) == len(lines) - MAX_CALLS * MAX_BATCH


def test_given_no_candidates_when_scanning_then_the_model_is_never_called():
	d = FakeDecider()
	scan([AddedLine("src/a.py", 1, "x = 1")], d)
	assert d.batches == []


def test_given_an_env_file_with_any_value_when_scanning_then_it_blocks_once_without_the_model_or_printing_contents():
	d = FakeDecider()
	r = scan([AddedLine(".env", 1, "# local"), AddedLine(".env", 2, "A=b"), AddedLine(".env", 3, "C=d")], d)
	assert r.exit_code == 1 and d.batches == [] and len(r.findings) == 1
	assert r.findings[0].number == 2 and "A=b" not in r.findings[0].preview


def test_given_an_empty_or_comment_only_env_file_when_scanning_then_it_passes():
	assert scan([AddedLine(".env", 1, "# nothing"), AddedLine(".env", 2, "")], FakeDecider()).exit_code == 0


def test_given_an_allowlisted_env_file_when_scanning_then_it_passes():
	fp = fingerprint(".env", "<contents hidden>")
	assert scan([AddedLine(".env", 1, "A=b")], FakeDecider(), allowlist={fp}).exit_code == 0


def test_given_an_env_example_when_scanning_then_it_is_still_skipped():
	assert scan([AddedLine(".env.example", 1, "A=b")], FakeDecider()).exit_code == 0


def test_given_a_binary_key_store_listed_only_by_path_when_scanning_then_it_blocks_by_name():
	r = scan([], FakeDecider(), paths=["certs/prod.p12", "logo.png"])
	assert r.exit_code == 1 and [f.path for f in r.findings] == ["certs/prod.p12"]


def test_given_a_private_key_file_with_text_lines_when_scanning_then_it_blocks_once_by_name():
	lines = [AddedLine("id_rsa", i, "abcdefg") for i in range(1, 4)]
	r = scan(lines, FakeDecider())
	assert len(r.findings) == 1 and r.findings[0].reason == "SSH private key"


def test_given_an_allowlisted_sensitive_file_when_scanning_then_it_passes():
	fp = fingerprint("certs/prod.p12", "<contents hidden>")
	assert scan([], FakeDecider(), paths=["certs/prod.p12"], allowlist={fp}).exit_code == 0


# --- 0.6: the model gets the real line in every mode


def test_given_a_candidate_when_scanning_then_the_decider_receives_exactly_the_candidate_line_and_nothing_else():
	d = FakeDecider(lambda p, t: 0.1)
	scan([AddedLine("src/a.py", 1, "x = 1"), PASS, AddedLine("src/b.py", 2, "y = 2")], d)
	assert d.batches == [[("src/db.py", 'DB_PASS = "Winter2026!Admin"')]]


def test_given_a_rule_hit_that_blocks_when_scanning_then_it_never_reaches_the_model_even_with_other_candidates_on_the_line():
	d = FakeDecider(lambda p, t: 0.1)
	line = AddedLine("src/a.py", 1, f'a = "{AWS_KEY}"; DB_PASS = "Winter2026!Admin"')
	r = scan([line], d)
	assert r.exit_code == 1 and d.batches == []


# --- 0.7 / 0.8: one finding per line, the most severe hit wins, the preview masks everything


def test_given_two_secrets_on_a_line_when_scanning_then_one_finding_masks_both_and_names_the_rules():
	secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzxk3Ntq9Lm"
	r = scan([AddedLine("src/a.py", 3, f'creds = ("{AWS_KEY}", "{secret}")')], FakeDecider())
	(f,) = r.findings
	assert f.level == "block" and "AWS access key pattern" in f.reason
	assert secret not in f.preview and AWS_KEY not in f.preview


def test_given_a_placeholder_then_a_real_secret_on_one_line_when_scanning_then_the_real_one_is_judged():
	d = FakeDecider(lambda p, t: 0.95)
	r = scan([AddedLine("src/a.json", 1, '{"password": "changeme", "token": "q8Zr2LmW9vXp4TnK7"}')], d)
	assert r.exit_code == 1 and "q8Zr2LmW9vXp4TnK7" not in r.findings[0].preview


def test_given_two_candidates_on_a_line_when_scanning_then_the_highest_score_decides_the_finding():
	line = AddedLine("src/a.py", 1, 'a_password = "Winter2026!Admin"; b_token = "q8Zr2LmW9vXp4TnK7yH"')
	r = scan([line], FakeDecider(lambda p, t: 0.9))
	assert len(r.findings) == 1 and r.findings[0].p == 0.9 and r.exit_code == 1


# --- 0.9: the model sees the candidate even deep inside a long line


LONG = AddedLine("web/app.min.json", 1, '{"a": "' + "x" * 500 + '", "password": "Winter2026!Admin", "b": "' + "y" * 500 + '"}')


def test_given_a_candidate_deep_inside_a_long_line_when_scanning_then_the_model_payload_contains_it():
	d = FakeDecider(lambda p, t: 0.1)
	scan([LONG], d)
	(sent,) = [t for b in d.batches for _, t in b]
	assert "Winter2026!Admin" in sent and 'password"' in sent and len(sent) < 400 and sent.startswith("…") and sent.endswith("…")


def test_given_a_value_at_column_350_when_windowing_then_it_is_inside_the_window():
	from smart_commit_guard.policy import window

	text = "k" * 350 + "SECRETVALUE1234" + "z" * 400
	w = window(text, 350, 365)
	assert "SECRETVALUE1234" in w and len(w) <= 302


def test_given_short_lines_when_windowing_then_they_are_unchanged():
	from smart_commit_guard.policy import window

	assert window("x = 1", 0, 1) == "x = 1"


def test_given_a_candidate_near_the_end_of_a_long_line_when_windowing_then_the_window_slides_instead_of_shrinking():
	from smart_commit_guard.policy import window

	text = "a" * 1000 + "SECRET"
	w = window(text, 1000, 1006)
	assert w.endswith("SECRET") and not w.endswith("…") and len(w) >= 300


def test_given_a_value_longer_than_the_window_when_windowing_then_its_beginning_is_kept():
	from smart_commit_guard.policy import window

	w = window("password = " + "Q" * 900, 11, 911)
	assert "Q" * 100 in w and w.endswith("…") and len(w) < 400


# --- 2.2: budget and duplicates


def test_given_the_same_candidate_pasted_in_several_places_when_scanning_then_it_is_judged_once():
	lines = [AddedLine("src/a.py", i, 'DB_PASS = "Winter2026!Admin"') for i in range(1, 6)]
	d = FakeDecider(lambda p, t: 0.95)
	r = scan(lines, d)
	assert len(d.batches) == 1 and len(r.findings) == 5 and r.exit_code == 1


def test_given_a_time_budget_when_it_runs_out_then_the_rest_is_not_judged_and_only_warns():
	ticks = iter(range(1000))
	lines = [AddedLine("src/a.py", i, f'PASS_{i} = "Winter{i:04d}!Admin"') for i in range(1, 11)]
	d = FakeDecider(lambda p, t: 0.0)
	r = scan(lines, d, budget=3.5, clock=lambda: next(ticks))   # every clock read advances one second
	assert r.budget_exhausted and 0 < len(d.batches) < 10 and r.exit_code == 0
	assert sum(f.level == "warn" for f in r.findings) == 10 - len(d.batches)


def test_given_no_budget_when_scanning_then_it_never_runs_out():
	lines = [AddedLine("src/a.py", i, f'PASS_{i} = "Winter{i:04d}!Admin"') for i in range(1, 6)]
	assert not scan(lines, FakeDecider(), budget=None).budget_exhausted


# --- fingerprint v2, [[allow]] paths and the inline pragma


def test_given_a_v2_fingerprint_when_the_line_is_re_indented_then_it_still_matches_but_v1_does_not():
	from smart_commit_guard.redact import fingerprint_v2

	masked = 'DB_PASS = "' + mask("Winter2026!Admin") + '"'
	v2 = fingerprint_v2(PASS.path, masked)
	assert v2.startswith("v2:")
	indented = AddedLine(PASS.path, 4, "\t\t" + PASS.text)
	assert scan([indented], FakeDecider(lambda p, t: 0.99), allowlist={v2}).findings == []
	assert scan([indented], FakeDecider(lambda p, t: 0.99), allowlist={fingerprint(PASS.path, masked)}).exit_code == 1


def test_given_a_v1_fingerprint_when_scanning_the_same_line_then_it_is_still_accepted_for_now():
	masked = 'DB_PASS = "' + mask("Winter2026!Admin") + '"'
	assert scan([PASS], FakeDecider(lambda p, t: 0.99), allowlist={fingerprint(PASS.path, masked)}).findings == []


def test_given_an_allow_entry_with_a_path_glob_when_the_path_does_not_match_then_it_does_not_apply():
	from smart_commit_guard.redact import fingerprint_v2

	masked = 'DB_PASS = "' + mask("Winter2026!Admin") + '"'
	fp = fingerprint_v2(PASS.path, masked)
	assert scan([PASS], FakeDecider(lambda p, t: 0.99), allowlist={fp}, allow_paths={fp: "src/*"}).findings == []
	assert scan([PASS], FakeDecider(lambda p, t: 0.99), allowlist={fp}, allow_paths={fp: "tests/*"}).exit_code == 1


def test_given_the_inline_pragma_when_it_is_enabled_then_only_that_line_is_ignored():
	other = AddedLine("src/db.py", 5, 'DB_PASS = "Winter2026!Admin"')
	marked = AddedLine("src/db.py", 4, 'DB_PASS = "Winter2026!Admin"  # smart-commit-guard: allow')
	r = scan([marked, other], FakeDecider(lambda p, t: 0.99), inline_allow=True)
	assert [f.number for f in r.findings] == [5]


def test_given_the_inline_pragma_when_it_is_not_enabled_then_it_changes_nothing():
	marked = AddedLine("src/db.py", 4, 'DB_PASS = "Winter2026!Admin"  # smart-commit-guard: allow')
	assert scan([marked], FakeDecider(lambda p, t: 0.99)).exit_code == 1


def test_given_the_inline_pragma_when_a_file_name_is_sensitive_then_the_file_still_blocks():
	line = AddedLine("id_rsa", 1, "abc  # smart-commit-guard: allow")
	assert scan([line], FakeDecider(), inline_allow=True).exit_code == 1


@pytest.mark.parametrize("marker", ["# gitleaks:allow", "# pragma: allowlist secret", "// smart-commit-guard: allow"])
def test_given_another_tools_inline_marker_when_inline_allow_is_on_then_the_line_is_ignored(marker):
	line = AddedLine("src/db.py", 4, f'DB_PASS = "Winter2026!Admin"  {marker}')
	assert scan([line], FakeDecider(lambda p, t: 0.99), inline_allow=True).findings == []
