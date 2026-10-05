import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("pin_actions", Path(__file__).resolve().parents[2] / "scripts" / "pin_actions.py")
assert SPEC and SPEC.loader
pin_actions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pin_actions)

SHA = "a" * 40


def fake(repo, ref):
	return SHA if ref != "v2" else "b" * 40


def test_given_tag_and_branch_refs_when_pinning_then_they_become_shas_with_the_ref_as_a_comment():
	text = "steps:\n  - uses: actions/checkout@v7\n  - uses: pypa/gh-action-pypi-publish@release/v1\n    with: {a: 1}\n"
	new, changed = pin_actions.pin(text, fake)
	assert f"- uses: actions/checkout@{SHA} # v7" in new and f"gh-action-pypi-publish@{SHA} # release/v1" in new
	assert changed == ["actions/checkout@v7", "pypa/gh-action-pypi-publish@release/v1"] and "with: {a: 1}" in new


def test_given_pinned_local_and_docker_actions_when_pinning_then_they_are_untouched():
	text = f"- uses: actions/checkout@{SHA} # v7\n- uses: ./local\n- uses: docker://alpine:3\n"
	assert pin_actions.pin(text, fake) == (text, [])


def test_given_a_subpath_action_when_pinning_then_the_subpath_is_kept():
	new, _ = pin_actions.pin("      uses: github/codeql-action/analyze@v3", fake)
	assert new == f"      uses: github/codeql-action/analyze@{SHA} # v3"
