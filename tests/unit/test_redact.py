from smart_commit_guard.redact import fingerprint, mask


def test_given_a_secret_when_masking_then_content_is_gone_but_shape_and_known_prefix_remain():
	m = mask("ghp_a1B2c3D4e5F6g7H8i9J0k1L2m3N4")
	assert m.startswith("ghp_") and len(m) == len("ghp_a1B2c3D4e5F6g7H8i9J0k1L2m3N4")
	assert "a1B2c3" not in m


def test_given_two_different_secrets_of_the_same_shape_when_masking_then_the_masks_are_equal():
	assert mask("Winter2026!Admin") == mask("Summer1999?Guest")


def test_given_the_same_masked_finding_when_fingerprinting_then_it_is_stable_and_path_sensitive():
	a = fingerprint("src/a.py", mask("Winter2026!Admin"))
	assert a == fingerprint("src/a.py", mask("Winter2026!Admin"))
	assert a != fingerprint("src/b.py", mask("Winter2026!Admin"))
	assert "Winter" not in a


def test_given_several_hits_on_a_line_when_masking_the_line_then_none_survives():
	from conftest import AWS_KEY

	from smart_commit_guard.redact import mask_line
	from smart_commit_guard.rules import scan_line

	secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzxk3Ntq9Lm"
	line = f'creds = ("{AWS_KEY}", "{secret}")'
	masked = mask_line(line, scan_line(line))
	assert secret not in masked and AWS_KEY not in masked and masked.count("AKIA") == 1


def test_given_a_long_random_looking_token_no_rule_flagged_when_masking_the_line_then_it_is_masked_too():
	from smart_commit_guard.redact import mask_line

	line = "see x9Qm2LpV7sTr4KdW8zYb in the logs"
	assert "x9Qm2LpV7sTr4KdW8zYb" not in mask_line(line, [])
	assert "a_long_snake_case_identifier_name" in mask_line("a_long_snake_case_identifier_name = 1", [])   # no digit: not a secret


def test_given_a_masked_line_when_masking_again_then_it_does_not_change():
	from smart_commit_guard.redact import mask_line

	once = mask_line("k = x9Qm2LpV7sTr4KdW8zYb1N", [])
	assert mask_line(once, []) == once
