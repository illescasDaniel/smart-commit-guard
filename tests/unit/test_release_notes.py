import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_notes", ROOT / "scripts" / "release_notes.py")
assert SPEC and SPEC.loader
release_notes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_notes)

LOG = "# Changelog\n\n## 0.2.0 - 2026-10-05\n\nintro\n\n### Fixed\n- a\n\n## 0.1.0\n\n- first\n"


def test_given_a_version_when_extracting_then_only_its_section_is_returned():
	assert release_notes.section(LOG, "v0.2.0") == "intro\n\n### Fixed\n- a"
	assert release_notes.section(LOG, "0.1.0") == "- first"


def test_given_an_unknown_version_when_extracting_then_none():
	assert release_notes.section(LOG, "9.9.9") is None


def test_given_the_real_changelog_when_extracting_the_current_version_then_there_are_notes():
	import tomllib

	version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
	assert release_notes.section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version)
