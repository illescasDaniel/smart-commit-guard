from conftest import AWS_KEY, FakeDecider

from secret_guard.policy import MAX_CALLS, scan
from secret_guard.redact import fingerprint, mask
from secret_guard.types import AddedLine

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
	r = scan([PASS], FakeDecider(lambda p, t: 0.6))
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


def test_given_hosted_when_scanning_then_the_model_only_sees_masked_values():
	d = FakeDecider(lambda p, t: 0.1)
	scan([PASS], d, hosted=True)
	assert d.batches and "Winter2026!Admin" not in d.seen_text


def test_given_local_when_scanning_then_the_model_sees_the_line_as_written():
	d = FakeDecider(lambda p, t: 0.1)
	scan([PASS], d)
	assert "Winter2026!Admin" in d.seen_text


def test_given_an_allowlisted_fingerprint_when_scanning_then_the_finding_is_not_reported():
	fp = fingerprint(PASS.path, PASS.text.replace("Winter2026!Admin", mask("Winter2026!Admin")))
	assert scan([PASS], FakeDecider(lambda p, t: 0.99), allowlist={fp}).findings == []


def test_given_a_skipped_path_when_scanning_then_it_is_not_scanned():
	line = AddedLine("package-lock.json", 1, f'"k": "{AWS_KEY}"')
	d = FakeDecider()
	assert scan([line], d).findings == [] and d.batches == []


def test_given_many_candidates_when_scanning_then_calls_are_batched_and_capped_and_the_rest_is_warned_unjudged():
	lines = [AddedLine("src/a.py", i, f'PASS_{i} = "Winter{i:04d}!Admin"') for i in range(1, 400)]
	d = FakeDecider(lambda p, t: 0.0)
	r = scan(lines, d)
	assert len(d.batches) == MAX_CALLS and all(len(b) <= 30 for b in d.batches)
	assert r.exit_code == 0 and sum(f.level == "warn" for f in r.findings) == len(lines) - MAX_CALLS * 30


def test_given_no_candidates_when_scanning_then_the_model_is_never_called():
	d = FakeDecider()
	scan([AddedLine("src/a.py", 1, "x = 1")], d)
	assert d.batches == []
