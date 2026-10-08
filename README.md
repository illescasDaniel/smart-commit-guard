# smart-commit-guard

[![CI](https://github.com/illescasDaniel/smart-commit-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/illescasDaniel/smart-commit-guard/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/smart-commit-guard.svg)](https://pypi.org/project/smart-commit-guard/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)

Stop real secrets (API keys, passwords, private keys, tokens, connection strings) from being committed.

Deterministic rules catch the obvious cases. A small decision model judges the ambiguous ones, such as
`DB_PASS = "Winter2026!Admin"` (real) versus `API_KEY = "your-api-key-here"` (placeholder). It runs as a git
pre-commit hook and as a CI step. Zero runtime dependencies, Python 3.12+.

## Quickstart

Four steps. Steps 1 to 3 are once per machine; 3 is once per repository.

**1. Pick a model.** The default is a **local** model, `jevk5:4b`, served by ollaya at `http://localhost:11435`: run
`ollaya pull jevk5:4b` and `ollaya serve`, and nothing else is needed (or set `"autostart": true` in your settings file and the hook starts `ollaya serve` itself when it needs the model). You can use a **hosted** model instead (for example
TypeSafe Jev), or no model at all (rules only). How to set up each: [docs/models.md](docs/models.md).

**2. Install the tool**, or run it without installing through [`uvx`](https://docs.astral.sh/uv/guides/tools/) (pin a range in hooks and CI,
since `uvx` caches releases):

```bash
uv tool install smart-commit-guard      # or: pipx install smart-commit-guard
uvx --from 'smart-commit-guard>=0.3,<0.4' smart-commit-guard doctor      # no install
```

**3. Write your settings file** (which model to use; it lives outside the repos, in `~/.config/smart-commit-guard/config.jsonc`),
then check that everything answers:

```bash
smart-commit-guard config init      # a commented template: the local default, and the hosted settings as comments
smart-commit-guard doctor           # hooks, rules, settings file and model
```

With the default local model you can skip `config init`; `doctor` still tells you whether the model answers.

**4. Add the git hooks to a repository.** A committed `.githooks/` gives everyone who clones the repo the gate:

```bash
smart-commit-guard install-hook --shared         # or uvx smart-commit-guard install-hook --shared
git add .githooks .gitattributes && git commit -m "Add the smart-commit-guard hooks"
```

Or protect only your own clone with `smart-commit-guard install-hook`. It writes a `pre-commit` hook (the staged diff) and a
`commit-msg` hook (the message). Details, an existing hook (`--chain`) and a throwaway-repo test: [docs/hooks.md](docs/hooks.md).

**Optional, per repository:**
- `.secret-guard.toml`: files to skip, findings to allow, a baseline for an existing repo: [docs/project-config.md](docs/project-config.md).
- CI, the backstop for `--no-verify` (GitHub Actions, SARIF, commit messages, a hosted model in CI): [docs/ci.md](docs/ci.md).

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

## More

| | |
|---|---|
| [docs/models.md](docs/models.md) | local and hosted models, the settings file, environment variables, other models, privacy |
| [docs/hooks.md](docs/hooks.md) | the shared hook, `--chain`, the pre-commit framework, testing the hook |
| [docs/project-config.md](docs/project-config.md) | `.secret-guard.toml`, allowlist, baseline, `SKIP_SECRET_GUARD`, the skips log |
| [docs/ci.md](docs/ci.md) | GitHub Actions, SARIF, commit messages, hosted model in CI, push events |
| [specs/secret-scan/SPEC.md](specs/secret-scan/SPEC.md) | the behaviour contract |
| [specs/next-version/MODEL_COMPARISON.md](specs/next-version/MODEL_COMPARISON.md) | model comparison report |

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
