# Spec: secret-scan (secret-guard CLI)

Status: **Approved**, with two later amendments pending re-approval: one candidate per model request, and
calibrated default thresholds (see the Eval results section).

## Goal
Stop real secrets (API keys, passwords, private keys, tokens, connection strings with passwords) from being committed.
Deterministic rules catch the obvious cases. A small decision model judges the ambiguous cases (real credential versus
placeholder, mock or env reference). The tool is a CLI for a git pre-commit hook and for CI.

## Design decisions
### Success criteria
- On the labelled eval set (synthetic only): recall on real secrets >= 0.95 and false-block rate on placeholders <= 0.05
  at the chosen thresholds, for the configured model. Thresholds are per model and come from the eval, not from this spec.
- A staged commit with no candidates adds < 100 ms (no model call).
- Exit code is a pure function of the scan result: 0 = commit allowed (warnings may print), 1 = blocked, 2 = tool error
  (never silently 0 for a block).

### Trust boundary
- The staged diff may contain real secrets. **Default backend is local**: a model server on `localhost` or a
  user-chosen URL. Nothing is sent to a hosted API unless `SECRET_GUARD_ALLOW_HOSTED=1` is set.
- With a hosted backend, only **redacted** snippets are sent: each candidate value is replaced by a mask that keeps shape
  (length class, character classes, known prefix) but not content. Full files and the unmasked diff are never sent.
- Findings output never prints the full secret: show the file, line, rule and a masked preview.
- The model client sends no data anywhere but the configured base URL. No telemetry.

### Failure handling
| Situation | Result |
|---|---|
| High-confidence rule hit (e.g. `-----BEGIN PRIVATE KEY-----`, AWS key) outside test/example paths | **Block**; no model call |
| Rule hit in test/fixture/doc/example path | Ask the model; block only at p >= block threshold |
| No rule hit but secret-looking name or high-entropy literal | Ask the model; block at p >= block threshold, warn between warn and block thresholds |
| Model unreachable, times out or returns a malformed or incomplete answer | Rule hits still **block**; model-only candidates **warn and allow** (never treat a missing answer as a pass for a rule hit) |
| Not a git repo, or git fails | Exit 2 with a message |
| Binary file, lockfile, generated file, `.env.example` | Skipped |

**Rule hit vs candidate (clarification).** Only *high-confidence* rules (private keys, AWS keys, token prefixes, URLs with a
password) block without the model. Credential-assignment (`password = "..."`) and high-entropy literals are
*candidates*: judged by the model, and warn-and-allow when it is unavailable.

**Allowlist fingerprint** = hash of the path plus the line with the secret replaced by its mask, so it only matches that line shape.

### Performance and resource budget
- Rules plus candidate extraction: O(added lines), single pass.
- Model calls: **one candidate per request** (measured with `jevk5:4b`: the score of a line depends heavily on its
  position in a batch, e.g. 0.87 as `items[0]` versus 0.37 as `items[1]`; alone it is accurate and not slower per item,
  ~145 ms). Candidate text capped at 300 characters, at most 30 candidates judged per scan. Beyond the cap the remainder is
  reported as "unjudged" (warn).
- Per-call timeout default 10 s (`SECRET_GUARD_TIMEOUT`). Target median hook time <= 1 s with a local model.

### Configuration
Env vars: `SECRET_GUARD_BASE_URL`, `SECRET_GUARD_MODEL`, `SECRET_GUARD_API_KEY` (only if the server wants one),
`SECRET_GUARD_TIMEOUT`, `SECRET_GUARD_ALLOW_HOSTED`, `SECRET_GUARD_BLOCK_AT`, `SECRET_GUARD_WARN_AT`.
Optional `.secret-guard.toml` in the repo root: extra skip globs, allowlisted fingerprints (hash of the masked finding, so
the allowlist itself holds no secret).

### Model protocol
`POST {base_url}/v1/systemone` (Bearer auth when an API key is set) with `state` (`items`: `path`, `line`), optional `model`,
and `questions` of type `noul`: `instructions` plus optional `criteria` (`true` / `false` text, as the SDK schema allows).
Answers are read from `answers[<key>].noul`. A missing or non-noul answer is a failure (see table).

## CLI
- `secret-guard scan --staged` | `--diff <range>` | `--files <paths...>`; `--json`; `--no-model` (rules only).
- `secret-guard install-hook` writes a `pre-commit` hook that runs `scan --staged` (refuses to overwrite an existing hook
  without `--force`).
- Intended for a git pre-commit hook and a CI step (the CI run covers `git commit --no-verify`).

## BDD
- **Given** a staged line `AWS_KEY = "AKIA...16 chars"` in `src/app.py`, **when** scanning, **then** exit 1 and the
  finding shows a masked preview, with no model call.
- **Given** `API_KEY = "your-api-key-here"` in `README.md` and the model answers p=0.03, **then** exit 0.
- **Given** `DB_PASS = "Winter2026!Admin"` (no rule hit) and the model answers p=0.92 (>= block), **then** exit 1.
- **Given** a model-only candidate with p=0.6 (between warn and block), **then** exit 0 and a warning is printed.
- **Given** the model is unreachable and a rule hit exists, **then** exit 1; **and given** only a model-only candidate,
  **then** exit 0 with a warning that the model was unavailable.
- **Given** a hosted base URL and no `SECRET_GUARD_ALLOW_HOSTED`, **then** exit 2 and nothing is sent.
- **Given** a hosted backend with opt-in, **then** the request body contains the masked value and not the original.
- **Given** a changed `package-lock.json`, **then** it is skipped.
- **Given** an allowlisted fingerprint, **then** that finding is not reported.
- **Given** a removed line (`-`) containing a secret, **then** it is ignored (only added lines are scanned).

## Out of scope (v1)
- Scanning git history, or secret rotation or revocation.
- PII detection beyond credentials.
- An MCP server, a Claude Code `PreToolUse` wrapper, and any shared `decision-core` package (later, if wanted).
- Auto-fixing or rewriting files.
- Training or tuning the model.

## Eval results (2026-10-05, `jevk5:4b` via ollaya, RTX 4070 laptop GPU)
Data: `evals/cases_tune.json` (66 lines, 25 real) and `evals/cases_holdout.json` (42 lines, 16 real), synthetic only.
Reproduce: `PYTHONPATH=src uv run python evals/run_eval.py` (needs `ollaya serve` with `jevk5:4b`).

Findings that changed the design:
- **Batching hurts this model.** The same line scored 0.87 as `items[0]` and 0.37 as `items[1]`; real secrets in a batch of
  6 scored 0.74-0.96 versus 0.88-0.98 alone, with no per-item speed gain. Hence one candidate per request.
- **Rule gaps capped recall.** The first rule set never surfaced 7 of 41 real secrets (unquoted YAML/compose values, prose,
  `Bearer` headers, `Password=` in connection strings, `mysql -p`, chat webhook URLs). Fixed; 0 unsurfaced afterwards.
- **Obvious placeholders** (`your-...`, `changeme`, `xxxx`, `test-...`) are dropped before the model.

Defaults chosen: **block at p >= 0.5, warn at p >= 0.4**. At those thresholds: tuning set recall 1.00, precision 1.00;
held-out set recall 1.00, precision 1.00 (0 false blocks, 0 missed). Model-judged scores: real secrets 0.68-0.98, placeholders
0.02-0.36 (tuning set had one 0.80 placeholder before the URL fix). Median 70 ms per call.

Caveats: the rules and placeholder filter were tuned on the tuning set and adjusted after seeing the first held-out gaps, so
the held-out numbers are optimistic. The sets are small and synthetic. Other models must rerun the eval and pick their own
thresholds. Real-repo check: SpaceMaker (whole tree) 0 findings; jev-mem 3 blocks and 1 warn, all deliberate fake secrets in
its own tests, eval data and CI config (scores 0.54-0.78, i.e. close to the threshold).
