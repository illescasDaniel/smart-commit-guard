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
