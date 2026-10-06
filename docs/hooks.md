# Hooks: sharing them with a team, and testing them

`smart-commit-guard install-hook` writes a `pre-commit` hook (the staged diff) and a `commit-msg` hook (the message). Back to the [README](../README.md).

The shared hook (`install-hook --shared`, committed as `.githooks/`) finds `smart-commit-guard` on `PATH`, then in the repo's `.venv`,
then falls back to `uvx`, pinned to the minor range of the version that installed it (`uvx --from 'smart-commit-guard>=0.2,<0.3' ...`),
so a hook never jumps to a release that changes behaviour. `doctor` warns when the committed hook differs from the current template.

Already have a pre-commit hook (husky, lefthook, a custom one)? `install-hook --chain` (also with `--shared`) keeps it as
`pre-commit.local` next to the new hook and runs it first; if it fails, the commit stops before the scan.

Re-run `install-hook` after upgrading from 0.1, which only wrote `pre-commit`; `doctor` warns when `commit-msg` is missing.

## Sharing the hook with your team

Git does not version `.git/hooks/`, so a plain `install-hook` only protects your own clone. To share it:

```bash
smart-commit-guard install-hook --shared
git add .githooks .gitattributes && git commit -m "Add the smart-commit-guard pre-commit hook"
```

This writes `.githooks/pre-commit` (no machine-specific paths: it finds `smart-commit-guard` on `PATH`, then in the repo's
`.venv`, then through `uvx`), sets `core.hooksPath` to `.githooks`, and adds `/.githooks/* text eol=lf` to
`.gitattributes` so the script keeps LF endings on Windows. `core.hooksPath` is local git config, so **each clone
runs once**:

```bash
git config core.hooksPath .githooks     # or: smart-commit-guard install-hook --shared
```

Put that line in your setup docs or bootstrap task. A teammate without `smart-commit-guard` installed is blocked with a
message telling them how to install it (the gate fails closed rather than silently not running).

`core.hooksPath` replaces `.git/hooks/` for the clone. If you already use other hooks, call them from
`.githooks/pre-commit` or use a hook manager.

## With the pre-commit framework or as a GitHub Action

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/illescasDaniel/smart-commit-guard
    rev: v0.2.0
    hooks:
      - id: smart-commit-guard
```

```yaml
# .github/workflows/secrets.yml, step
- uses: illescasDaniel/smart-commit-guard@v0.2.0
  with:
    args: scan --no-model --diff origin/${{ github.base_ref }}...HEAD --config-from origin/${{ github.base_ref }}
```

## Testing that the hook works

Run the built-in check first:

```bash
smart-commit-guard doctor
```

It verifies that the hook exists at the effective path, is executable and runs `scan --staged`, that the hook can actually find
the tool (and which version it finds), that a shared hook is not stale, that a synthetic
secret is blocked by the rules, and that the model answers (a missing model is a warning, not a failure).

Then prove it through real git, in a throwaway repo:

```bash
cd "$(mktemp -d)" && git init -q && smart-commit-guard install-hook
K=A1b2C3d4E5f6G7h8I9j0K1l2; echo "KEY = "sk_live_$K"" > cfg.py && git add cfg.py
git commit -m test                         # blocked, exit 1
SKIP_SECRET_GUARD=1 git commit -m test     # allowed, prints SKIPPED
cat .git/secret-guard-skips.log            # the logged bypass
```
