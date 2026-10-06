# Changelog

## Unreleased

- Per-user settings file `~/.config/smart-commit-guard/config.jsonc` (JSON with comments): choose the model server, model, key (or `api_key_env`), thresholds and hosted opt-in once for every repo. `smart-commit-guard config init` writes a commented template with `jevk5:4b` as the default and hosted-model instructions. Environment variables still win; `doctor` reports the file.
- Stripe publishable keys (`pk_live_...`, `pk_test_...`) are public identifiers and are no longer flagged. Secret and restricted keys (`sk_`, `rk_`) still block.
- Evals: generated and open-source case sets, `compare_models.py` (AUC, bootstrap intervals, latency, GPU memory), `experiments.py` (prompt variants), per-model `evals/thresholds.json`. `.env` is gitignored.

## 0.2.0 - 2026-10-05

Printed allowlist fingerprints are now `v2:...` (hash of the stripped line); v1 entries keep working, and
`smart-commit-guard allowlist migrate` rewrites them. Fingerprints change for lines that have a second secret or another long random-looking token (the preview now masks
them), and for paths with non-ASCII or special characters (they are now spelled as git stores them). Re-run the scan and
update `.secret-guard.toml` if a previously allowlisted finding comes back.

### Fixed (silent bypasses, leaks, crashes)
- A user's git config can no longer make the scan see nothing: `diff.external`, `textconv`, `binary` / `-diff` attributes,
  `diff.mnemonicPrefix`, `diff.noprefix` and `diff.relative` are overridden (new `git.py`).
- Non-ASCII and special file names (`café.py`, names with quotes, tabs or backslashes) are decoded; skip globs, file-name rules and
  fingerprints see the real name. A file renamed to a sensitive name (`config.json` -> `.env`) is caught.
- Non-UTF-8 files no longer crash the tool (which exited 1, "blocked"). Any unexpected error now exits 2; exit 1 only ever means a finding.
- `skip = "tests/*"` (a string) used to skip every file. `.secret-guard.toml` is now validated: wrong types and unknown keys exit 2.
- The model call ignores `HTTP_PROXY` for loopback URLs (the unmasked line used to reach a corporate proxy) and never follows redirects.
- A second secret on the same line was printed in clear, and a placeholder earlier on a line hid a real secret after it. All hits on a line are found and masked.
- The model saw only the first 300 characters of a line. It now gets a window centred on the candidate.
- `.secret-guard.toml` is read from the repo root, and `--files` paths are normalised, so skip globs and allowlist fingerprints agree between local and CI runs.
- `SECRET_GUARD_TIMEOUT=0` is refused.

### Changed
- During a merge (`MERGE_HEAD` exists) the staged scan covers only lines that are new against every parent: conflict resolutions and hand edits are scanned, lines brought in from the other branch are not rescanned.
- A weak password that merely starts with a placeholder word (`DB_PASSWORD = "Password123!"`) now goes to the model instead of being dropped; a bare `password` / `token` / `secret` / `key` (or `wrong-password`, `password123`) is still a placeholder.
- `.svg`, Xcode scheme / test plan / project files and checksum lists (`*checksums*.json`, `SHA256SUMS`, `*.sha256`) get the rules only: replaying 486 real commits showed them as the top source of model calls (element ids, build ids, sha256 lists).
- Files git calls binary and that are over 256 KiB are excluded from the diff up front (a `--numstat` pre-pass), whatever their suffix: a 5,000-file staged change with 450 MB of `.dat` / `.bin` blobs spent most of its time reading them. Small files marked `binary` in `.gitattributes` are still scanned.
- **The model receives the unmasked candidate line in every mode** (masked text told it every input was a non-secret). Masking stays for everything printed or logged. A hosted backend therefore receives candidate lines: use one you trust with the secrets themselves. Hosted URLs must be `https`.
- Lockfiles and generated files (`.min.js`, `.map`) get the high-confidence rules instead of being skipped entirely.
- `--diff` takes a revision range (`A..B` or `A...B`); a single revision is rejected.
- Renames are not detected in scans, so a renamed file's content is scanned as added.

### Added
- `SECRET_GUARD_HOSTED_SCOPE=ci` / `[model] hosted_scope = "ci"`: use a hosted model in CI but not in the commit hook.
- `SECRET_GUARD_BUDGET` (total model seconds per scan), identical candidates judged once.
- Many more token shapes (GitHub fine-grained, Anthropic, Stripe webhook, Slack app, Google OAuth, GitLab, SendGrid, PyPI, npm, Shopify, DigitalOcean, Doppler, Hugging Face, Telegram, Azure storage, PGP private keys), JWT and `.npmrc` candidates, more sensitive file names.
- Fewer false positives: `sk-learn-contrib-projects`, UUIDs, hex digests on hash lines, slash-separated words.
- `scan --all`, `--files -`, `--format sarif`, GitHub Actions annotations, `--config-from REF`, a warning when the config changes inside a scanned range, `--version`, a size cap and binary detection for `--files`.
- `[[allow]]` entries in `.secret-guard.toml` (`fingerprint`, a required `reason`, optional `path` glob), and an opt-in inline pragma (`allow_inline = true`, then `# smart-commit-guard: allow` on a line).
- `baseline create` and `scan --baseline FILE`: adopt the tool on an existing repo and fail on new findings only.
- Fingerprint v2 and `allowlist migrate`.
- `install-hook --chain`: keep an existing hook as `pre-commit.local` and run it first.
- **Commit-message scanning**: a `commit-msg` hook (`scan --message FILE`) refuses a commit whose message contains a secret (rule hits block, candidates only warn, no model), `scan --diff A..B --messages` scans every message in a range for CI and squash merges, and `scan --text -` scans stdin (PR title and body). `install-hook` now writes both hooks (with `--shared` and `--chain`), and `doctor` warns when `commit-msg` is missing. Re-run `install-hook` after upgrading.
- Base64 decoding: a token that decodes to a known secret shape (Kubernetes `Secret`, encoded key) is found and marked `(base64-encoded)`. Sequential and repeated values are placeholders. `gitleaks:allow` and `pragma: allowlist secret` work as inline markers when `allow_inline = true`.
- `[model] name / block_at / warn_at` in `.secret-guard.toml` (environment wins; never `base_url`).
- Push ranges: an all-zero `before` scans the whole branch; a missing base revision explains `fetch-depth: 0`.
- `doctor` checks that the hook can find the tool and which version it finds, and warns about a stale shared hook; the shared hook's `uvx` fallback is pinned to the minor range.
- The release workflow creates the GitHub release with the CHANGELOG notes (`scripts/release_notes.py`).
- `scripts/pin_actions.py` pins GitHub Actions to commit SHAs (`--check` for CI).
- `.pre-commit-hooks.yaml` for the pre-commit framework and a composite GitHub Action (`action.yml`).
- Eval cases record the stage that decides them, and a unit test checks it without a model (`tests/unit/test_eval_cases.py`).
