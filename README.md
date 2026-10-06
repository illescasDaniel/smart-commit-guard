# smart-commit-guard

[![CI](https://github.com/illescasDaniel/smart-commit-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/illescasDaniel/smart-commit-guard/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/smart-commit-guard.svg)](https://pypi.org/project/smart-commit-guard/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)

Stop real secrets (API keys, passwords, private keys, tokens, connection strings) from being committed.

Deterministic rules catch the obvious cases. A small decision model judges the ambiguous ones, such as
`DB_PASS = "Winter2026!Admin"` (real) versus `API_KEY = "your-api-key-here"` (placeholder). It runs as a git
pre-commit hook and as a CI step. Zero runtime dependencies, Python 3.12+.

## Install

```bash
uv tool install smart-commit-guard      # or: pipx install smart-commit-guard
```

Or install nothing and run it through [`uvx`](https://docs.astral.sh/uv/guides/tools/), which downloads and caches it
on first use. `uvx` caches releases, so pin a range in hooks and CI:

```bash
uvx --from 'smart-commit-guard>=0.2,<0.3' smart-commit-guard doctor
```

## Quickstart

Share the gate with everyone who clones the repo (a committed `.githooks/pre-commit`, see
[Sharing the hook](#sharing-the-hook-with-your-team)). With `uvx` there is nothing to install:

```bash
uvx smart-commit-guard install-hook --shared
git add .githooks .gitattributes && git commit -m "Add the smart-commit-guard pre-commit hook"
```

The shared hook finds `smart-commit-guard` on `PATH`, then in the repo's `.venv`, then falls back to `uvx`, pinned to the
minor range of the version that installed it (`uvx --from 'smart-commit-guard>=0.2,<0.3' ...`), so a hook never jumps to a
release that changes behaviour. `doctor` warns when the committed hook differs from the current template.

Already have a pre-commit hook (husky, lefthook, a custom one)? `install-hook --chain` (also with `--shared`) keeps it as
`pre-commit.local` next to the new hook and runs it first; if it fails, the commit stops before the scan.

`install-hook` writes two hooks: `pre-commit` (the staged diff) and `commit-msg` (the message, see below). Re-run it after
upgrading from 0.1, which only wrote `pre-commit`; `doctor` warns when `commit-msg` is missing.

Or protect only your own clone: `smart-commit-guard install-hook`. Either way, check the result with
`smart-commit-guard doctor`.

### Set up a project, step by step

1. **Install the tool** (above), then **choose a model once per machine**. The default needs no setup if a local ollaya
   server runs `jevk5:4b`; otherwise write your settings file and edit it (see [Your settings file](#your-settings-file-choosing-a-model)):

   ```bash
   smart-commit-guard config init        # writes ~/.config/smart-commit-guard/config.jsonc
   smart-commit-guard config path        # where it is
   ```

2. **Add the gate to the repo**: `uvx smart-commit-guard install-hook --shared`, then commit `.githooks` and `.gitattributes`
   (see above). Everyone who clones it gets the hook after one `git config core.hooksPath .githooks`, or by running `install-hook`.
3. **Optionally add `.secret-guard.toml`** at the repo root for files to skip and findings to allow (see
   [Bypassing a false positive](#bypassing-a-false-positive)). Keep `.env` files out of git (`.gitignore`); a staged `.env` blocks.
4. **Add the CI step** below, so `--no-verify` and a missing hook still get caught.
5. **Check it**: `smart-commit-guard doctor` verifies the hooks, the rules, your settings file and that the model answers; the
   throwaway-repo test in [Testing that the hook works](#testing-that-the-hook-works) proves it through real git.

### CI

CI is the backstop: it catches `git commit --no-verify` and ignores `SKIP_SECRET_GUARD`. A GitHub Actions example
(no model in CI: rule hits block, ambiguous candidates only warn):

```yaml
name: Secret scan
on:
  push:
    branches: [main]
  pull_request:

jobs:
  smart-commit-guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0          # the diff scan needs the base branch
      - uses: astral-sh/setup-uv@v10
      - name: Scan the pull request's added lines
        if: github.event_name == 'pull_request'
        run: uvx --from 'smart-commit-guard>=0.2,<0.3' smart-commit-guard scan --no-model --diff "origin/${{ github.base_ref }}...HEAD"
      - name: Scan the whole tree
        if: github.event_name == 'push'
        run: uvx --from 'smart-commit-guard>=0.2,<0.3' smart-commit-guard scan --no-model --all
```

CI can also use the SARIF format for GitHub code scanning, `--all` instead of
`--files $(git ls-files)` (which hits the argument-length limit on large repos), and `--config-from origin/main` so a pull
request cannot change its own skip list. A GitHub Actions run prints findings as inline annotations on its own.

```yaml
      - run: uvx --from 'smart-commit-guard>=0.2,<0.3' smart-commit-guard scan --no-model --all
      - run: uvx --from 'smart-commit-guard>=0.2,<0.3' smart-commit-guard scan --no-model --diff "origin/${{ github.base_ref }}...HEAD" --config-from "origin/${{ github.base_ref }}" --format sarif > results.sarif
```

#### Commit messages

Secrets also leak through commit messages (`git commit -m "debugging with AKIA..."`), and a message is permanent once pushed.
The `commit-msg` hook runs `scan --message` on the message; for the CI backstop add `--messages` to a diff scan, which also
scans the message of every commit in the range (it catches `--no-verify`, a hook that was never installed, and the message
GitHub builds for a squash merge):

```yaml
      - run: uvx --from 'smart-commit-guard>=0.2,<0.3' smart-commit-guard scan --no-model --diff "origin/${{ github.base_ref }}...HEAD" --messages
      # a pull request title and body are not commits: pipe them in
      - run: printf '%s\n%s\n' "$TITLE" "$BODY" | uvx --from 'smart-commit-guard>=0.2,<0.3' smart-commit-guard scan --text -
        env:
          TITLE: ${{ github.event.pull_request.title }}
          BODY: ${{ github.event.pull_request.body }}
```

Messages follow different rules than code: **rule hits block** (AWS keys, tokens, private keys, connection strings), but
candidates (`the password is ...`) **only warn**, and the model is never called, because prose is too noisy to block on a score.
When a message is blocked, git keeps it in `.git/COMMIT_EDITMSG`; fix it and run `git commit -e -F .git/COMMIT_EDITMSG`. Text
below the `-v` scissors line (the diff) is not scanned as message text, comment lines are. `SKIP_SECRET_GUARD=1` skips the message
hook too, and so does `# smart-commit-guard: allow` on a line when `allow_inline = true`.

#### Hosted model in CI only

CI runs on a server your team already trusts with the code, while a commit hook runs on a laptop with work in progress. To
use a hosted model only in CI, keep the hook on rules and set the scope (the repo file can only narrow it):

```toml
# .secret-guard.toml
[model]
hosted_scope = "ci"      # the commit hook never calls a hosted model; ambiguous candidates only warn there
```

In the workflow, run the scan without `--no-model` and give it the endpoint and the key from repository secrets (CI has no settings file, so
it uses environment variables):

```yaml
      - name: Scan the pull request's added lines (hosted model)
        env:
          SECRET_GUARD_BASE_URL: ${{ secrets.SECRET_GUARD_BASE_URL }}   # https only
          SECRET_GUARD_ALLOW_HOSTED: "1"
          SECRET_GUARD_API_KEY: ${{ secrets.SECRET_GUARD_API_KEY }}
        run: uvx --from 'smart-commit-guard>=0.2,<0.3' smart-commit-guard scan --diff "origin/${{ github.base_ref }}...HEAD"
```

`scan --files` and `--all` count as CI too, even when run locally.

#### Push events

To scan what a push added instead of the whole tree, use the range from the event. For a new branch GitHub sends an all-zero
`before`; that is handled (the whole branch is scanned):

```yaml
      - run: uvx --from 'smart-commit-guard>=0.2,<0.3' smart-commit-guard scan --no-model --diff "${{ github.event.before }}...${{ github.sha }}"
```

Check out with `fetch-depth: 0`. After a force-push the old `before` commit can be gone; scan the branch against its base then.

## How it works

1. Only **added lines** are scanned. Binaries and `.env.example` are skipped. Lockfiles and generated files (`.min.js`,
   `.map`) only get the high-confidence rules below, since they can carry inlined keys or `user:token@` URLs but are too
   noisy for model candidates.
2. **High-confidence rules** (private keys, AWS keys, GitHub, GitLab, Slack, Stripe secret keys, Google, Anthropic/OpenAI-style,
   npm, PyPI, Hugging Face, SendGrid, Shopify, DigitalOcean and similar token shapes, chat webhook URLs,
   connection strings with a password) **block immediately**, with no model call, outside test/doc/example paths.
3. A staged **environment file** (`.env`, `.env.local`, `prod.env`; not `.env.example`/`.sample`/`.template`) blocks as a whole,
   with no model call, as long as it has any non-comment line. Add it to `.gitignore`, or allowlist it if intentional.
4. A staged file whose **name** marks it as sensitive blocks as a whole, with no model call, binaries included: SSH
   private keys (`id_rsa`, `id_ed25519`...), key stores (`.p12`, `.pfx`, `.jks`, `.keystore`, `.ppk`), KeePass databases,
   `.netrc`, `.pgpass`, `.pypirc`, `.htpasswd`, `.git-credentials`, `.aws/credentials`, `.docker/config.json`,
   `.kube/config`, `kubeconfig`, Terraform state and `.tfvars`, `credentials.json`, Google `client_secret*.json` and
   service-account keys, iOS provisioning profiles, `.vault-token`, `.cargo/credentials`, `.gem/credentials`,
   `.composer/auth.json` and `.config/gh/hosts.yml`. Names containing `example`, `sample`, `template` or `defaults`
   are exempt. Public files (`id_rsa.pub`, `.pem`/`.crt` certificates) are not matched by name; a private key inside
   them is still caught by content.
5. **Candidates** (`password = "..."`, `Bearer` tokens, `-pSECRET` CLI flags, unquoted YAML values, high-entropy
   literals) go to the model, one per request. Obvious placeholders (`changeme`, `your-...`, `xxxx`) are dropped first.
6. The **policy lives in code**, not in the model: the model's probability `p` blocks at `p >= 0.5` and warns at
   `p >= 0.4` (configurable).
7. If the model is unreachable: rule hits still block; model-only candidates warn and allow.

Stripe publishable keys (`pk_live_...`, `pk_test_...`) are public identifiers and are never flagged.

A base64 token that decodes to a known secret shape (a Kubernetes `Secret`, an encoded key) is reported as that rule, marked
`(base64-encoded)`.

Findings never print the secret, only a shape-preserving mask such as `sk_live_A9a9A9a9...`. Every secret on a line is
masked, and so is any other long random-looking token.

The scan does not depend on your git configuration: external diff tools, `textconv`, `diff.noprefix`/`mnemonicPrefix`,
`diff.relative` and `binary`/`-diff` attributes are overridden, so they cannot hide a file from the gate.

Exit codes: `0` allowed (warnings may print), `1` blocked by a finding, `2` tool or configuration error (an unexpected
crash is also `2`, with the details on stderr when `SMART_COMMIT_GUARD_DEBUG=1`).

## Commands

| Command | Purpose |
|---|---|
| `smart-commit-guard scan --staged` | the staged diff (what the hook runs) |
| `smart-commit-guard scan --diff RANGE` | a revision range, for CI (`origin/main...HEAD`) |
| `smart-commit-guard scan --files PATH...` | whole files (`--files -` reads NUL-separated paths from stdin) |
| `smart-commit-guard scan --all` | every tracked file (`git ls-files`) |
| `smart-commit-guard scan --message FILE` | a commit message (what the `commit-msg` hook runs); `--text -` scans stdin the same way |
| `--messages` | with `--diff`: also scan the message of every commit in the range |
| `--format text\|json\|sarif`, `--json`, `--no-model` | output format (`--json` is `--format json`); rules only (no model call) |
| `--config-from REF` | read `.secret-guard.toml` from a revision such as `origin/main`, not the working tree |
| `--baseline FILE` | ignore the findings recorded in a baseline file |
| `smart-commit-guard baseline create [-o FILE] [--no-model]` | record the current findings (default `.secret-guard-baseline.json`) |
| `smart-commit-guard allowlist migrate` | rewrite v1 fingerprints in `.secret-guard.toml` to v2 |
| `smart-commit-guard install-hook [--force]` | per-clone hook in the effective hooks directory |
| `smart-commit-guard install-hook --shared` | committable `.githooks/pre-commit` and `commit-msg` plus `core.hooksPath` |
| `smart-commit-guard install-hook --chain` | keep an existing hook as `pre-commit.local` and run it first |
| `smart-commit-guard doctor` | verify the hooks, the rules, your settings file and the model |
| `smart-commit-guard config init [--force]` / `config path` | write a commented template of your settings file / print where it is |
| `--version` | print the version |

## Your settings file: choosing a model

The model is a per-user choice, so it lives outside every repository. Run `smart-commit-guard config init` once; it writes
`~/.config/smart-commit-guard/config.jsonc` (mode 600) with the default and the hosted-model settings as comments. The file is
JSON with comments (`//` and `/* */`). `config path` prints its location: `$XDG_CONFIG_HOME/smart-commit-guard/` if set,
`%APPDATA%\smart-commit-guard\` on Windows, or the path in `SECRET_GUARD_CONFIG`. An existing `config.json` is read too.

```jsonc
{
	// The default: a local ollaya server. Nothing leaves your machine.
	"base_url": "http://localhost:11435",
	"model": "jevk5:4b"

	// A hosted model (candidate lines are sent UNMASKED: only use a server you would trust with the secrets):
	//   "base_url": "https://api.typesafe.ai",
	//   "model": "jev-latest",
	//   "allow_hosted": true,
	//   "api_key_env": "TYPESAFE_API_KEY",     // the NAME of an environment variable that holds the key
	//   "hosted_scope": "ci"                   // the commit hook never calls it; CI does
}
```

Keys: `base_url`, `model`, `api_key`, `api_key_env`, `timeout`, `allow_hosted`, `hosted_scope`, `budget`, `block_at`, `warn_at`
(same meaning as the variables below). Prefer `api_key_env` to `api_key`: the key then never sits in a file, and a file that
holds a key and is readable by others gets a warning.

**Precedence, per setting:** environment variable, then this file, then the repo's `[model]` table (model name and thresholds
only), then the default. Only this file and the environment can name a server or a key; the repo file never can, so a pull
request cannot send your diff somewhere. "Environment variable" means a real one that you export (in your shell profile, a CI
`env:` block...). **A `.env` file is never read.** (This repo's `.env` / `.env.example` are only for its own eval scripts.)

## Environment variables

Each of these overrides the same setting in your settings file.

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_GUARD_BASE_URL` | `http://localhost:11435` | model server |
| `SECRET_GUARD_MODEL` | `jevk5:4b` | model name sent to the server |
| `SECRET_GUARD_API_KEY` | unset | Bearer token, only if the server wants one |
| `SECRET_GUARD_TIMEOUT` | `10` | seconds per model call (must be > 0) |
| `SECRET_GUARD_BLOCK_AT` / `SECRET_GUARD_WARN_AT` | `0.5` / `0.4` | thresholds, see "Other models" |
| `SECRET_GUARD_ALLOW_HOSTED` | unset | must be `1` to use a non-local URL, see "Privacy"; hosted URLs must be `https` |
| `SECRET_GUARD_HOSTED_SCOPE` | `all` | `ci` keeps a hosted model out of the commit hook (`scan --staged`); `[model] hosted_scope` in `.secret-guard.toml` can only narrow it |
| `SECRET_GUARD_BUDGET` | `5` for `--staged`, `120` otherwise | total seconds of model time per scan; candidates left over only warn |
| `SECRET_GUARD_ALLOW_INSECURE` | unset | `1` allows an `http://` hosted URL on a network you fully control |
| `SMART_COMMIT_GUARD_DEBUG` | unset | `1` prints the traceback of an unexpected error |
| `SKIP_SECRET_GUARD` | unset | `1` bypasses the commit hook once, see below |

## Bypassing a false positive

Two ways, from narrowest to widest.

### 1. Allowlist the line (permanent, reviewed in PRs)

Every finding prints an `allowlist: <fingerprint>`. Put it in `.secret-guard.toml` at the repo root:

```toml
# Files to skip entirely (fnmatch globs against repo-relative paths)
skip = ["tests/fixtures/*", "docs/*"]

# Findings to accept. A fingerprint is sha256(path + masked line), so the file holds no secret
# and only matches that line shape in that file.
allowlist = ["b37018356662157b"]

# The same, with the reason reviewers see (and optionally the paths it may apply to). `reason` is required.
[[allow]]
fingerprint = "v2:3f9a1c0b7d52e864"
reason = "Fixture: a fake password used by the login tests"
path = "tests/*"

# Optional: honour `# smart-commit-guard: allow` at the end of a line (`# gitleaks:allow` and `# pragma: allowlist secret`
# are accepted too, so existing markers keep working). Off by default: it is easy to abuse (but, unlike
# SKIP_SECRET_GUARD, it is visible in review).
allow_inline = true

# Optional: where a hosted model may be used (see "Hosted model in CI only"). It can only narrow, never widen.
# `name`, `block_at` and `warn_at` set the model and thresholds for the repo (thresholds are per model); the environment
# variables win. There is deliberately no `base_url`: a pull request must not be able to choose where data goes.
[model]
hosted_scope = "ci"
# name = "jevk5:4b"
# block_at = 0.5
# warn_at = 0.4
```

`skip` and `allowlist` must be lists of strings and unknown keys are an error (exit 2), so a typo cannot silently disable
the scan. The file is read from the repository root, whatever directory you run from. A skip pattern that covers every
changed file prints a warning. In `--diff` mode a change to this file inside the range also warns, since it is part of
the diff it guards; use `--config-from origin/main` to read it from the base branch instead.

Allowlisting works for the hook and for CI.

**Fingerprints.** Printed fingerprints are `v2:` + the hash of the path and the *stripped* masked line, so re-indenting a line
does not break its entry. Plain 16-hex entries (v1, from 0.1) are still accepted for now; `smart-commit-guard allowlist migrate`
rewrites them to v2 in place (comments and layout are kept) and lists entries that no longer match anything.

### Adopting the tool on an existing repo: a baseline

```bash
smart-commit-guard baseline create            # records every current finding (masked, fingerprints only) in .secret-guard-baseline.json
git add .secret-guard-baseline.json && git commit -m "Record the secret-scan baseline"
smart-commit-guard scan --all --baseline .secret-guard-baseline.json    # fails only on findings that are not in the baseline
```

`baseline create --no-model` records rules-only results. The baseline hides the old findings, it does not fix them: rotate
anything that was real, then shrink the file.

### 2. `SKIP_SECRET_GUARD=1` (one commit, local only)

```bash
SKIP_SECRET_GUARD=1 git commit -m "..."
```

An explicit acknowledgement that a block is a false positive. Details:

- Only the exact value `1` counts (`0`, empty, `true` do not).
- It applies **only to the commit hook** (`scan --staged`). `--diff` and `--files` ignore it, so a bypassed
  commit still has to pass CI. Use an allowlist entry for a false positive that must pass CI.
- Nothing is scanned and the model is not called. A loud `SKIPPED` notice is printed.
- Every bypass is **logged** (see below).
- Do not `export` it in your shell profile; `smart-commit-guard doctor` warns if it is set.

### The skips log

Each bypass appends an entry to `secret-guard-skips.log` inside the git directory (`.git/` in a normal clone, so
it is never committed): time, branch, staged files, and what the rules would have flagged, with masked previews
and allowlist fingerprints. It never contains a secret.

```text
2026-10-05T15:15:23+00:00 SKIP branch=main files=1
  file: cfg.py
  BLOCK cfg.py:1 API token pattern (rule, no model needed) STRIPE = "sk_live_A9a9A9a9..." allowlist=b3701835...
```

The log is local and per clone, so it is for your own audit ("what did I skip, and was it really a false positive?").
The authoritative backstop is CI.

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

### With the pre-commit framework or as a GitHub Action

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

## Model setup

The default is a local model server that speaks the `POST /v1/systemone` API, with the `jevk5:4b` model (for example
ollaya serving it on port 11435). A call takes about 80 ms and the model needs about 5.5 GB of GPU memory;
commits with no candidates never call the model (about 9 in 10 commits in a replay of 486 real commits).

### Other models

Thresholds are calibrated per model. On 1,056 labelled lines that reach the model (356 real, 700 not; synthetic cases split by
template, plus real lines from 95 open-source packages), with thresholds fitted on one half and scored on the other:

| model | AUC | recall | false blocks | median call | GPU memory |
|---|---|---|---|---|---|
| `jevk5:4b` (default) | 0.998 | 0.98 | 1.6 % | 82 ms | 5.6 GB |
| `jeb:4b` | 0.994 | 0.99 | 3.6 % | 75 ms | 5.3 GB |
| `snap:2b` | 0.855 | 0.61 | 5.2 % | 43 ms | 3.1 GB |
| hosted TypeSafe `jev-latest` | 1.000 (60 lines only) | 1.00 | 0 | 242 ms | none |

At the defaults (block 0.5, warn 0.4) `jevk5:4b` has recall 0.97 and 1 % false blocks on that set. The cases are mostly synthetic, so
treat the numbers as optimistic for real code. The full report, per-model thresholds (`evals/thresholds.json`) and prompt
experiments are in [`specs/next-version/MODEL_COMPARISON.md`](specs/next-version/MODEL_COMPARISON.md). For another model, rerun
the comparison and set `block_at` / `warn_at` for it in your settings file:

```bash
uv run python evals/compare_models.py run MODEL && uv run python evals/compare_models.py report
```

### Privacy

The staged diff may contain real secrets, so the default backend is **local** and nothing is sent anywhere else.

- A non-local `SECRET_GUARD_BASE_URL` is refused (exit 2) unless `SECRET_GUARD_ALLOW_HOSTED=1`, and it must be `https`.
- **A hosted backend receives the candidate lines unmasked**: the model has to see the real value to judge it, and a masked
  value carries too little signal. Only use a hosted backend you would trust with the secrets themselves (for example a
  server you host on your own network), or limit it to CI with `SECRET_GUARD_HOSTED_SCOPE=ci`.
- Only candidate lines are sent (a window of about 300 characters around the candidate for very long lines), never whole
  files or the full diff. Lines that the rules already block are never sent.
- Local model calls ignore `HTTP_PROXY`/`HTTPS_PROXY`, so an unmasked line never goes through a corporate proxy on its way to
  `localhost`. Hosted calls honour them. Redirects are never followed.
- Everything printed (terminal, `--json`, SARIF, the skips log, allowlist fingerprints) is masked. No telemetry.

## Development

```bash
uv sync
uv run task setup-hooks   # dogfood the shared hook
uv run task test
uv run ruff check . && uv run ty check
python scripts/pin_actions.py     # pin GitHub Actions to commit SHAs (needs github.com; --check for CI)
```

Behavior is specified in [`specs/secret-scan/SPEC.md`](specs/secret-scan/SPEC.md).

## Limitations

- Scans added lines only, not git history. If a secret was committed, rotate it.
- Not a replacement for server-side scanning such as GitHub push protection; use both.
- PII detection is out of scope for now.

## License

MIT
