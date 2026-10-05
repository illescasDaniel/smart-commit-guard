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

## Quickstart

```bash
smart-commit-guard install-hook          # this clone only: writes .git/hooks/pre-commit
smart-commit-guard doctor                # checks the hook, the rules and the model
```

To share the hook with everyone who clones the repo, see [Sharing the hook](#sharing-the-hook-with-your-team).

Add a CI step too: it catches `git commit --no-verify` and cannot be bypassed with `SKIP_SECRET_GUARD`.

```bash
smart-commit-guard scan --diff origin/main...HEAD
```

## How it works

1. Only **added lines** are scanned. Lockfiles, binaries, minified files and `.env.example` are skipped.
2. **High-confidence rules** (private keys, AWS keys, `sk-`/`ghp_`/`xox`/`AIza`/`glpat-` tokens, chat webhook URLs,
   connection strings with a password) **block immediately**, with no model call, outside test/doc/example paths.
3. A staged **environment file** (`.env`, `.env.local`, `prod.env`; not `.env.example`/`.sample`/`.template`) blocks as a whole,
   with no model call, as long as it has any non-comment line. Add it to `.gitignore`, or allowlist it if intentional.
4. A staged file whose **name** marks it as sensitive blocks as a whole, with no model call, binaries included: SSH
   private keys (`id_rsa`, `id_ed25519`...), key stores (`.p12`, `.pfx`, `.jks`, `.keystore`, `.ppk`), KeePass databases,
   `.netrc`, `.pgpass`, `.pypirc`, `.htpasswd`, `.git-credentials`, `.aws/credentials`, `.docker/config.json`,
   `.kube/config`, `kubeconfig`, Terraform state and `.tfvars`, `credentials.json`, Google `client_secret*.json` and
   service-account keys, and iOS provisioning profiles. Names containing `example`, `sample`, `template` or `defaults`
   are exempt. Public files (`id_rsa.pub`, `.pem`/`.crt` certificates) are not matched by name; a private key inside
   them is still caught by content.
5. **Candidates** (`password = "..."`, `Bearer` tokens, `-pSECRET` CLI flags, unquoted YAML values, high-entropy
   literals) go to the model, one per request. Obvious placeholders (`changeme`, `your-...`, `xxxx`) are dropped first.
6. The **policy lives in code**, not in the model: the model's probability `p` blocks at `p >= 0.5` and warns at
   `p >= 0.4` (configurable).
7. If the model is unreachable: rule hits still block; model-only candidates warn and allow.

Findings never print the secret, only a shape-preserving mask such as `sk_live_A9a9A9a9...`.

Exit codes: `0` allowed (warnings may print), `1` blocked, `2` tool error.

## Commands

| Command | Purpose |
|---|---|
| `smart-commit-guard scan --staged` | the staged diff (what the hook runs) |
| `smart-commit-guard scan --diff RANGE` | a revision range, for CI (`origin/main...HEAD`) |
| `smart-commit-guard scan --files PATH...` | whole files |
| `--json`, `--no-model` | machine-readable output; rules only (no model call) |
| `smart-commit-guard install-hook [--force]` | per-clone hook in the effective hooks directory |
| `smart-commit-guard install-hook --shared` | committable `.githooks/pre-commit` plus `core.hooksPath` |
| `smart-commit-guard doctor` | verify the hook, the rules and the model |

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_GUARD_BASE_URL` | `http://localhost:11435` | model server |
| `SECRET_GUARD_MODEL` | `jevk5:4b` | model name sent to the server |
| `SECRET_GUARD_API_KEY` | unset | Bearer token, only if the server wants one |
| `SECRET_GUARD_TIMEOUT` | `10` | seconds per model call |
| `SECRET_GUARD_BLOCK_AT` / `SECRET_GUARD_WARN_AT` | `0.5` / `0.4` | thresholds, see "Other models" |
| `SECRET_GUARD_ALLOW_HOSTED` | unset | must be `1` to use a non-local URL, see "Privacy" |
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
```

Allowlisting works for the hook and for CI.

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

## Testing that the hook works

Run the built-in check first:

```bash
smart-commit-guard doctor
```

It verifies that the hook exists at the effective path, is executable and runs `scan --staged`, that a synthetic
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

The default is a local model server that speaks the `POST /v1/systemone` API, with the `jevk5:4b` model
(for example ollaya serving `jevk5:4b` on port 11435). Typical latency is
about 70 ms per candidate. Commits with no candidates never call the model.

### Other models

Thresholds are calibrated per model. The defaults come from `evals/` (tuning and held-out sets, synthetic only):
recall and precision 1.00 at block 0.5 / warn 0.4 for `jevk5:4b`. Those sets are small and the rules were adjusted
after seeing the first held-out misses, so treat the numbers as optimistic. For another model, rerun the eval and
choose your own thresholds:

```bash
PYTHONPATH=src uv run python evals/run_eval.py
```

### Privacy

The staged diff may contain real secrets, so the default backend is **local** and nothing is sent anywhere else.
A non-local `SECRET_GUARD_BASE_URL` is refused (exit 2) unless `SECRET_GUARD_ALLOW_HOSTED=1`. With a hosted backend
only **masked** lines are sent, never the secret value, a full file or the unmasked diff. No telemetry.

## Development

```bash
uv sync
uv run task setup-hooks   # dogfood the shared hook
uv run task test
uv run ruff check . && uv run ty check
```

Behavior is specified in [`specs/secret-scan/SPEC.md`](specs/secret-scan/SPEC.md).

## Limitations

- Scans added lines only, not git history. If a secret was committed, rotate it.
- Not a replacement for server-side scanning such as GitHub push protection; use both.
- PII detection is out of scope for now.

## License

MIT
