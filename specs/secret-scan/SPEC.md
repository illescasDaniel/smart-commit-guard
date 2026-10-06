# Spec: secret-scan (smart-commit-guard CLI)

Status: **Approved** (including the one-candidate-per-request and calibrated-threshold amendments, 2026-10-05, and the
`SKIP_SECRET_GUARD` bypass; skips log, `doctor` and `install-hook --shared` added 2026-10-05 at the user's request).
Amended for 0.2 (2026-10-05, see `specs/next-version/PLAN.md`): trust boundary, hosted scope, safe git invocation, config validation.

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
- The model receives the **same unmasked candidate line in every mode**, local or hosted: a masked value is a non-secret by
  the model's own criteria and carries too little signal to judge. Choosing a hosted backend (`SECRET_GUARD_ALLOW_HOSTED=1`,
  `https` only) is an explicit consent to send candidate lines, which may contain real secrets, to it.
- Only candidate lines are sent (a window of about 300 characters centred on the candidate for long lines), never other
  lines, whole files or the full diff. A line a rule already blocks is never sent.
- `SECRET_GUARD_HOSTED_SCOPE=ci` (or `[model] hosted_scope = "ci"` in the repo file) keeps a hosted model out of
  `scan --staged`: there, model-only candidates warn as if the model were unavailable and rule hits still block. The repo
  file can only narrow the scope; the most restrictive of file and environment wins. A loopback URL is never affected.
- Local (loopback) model calls bypass `HTTP_PROXY`/`HTTPS_PROXY`; no call follows a redirect.
- Findings output never prints the full secret: show the file, line, rule and a masked preview. Every hit on the line is
  masked, plus any other token of 16+ characters with letters, digits and entropy above 3.0. This holds for the terminal,
  `--json`, SARIF, the skips log and allowlist fingerprints.
- The model client sends no data anywhere but the configured base URL. No telemetry.

### Failure handling
| Situation | Result |
|---|---|
| High-confidence rule hit (e.g. `-----BEGIN PRIVATE KEY-----`, AWS key) outside test/example paths | **Block**; no model call |
| Rule hit in test/fixture/doc/example path | Ask the model; block only at p >= block threshold |
| No rule hit but secret-looking name or high-entropy literal | Ask the model; block at p >= block threshold, warn between warn and block thresholds |
| Model unreachable, times out or returns a malformed or incomplete answer | Rule hits still **block**; model-only candidates **warn and allow** (never treat a missing answer as a pass for a rule hit) |
| `SKIP_SECRET_GUARD=1` and `scan --staged` | Nothing is scanned (no model call); prints a loud `SKIPPED` notice on stderr; exit 0; an entry is appended to `secret-guard-skips.log` in the git dir (rules-only, masked, best effort: a log failure never blocks) |
| `SKIP_SECRET_GUARD=1` with `--diff` or `--files` | Ignored: CI and explicit scans cannot be skipped this way |
| Not a git repo, or git fails | Exit 2 with a message |
| Any unexpected exception, an invalid `.secret-guard.toml` (wrong type, unknown key, bad scope) or an invalid setting (`SECRET_GUARD_TIMEOUT <= 0`, bad scope, hosted URL that is not `https`) | Exit 2 with a one-line message (`--json` prints `{"exit_code": 2, "error": ...}`); exit 1 only ever means a finding blocked |
| `SECRET_GUARD_HOSTED_SCOPE=ci` (env or repo file), hosted URL, `scan --staged` | The model is not called; model-only candidates warn (reported as `model_skipped: "hosted_scope"` in `--json`, with a note on stderr); rule hits still block |
| The model time budget (`SECRET_GUARD_BUDGET`) runs out | The candidates not yet judged warn as "not judged by the model" |
| A diff scan where `.secret-guard.toml` changes in the range | Warning on stderr; `--config-from REF` reads the config from a trusted revision |
| Environment file (`.env`, `.env.*`, `*.env`, not `.example`/`.sample`/`.template`/`.dist`/`.defaults`) with at least one non-blank, non-comment added line | **Block**, one finding per file (no model, contents not printed); allowlist it or add the path to `skip` if intentional |
| Sensitive file name (SSH private keys, key stores such as `.p12`/`.pfx`/`.jks`/`.keystore`/`.ppk`, `.kdbx`, `.netrc`, `.pgpass`, `.pypirc`, `.htpasswd`, `.git-credentials`, `.aws/credentials`, `.docker/config.json`, `.kube/config`, Terraform state and `.tfvars`, `credentials.json`, Google client-secret and service-account JSON, `.mobileprovision`; template names exempt) | **Block** by name, one finding per file, binaries included (checked from the changed-file list, not only text lines); same allowlist/`skip` escape |
| Binary file (by suffix, or NUL bytes), `.env.example` | Skipped |
| Lockfile, generated file (`.min.js`, `.min.css`, `.map`) | High-confidence rules only; no candidates, no model |

**Commit messages.** The `commit-msg` hook runs `scan --message FILE`: every line above git's scissors line (`# ---- >8 ----`,
which `commit -v` appends the diff below) is scanned, comment lines included, as the pseudo-file `COMMIT_EDITMSG`. Rule hits block
(exit 1, with a hint to recover the message from `COMMIT_EDITMSG`); candidates only warn and the model is never called, so a model
or hosted-model configuration problem cannot refuse a commit. `scan --diff A..B --messages` scans the message of every commit in
the range (`commit <sha>`; an all-zero base means the whole branch); `scan --text -` scans stdin as a message (PR title and body).
`SKIP_SECRET_GUARD=1` skips the message scan with a notice (the pre-commit hook already logged the skip). `install-hook` installs
both hooks, checking every target before writing any, with the same `--shared` and `--chain` behaviour for each.

**Git invocation.** Every diff is read with the user's diff configuration overridden (no external diff, no textconv, `a/` and
`b/` prefixes, no relative paths, no rename detection, `--text` so `binary` / `-diff` attributes cannot hide a file, binary
suffixes excluded from the pathspec), decoded as UTF-8 whatever the locale, with C-quoted paths decoded. A user's git config
must never change what is scanned.

**Rule hit vs candidate (clarification).** Only *high-confidence* rules (private keys, AWS keys, token prefixes, URLs with a
password) block without the model. Credential-assignment (`password = "..."`) and high-entropy literals are
*candidates*: judged by the model, and warn-and-allow when it is unavailable.

**Allowlist fingerprint** = hash of the path plus the line with the secret replaced by its mask, so it only matches that line shape.
v2 (printed, `v2:` + 16 hex) hashes the *stripped* masked line, so re-indenting does not break an entry; v1 (16 hex, whole line)
is still accepted. `allowlist migrate` rewrites v1 entries to v2 in `.secret-guard.toml`. `[[allow]]` entries carry a required
`reason` and an optional `path` glob (the entry then only applies to matching paths). With `allow_inline = true`, a line
containing `smart-commit-guard: allow` is not scanned (sensitive file names are not affected). A baseline file (`baseline create`,
`scan --baseline`) is a list of v2 fingerprints that are ignored, to adopt the tool on an existing repo.

### Performance and resource budget
- Rules plus candidate extraction: O(added lines), single pass.
- Model calls: **one candidate per request** (measured with `jevk5:4b`: the score of a line depends heavily on its
  position in a batch, e.g. 0.87 as `items[0]` versus 0.37 as `items[1]`; alone it is accurate and not slower per item,
  ~145 ms). Candidate text is a window of about 300 characters centred on the candidate, at most 30 distinct candidates
  judged per scan (identical lines are judged once). Beyond the cap the remainder is reported as "unjudged" (warn).
- Per-call timeout default 10 s (`SECRET_GUARD_TIMEOUT`, must be > 0). Total model time per scan is bounded by
  `SECRET_GUARD_BUDGET` (default 5 s for `--staged`, 120 s otherwise); what is left over warns as "unjudged".
  Target median hook time <= 1 s with a local model.

### Configuration
The same settings can live in the user's `~/.config/smart-commit-guard/config.jsonc` (JSON with `//` comments; keys `base_url`, `model`, `api_key`, `api_key_env`, `timeout`, `allow_hosted`, `hosted_scope`, `budget`, `block_at`, `warn_at`). Precedence per setting: environment variable, then that file, then the repo's `[model]` table (name and thresholds only), then the default. Only the user file and the environment may choose a server or key. A `.env` file is never read.

Env vars: `SECRET_GUARD_BASE_URL`, `SECRET_GUARD_MODEL`, `SECRET_GUARD_API_KEY` (only if the server wants one),
`SECRET_GUARD_TIMEOUT`, `SECRET_GUARD_ALLOW_HOSTED`, `SECRET_GUARD_ALLOW_INSECURE`, `SECRET_GUARD_HOSTED_SCOPE`,
`SECRET_GUARD_BUDGET`, `SECRET_GUARD_BLOCK_AT`, `SECRET_GUARD_WARN_AT`, `SMART_COMMIT_GUARD_DEBUG`.

**Bypass:** `SKIP_SECRET_GUARD=1 git commit -m "..."` is an explicit acknowledgement that a block is a false positive. Only
the exact value `1` counts, only for `scan --staged` (the commit hook). It is not honored for `--diff` (CI), so a
bypassed commit still has to pass CI; a false positive that must pass CI gets an allowlist entry in `.secret-guard.toml`.
Optional `.secret-guard.toml` in the repo root (found from any directory; `--files` paths are normalised to repo-relative
POSIX paths first): extra skip globs, allowlisted fingerprints (hash of the masked finding, so the allowlist itself holds no
secret), and `[model]` (`hosted_scope`, `name`, `block_at`, `warn_at`; the environment wins; never `base_url`). `skip` and `allowlist` must be lists of strings; unknown keys are an error. Hosted URLs
come only from the environment, never from this committed file.

### Model protocol
`POST {base_url}/v1/systemone` (Bearer auth when an API key is set) with `state` (`items`: `path`, `line`), optional `model`,
and `questions` of type `noul`: `instructions` plus optional `criteria` (`true` / `false` text, as the SDK schema allows).
Answers are read from `answers[<key>].noul`. A missing or non-noul answer is a failure (see table).

## CLI
- `smart-commit-guard scan --staged` | `--diff <range>` (a range with `..`; a single revision is rejected) | `--files <paths...>`
  (`-`: NUL-separated paths on stdin) | `--all` (every tracked file); `--format text|json|sarif` (`--json` is an alias; text adds
  GitHub Actions annotations when `GITHUB_ACTIONS=true`); `--no-model` (rules only); `--config-from REF`.
- `smart-commit-guard --version`; `scan --baseline FILE`; `baseline create [-o FILE] [--no-model]`; `allowlist migrate`.
- `smart-commit-guard doctor` checks the hook (exists at the effective hooks path, executable, runs `scan --staged`), that rules block a
  synthetic secret, and that the model answers. Exit 1 only for a missing or broken hook, broken rules or invalid config; an
  unreachable model or an exported `SKIP_SECRET_GUARD` is a warning.
- `smart-commit-guard install-hook --shared` writes a committable `.githooks/pre-commit` (no machine-specific paths), sets
  `core.hooksPath=.githooks` and adds `/.githooks/* text eol=lf` to `.gitattributes`; refuses to replace a different
  `core.hooksPath` or an existing hook without `--force`.
- `install-hook [--shared] --chain` keeps an existing hook that is not ours as `pre-commit.local` (same directory) and the new hook
  runs it first, stopping the commit if it fails.
- `smart-commit-guard install-hook` writes a `pre-commit` hook that runs `scan --staged` (refuses to overwrite an existing hook
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
- **Given** a hosted backend with opt-in, **then** the request body contains only the candidate line as written, not other
  lines or files; **and given** an `http://` hosted URL, **then** exit 2.
- **Given** `SECRET_GUARD_HOSTED_SCOPE=ci` and a hosted URL, **when** scanning staged, **then** the model is not called, a
  candidate warns (exit 0), a rule hit still blocks, and a note says why; **and given** `--diff` or `--files` **then** the model judges.
- **Given** repo scope `ci` and environment scope `all`, **then** the scope is `ci`.
- **Given** a changed `package-lock.json` with an AWS key, **then** it blocks; **and given** only candidates in it, **then** nothing is reported.
- **Given** `diff.external`, a `binary` attribute, `diff.mnemonicPrefix` or `diff.relative` in the user's git config, **then** a staged secret still blocks, with a plain repo-relative path.
- **Given** a staged file named `café.py`, `"quoted".py` or with a tab, **then** findings and skip globs use the real name.
- **Given** a staged Latin-1 file, **then** it is scanned (no crash); **and given** an unexpected crash, **then** exit 2, never 1.
- **Given** `skip = "tests/*"` in `.secret-guard.toml`, **then** exit 2 naming the key.
- **Given** two secrets on one line, **then** neither appears in any output; **and given** a placeholder before a real secret on the
  same line, **then** the real one is still judged.
- **Given** a base64 token that decodes to a GitHub token or a private key, **then** it blocks as that rule, marked encoded; **and given** base64 of a hash or plain words, **then** nothing is found.
- **Given** a sequential or repeated value (`abcdefgh`, `123456789`, `aaaaaaaa`), **then** it is a placeholder.
- **Given** `# gitleaks:allow` or `# pragma: allowlist secret` with `allow_inline = true`, **then** the line is ignored.
- **Given** a push range whose base is all zeros, **then** the whole branch is scanned; **and given** a missing base revision, **then** exit 2 with a `fetch-depth: 0` hint.
- **Given** `doctor` and a hook that cannot find the tool, **then** it fails; **given** a stale shared hook, **then** it warns.
- **Given** `git commit -m "... AKIA..."` with the hooks installed, **then** the commit is refused, nothing is committed, the message stays in `COMMIT_EDITMSG` and the secret is not printed.
- **Given** a prose candidate in a message (`the admin password is ...`), **then** exit 0 with a warning and no model call; **and given** a secret only below the scissors line, **then** it is not reported.
- **Given** `scan --diff A..B --messages` and a secret in a commit message in the range, **then** exit 1 naming the commit; **and given** `--messages` without `--diff`, **then** exit 2.
- **Given** an existing `commit-msg` hook that is not ours and no `--force` or `--chain`, **then** nothing is written (no half-installed state).
- **Given** a candidate at column 350 of a long line, **then** the model payload contains it.
- **Given** `HTTP_PROXY` set and a loopback model, **then** the call bypasses the proxy; **and given** a redirect, **then** it is not followed.
- **Given** `SKIP_SECRET_GUARD=1` and a staged secret, **when** scanning staged, **then** exit 0, a `SKIPPED` notice, no model call;
  **and given** any other value (`0`, empty, `true`) **then** it still blocks; **and given** `--files`/`--diff` **then** the
  variable is ignored.
- **Given** a skipped commit, **then** the skips log gains one entry (time, branch, files, masked findings) and never the secret.
- **Given** `install-hook --shared`, **then** `.githooks/pre-commit` is executable and path-free, `core.hooksPath` is set, and
  re-running does not duplicate `.gitattributes`.
- **Given** a healthy setup, **then** `doctor` exits 0; **given** no hook, **then** it exits 1 and names the fix; **given** an
  unreachable model, **then** it only warns.
- **Given** a staged `.env` containing `A=b`, **then** exit 1 with one finding, no model call, and the content not printed;
  **and given** `.env.example`, **then** it is skipped.
- **Given** a staged binary `prod.p12`, **then** exit 1 by name; **given** `id_rsa.pub` or `terraform.tfvars.example`, **then** no name finding.
- **Given** an allowlisted fingerprint (v1 or v2), **then** that finding is not reported; **and given** the line re-indented, **then** a v2 entry still matches.
- **Given** a baseline created from the current findings, **then** `scan --baseline` passes until a new finding appears.
- **Given** `allow_inline = true` and `# smart-commit-guard: allow` on a line, **then** that line is not reported; without the setting it is.
- **Given** an `[[allow]]` entry without a `reason`, **then** exit 2.
- **Given** an existing hook and `install-hook --chain`, **then** it becomes `pre-commit.local` and runs first.
- **Given** a removed line (`-`) containing a secret, **then** it is ignored (only added lines are scanned).

## Out of scope (v1)
- Scanning git history, or secret rotation or revocation.
- PII detection beyond credentials.
- An MCP server, a Claude Code `PreToolUse` wrapper, and any shared `decision-core` package (later, if wanted).
- Auto-fixing or rewriting files.
- Training or tuning the model.

## Eval results (2026-10-06, `jevk5:4b` via ollaya, RTX 4070 laptop GPU)
Data: `evals/cases_tune.json` (75 lines, 32 real) and `evals/cases_holdout.json` (42 lines, 16 real), synthetic only.
Reproduce: `PYTHONPATH=src uv run python evals/run_eval.py` (needs `ollaya serve` with `jevk5:4b`).

Findings that changed the design:
- **Batching hurts this model.** The same line scored 0.87 as `items[0]` and 0.37 as `items[1]`; real secrets in a batch of
  6 scored 0.74-0.96 versus 0.88-0.98 alone, with no per-item speed gain. Hence one candidate per request.
- **Rule gaps capped recall.** The first rule set never surfaced 7 of 41 real secrets (unquoted YAML/compose values, prose,
  `Bearer` headers, `Password=` in connection strings, `mysql -p`, chat webhook URLs). Fixed; 0 unsurfaced afterwards.
- **Obvious placeholders** (`your-...`, `changeme`, `xxxx`, `test-...`) are dropped before the model.

Defaults chosen: **block at p >= 0.5, warn at p >= 0.4**. At those thresholds: tuning set recall 0.97 (the one miss, p 0.36, is the AWS documentation example secret, which the model reasonably treats as an example; it still warns), precision 1.00;
held-out set recall 1.00, precision 1.00 (0 false blocks, 0 missed). Model-judged scores: real secrets 0.68-0.98, placeholders
0.02-0.36 (tuning set had one 0.80 placeholder before the URL fix). Median 70 ms per call.

Caveats: the rules and placeholder filter were tuned on the tuning set and adjusted after seeing the first held-out gaps, so
the held-out numbers are optimistic. The sets are small and synthetic. Other models must rerun the eval and pick their own
thresholds. Real-repo check: SpaceMaker (whole tree) 0 findings; jev-mem 3 blocks and 1 warn, all deliberate fake secrets in
its own tests, eval data and CI config (scores 0.54-0.78, i.e. close to the threshold).
