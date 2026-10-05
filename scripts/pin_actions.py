"""Pin third-party GitHub Actions to commit SHAs.

	python scripts/pin_actions.py            # rewrite `uses: owner/repo@v1` to `uses: owner/repo@<sha> # v1`
	python scripts/pin_actions.py --check    # exit 1 if any action is not pinned (for CI)

A tag or branch can be moved by whoever controls the action's repository; a commit SHA cannot. Dependabot (see
`.github/dependabot.yml`) understands the `@<sha> # <ref>` form and keeps it up to date. Needs network access to github.com.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

USES = re.compile(r"^(?P<head>\s*(?:-\s*)?uses:\s*)(?P<repo>[\w.-]+/[\w./-]+)@(?P<ref>[^\s#]+)(?P<tail>.*)$")
SHA = re.compile(r"^[0-9a-f]{40}$")
FILES = (".github/workflows/*.yml", ".github/workflows/*.yaml", "action.yml", "action.yaml")


def resolve_with_git(repo: str, ref: str) -> str:
	"""The commit SHA a tag (peeled, for annotated tags) or branch points at."""
	owner_repo = "/".join(repo.split("/")[:2])   # `owner/repo/subpath` actions
	out = subprocess.run(["git", "ls-remote", f"https://github.com/{owner_repo}", f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}",
						  f"refs/heads/{ref}"], capture_output=True, text=True, check=True).stdout
	rows = {name: sha for sha, name in (line.split("\t") for line in out.splitlines() if "\t" in line)}
	for name in (f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", f"refs/heads/{ref}"):
		if name in rows:
			return rows[name]
	raise LookupError(f"{owner_repo}@{ref} not found")


def is_local(repo: str) -> bool:
	return repo.startswith(("./", "docker://"))


def pin(text: str, resolve: Callable[[str, str], str]) -> tuple[str, list[str]]:
	"""(new text, the `repo@ref` entries that were unpinned). Already pinned and local actions are left alone."""
	changed: list[str] = []
	out = []
	for line in text.split("\n"):
		m = USES.match(line)
		if m and not is_local(m["repo"]) and not SHA.match(m["ref"]):
			sha = resolve(m["repo"], m["ref"])
			line = f"{m['head']}{m['repo']}@{sha} # {m['ref']}"
			changed.append(f"{m['repo']}@{m['ref']}")
		out.append(line)
	return "\n".join(out), changed


def main(argv: list[str]) -> int:
	root = Path(__file__).resolve().parents[1]
	check = "--check" in argv
	unpinned = 0
	for pattern in FILES:
		for path in sorted(root.glob(pattern)):
			text = path.read_text(encoding="utf-8")
			new, changed = pin(text, (lambda r, ref: "0" * 40) if check else resolve_with_git)
			unpinned += len(changed)
			for entry in changed:
				print(f"{path.relative_to(root)}: {entry}" + ("" if check else " pinned"))
			if changed and not check:
				path.write_bytes(new.encode("utf-8"))
	if check and unpinned:
		print(f"{unpinned} action(s) are not pinned to a commit SHA; run python scripts/pin_actions.py", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
