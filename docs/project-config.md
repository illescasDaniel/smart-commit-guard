# Project configuration: skips, allowlist, baseline, bypasses

Everything a repository can say about itself lives in `.secret-guard.toml` at its root. Which model runs is **not** here: that is a per-user choice, see [Choosing a model](models.md). Back to the [README](../README.md).

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

# Optional: where a hosted model may be used (see docs/ci.md, "Hosted model in CI only"). It can only narrow, never widen.
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

## Adopting the tool on an existing repo: a baseline

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
- Every bypass is **logged** (see [The skips log](#the-skips-log)).
- Do not `export` it in your shell profile; `smart-commit-guard doctor` warns if it is set.

## The skips log

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
