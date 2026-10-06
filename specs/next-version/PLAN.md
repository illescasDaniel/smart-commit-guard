# Plan: smart-commit-guard next version (0.2.0)

Status: **In progress.** Written from a code review plus live probes in an isolated container (no model server, Linux,
git 2.x, Python 3.13). Everything that does not need a decision model was implemented and tested in that container (Linux,
Python 3.12 and 3.13); what is left needs the local model, macOS or Windows and is marked **TODO(local)** in the progress
section below and inline.

Legend:
- **[confirmed]** reproduced in this session. The repro is included.
- **[by reading]** follows from the code but was not run.
- **[to measure]** needs the model, real repos or another OS before deciding.

## Progress (implemented without a model; see `CHANGELOG.md`)

Done, with tests (630 unit and integration tests, ruff and ty clean):
- **0.1** safe diff invocation (`git.py`): pinned config, `--no-ext-diff --no-textconv --text --no-renames`, binary suffixes
  excluded from the pathspec, NUL-byte files dropped. Integration tests for every row of the table.
- **0.2** C-quoted path decoding in the parser and `-z` name lists (the `--raw -z` matching idea was not needed).
- **0.3** UTF-8 everywhere, catch-all exit 2, `--json` errors, `SMART_COMMIT_GUARD_DEBUG`.
- **0.4** validated `.secret-guard.toml` (types, unknown keys, scope), warning for a skip that covers every changed file.
- **0.5** loopback bypasses proxies (tested against a real throwaway server with a dead `HTTP_PROXY`), no redirects.
- **0.6** the model gets the unmasked candidate line in every mode, spec, README, config message and tests updated.
- **0.6.1** hosted scope (`SECRET_GUARD_HOSTED_SCOPE`, `[model] hosted_scope`, most restrictive wins, `model_skipped`, doctor).
- **0.7, 0.8, 0.9** all hits per line, previews mask every hit and other long random-looking tokens (Hypothesis property test),
  centred window for long lines.
- **1.1, 1.2 (rules), 1.4, 1.5** rule table with ~20 more token shapes (positive and negative example per rule, enforced by a
  test), UUID / hex-digest / `sk-learn-...` false positives, rules-only for lockfiles and generated files, more sensitive names.
  `secrets.yml` stays candidate-only.
- **2.1, 2.3** repo root and `--files` path normalisation, timeout > 0, https for hosted URLs (`SECRET_GUARD_ALLOW_INSECURE`).
- **2.2 (part)** `SECRET_GUARD_BUDGET` (5 s staged / 120 s otherwise), identical candidates judged once.
- **2.5 (part)** `--version`, `--json` errors, `--files` binary and size checks, `--diff` single revision rejected, `.exe` name check
  in `_executable()`, duplicate regex fragment gone.
- **3.1 (part)** `--all`, `--files -`, `--format sarif`, GitHub annotations, `.pre-commit-hooks.yaml`, `action.yml`.
- **3.2 (part)** `--config-from REF`, warning when the config changes inside a scanned range.
- **4.1** every eval case has a `stage`; `tests/unit/test_eval_cases.py` runs without a model and fails when a real case is `no-hit`.
  `run_eval.py` uses the shared `policy.stage`, fills its cache with one call per candidate (the per-scan cap would have left
  holes) and records model, question version and tool version in `evals/last_run.json`.
- **4.2 (part)** six of the probes from this plan were added to `cases_tune.json`.
- **P3 (part)** `git.py`, rule table, Python 3.14 in the CI matrix and classifiers, coverage in CI, Dependabot for actions and uv,
  `CHANGELOG.md`.

### Done locally (2026-10-06, jevk5:4b via ollaya, RTX 4070 laptop, Linux)
1. **Eval re-run** on the updated rules and cases (tuning 75 lines / 32 real, held-out 42 / 16). At block 0.5 / warn 0.4: tuning
   recall 0.97, precision 1.00 (the one miss is the AWS documentation example secret, p 0.36, which still warns); held-out recall
   1.00, precision 1.00. Thresholds unchanged. `evals/last_run.json` committed. Median 71 ms per call.
2. **0.6 hosted check: not done.** No hosted endpoint was available; the input is identical by construction.
3. **0.9 window:** lines up to 300 characters are sent whole (asserted for every model-stage case). For 69 long variants of the
   eval lines (secret at the start, middle or end of a 300+ character line) the window moved the score by 0.09 on average and
   crossed 0.5 in 6 cases; sending the first 1,000 characters moved it by 0.09 and crossed 0.5 in 10. Keep the window.
4. **1.2 real-repo replay** (486 non-merge commits of 7 local repos; no repo has 500 commits, so this is smaller than planned):
   1.11 model calls per commit on average, 440 of 486 commits (91 %) need none. The top sources were boring shapes: `.svg`
   element ids (186), a `*_checksums.json` of sha256 values (166), Xcode scheme / test plan ids (14), all now rules-only
   by path. Without them the average is about 0.2. `--no-renames` added 6 candidates over the whole replay.
   The remaining top-scoring lines were synthetic fixtures in this repo's and jev-mem's own tests.
5. **1.3 done:** a bare `password` / `token` / `secret` / `key` (and `wrong-password`, `password123`) is still a placeholder, but
   `Password123!` goes to the model. Three `real` cases added to the tuning set; the model scores them 0.60-0.89 and the ok-case
   false-block rate did not rise (0 at block 0.5). End to end: `git commit` of `DB_PASSWORD = "Password123!"` is blocked.
6. **2.2 parallel calls: do not add them.** 2 and 4 workers gave identical scores but no speed-up (44 calls: 2.99 s
   sequential, 2.72 s with 2 or 4 workers; p95 per call 129 ms and 253 ms) because the server serialises them. A verdict
   cache was not built: 91 % of commits make no call. The default budgets fit: 5 s is about 70 calls at 71 ms.
7. **2.4 merge commits (measured, not implemented):** over 33 real merges, the first-parent diff had 11 candidates, the
   second-parent diff 40, and lines in neither parent 0. Scanning only lines that are in neither parent would have produced
   no model calls and no false blocks. Implemented for staged merges (`MERGE_HEAD`, octopus too); `--diff` ranges are unchanged because CI already scans each branch commit.
8. **0.1 big binaries:** on a staged change of 5,000 text files plus 450 MB of binaries with odd suffixes (`.dat`, `.bin`,
   `.safetensors`, an LFS pointer), `--text` made git emit 502 MB; the scan took 25 s. A `--numstat` pre-pass (about 0.07 s) now
   excludes binary files over 256 KiB: git output 7 MB. The rest of the scan time (17 s) is 600,000 added lines in the rules.
   Small files marked `binary` are still scanned. LFS pointers are plain text and are scanned normally.
9. **4.2 / 4.3: not done** (template-split cases, an OSS `ok` corpus, bootstrap intervals, the experiments table).
11. **3.3 doctor:** verified in a temp repo with the real hooks: the pre-commit hook blocks, the commit-msg hook blocks a token
    in a message, a clean commit passes; `doctor` reports the tool version and flagged this repo's own stale `.githooks`
    (refreshed and committed with the new `commit-msg`). The commit messages of 6 local repos (460 messages): 2 warnings
    (merge subjects with long branch slugs, 0.4 %), 0 blocks.
12. **Pinned actions:** `scripts/pin_actions.py` ran (3 workflow files and `action.yml`); `--check` is a step in CI.

### Model comparison (2026-10-06, same 117 cases, RTX 4070 laptop, 6.5 GB usable VRAM)
Candidates had to fit in about 6.5 GB. Run with `SECRET_GUARD_MODEL=<tag> EVAL_OUT=evals/models/<tag>.json python evals/run_eval.py`.
Not run: `my-jev-4b` and `Metask-Jev-4B` (BF16 safetensors on Hugging Face only, 9 GB, no ollaya tag: they need a GGUF Q8
conversion and their own letter-readout adapter), `snap:2b` (needs ollaya 0.10, installed 0.9.0), `winnow:e4b` (8 GB),
`decider:4b`, `kev`, `jeeves`, `clef`, `nimble`, `cygnet` (8.4 GB and up).

| model | size | AUC (28 real / 16 ok, model-stage) | block 0.5: recall / false blocks (tune, held-out) | median call |
|---|---|---|---|---|
| `jevk5:4b` | 4.5 GB | 0.996 | 0.97 / 0, 1.00 / 0 | 71 ms |
| `jeb:4b` | 4.6 GB | 0.991 | 0.97 / 2, 1.00 / 0 | 67 ms |
| `decider:2b` | 3.8 GB | 0.949 | 0.94 / 4, 0.94 / 1 | 1,231 ms |

Ranking: `jevk5:4b`, then `jeb:4b` (slightly more false blocks at 0.5; its best threshold is about 0.7), then `decider:2b`
(overconfident: placeholders score up to 0.91, and slow). The model-stage subset is only 44 lines, so the gaps between the first two
are within noise: the larger eval (4.2 / 4.3) should use `jevk5:4b` and `jeb:4b`.

The expanded comparison (generated and open-source sets, thresholds fitted on a tune half, bootstrap intervals, time and
GPU memory) is in `MODEL_COMPARISON.md`: `jevk5:4b` stays the default, `jeb:4b` is statistically tied, `snap:2b` is not accurate enough.
That also covers 4.2 / 4.3 except the experiments table (context lines, question wording, per-model thresholds file).

### Still TODO(local): needs macOS or Windows, or a hosted model
- **0.6** run the eval against a hosted endpoint (a different hosted model needs its own thresholds).
- **10. Windows / macOS:** `text=True` code page crash is fixed by explicit UTF-8, but test it; `--files` backslash paths; the
  shared hook looking for `.venv/Scripts/smart-commit-guard.exe`; `_executable()` with `.exe`; CI `install-smoke` on macOS and
  Windows (needs `Scripts` vs `bin` handling). The CI matrix runs the unit tests on all three; read its results.
- **4.2 / 4.3** the experiments table (context lines, question wording, `evals/thresholds.json`), `my-jev-4b` / `Metask-Jev-4B` after a GGUF conversion, and a rule for public key prefixes (`pk_live_`).

### Done in the second pass (no model needed)
3.2 richer `[[allow]]` entries, opt-in inline pragma, `--baseline` / `baseline create`, fingerprint v2 with `allowlist migrate`
(v1 and v2 both accepted for this release); 3.3 `install-hook --chain`; P3 `scripts/pin_actions.py` (and the version bump to 0.2.0).
Done locally: the actions are pinned and CI runs `--check`.

### Done in the third pass
3.1 push-event ranges (all-zero `before`, `fetch-depth` hint), 3.2 repo-level `[model]` name and thresholds, 3.3 pinned `uvx`
range and the extra `doctor` checks (tool lookup and version, stale shared hook), release workflow creates the GitHub release with
notes. Ideas taken from similar tools (base64 decoding, sequential-value filter, other tools' inline markers) are in
`RESEARCH.md`, which also lists what was deliberately not adopted and the next candidates.

### Done in the fourth pass
Commit-message scanning (see `RESEARCH.md`): `commit-msg` hook, `scan --message`, `--diff --messages`, `--text -`, `install-hook`
writes both hooks, `doctor` checks the second one.

### Still not done
Everything left is in the "Still TODO(local)" list above, plus the candidates at the end of `RESEARCH.md` (`pre-push` hook, global template-dir install, per-rule stopwords, severity levels, BPE-based randomness test).

---

Work in priority order. P0 items are silent bypasses or leaks, so the gate either lets secrets through without saying so or
prints them. Fix those before adding features.

---

## P0: silent bypasses, leaks and crashes

### 0.1 User git config can make the scan see nothing [confirmed]
`_git("diff", ...)` runs with whatever diff config the user or repo has. Repro in a temp repo with a staged `sk_live_...` line:

| Config | Result today |
|---|---|
| `git config diff.external /bin/true` | **exit 0, no findings** (git runs the external tool, so there is no unified diff to parse) |
| `.gitattributes`: `app.py binary` (or `-diff`) | **exit 0, no findings** ("Binary files differ" lines are ignored) |
| `git config diff.mnemonicPrefix true` | finding path is `i/app.py`: `skip` globs, example paths and allowlist fingerprints all stop matching |
| `diff.noprefix true` | by reading: `+++ app.py` without `b/`, so paths happen to work, but the parser relies on luck |
| `diff.relative true` while run from a subdirectory | by reading: paths become relative to the cwd |

Fix (one helper that every diff call goes through, in a new `git.py`):
```
git -c core.quotepath=off -c diff.mnemonicPrefix=false -c diff.noprefix=false -c diff.relative=false \
    diff --no-ext-diff --no-textconv --no-color --src-prefix=a/ --dst-prefix=b/ -U0 ...
```
For files git treats as binary: either add `--text` and drop lines containing `\0`, or run a second pass that lists
"binary" paths with `git diff --numstat` (binary rows show `-\t-`) and reads their blob with `git show :path` when the path
is not a real binary suffix. **To test:** which one is faster on a 5,000-file staged change and on a repo with large real
binaries (LFS pointers, images).

Tests: integration tests with a real temp repo for each config row above (they must block).

### 0.2 Non-ASCII and special file names are mangled [confirmed]
`parse_added_lines` gets git's C-quoted names: staging `café.py` reports path `"b/caf\303\251.py"`. Skip globs, the env and
sensitive-name rules, example-path detection and fingerprints all see the wrong string. `-c core.quotepath=off` is only
passed to `_changed_paths`, and even with it git still quotes names containing `"`, `\`, tabs or newlines.

Fix: in the parser, unquote C-style quoted paths (handle `\ooo` octal escapes as UTF-8 bytes, plus `\t \n \" \\`). Better:
take paths from `git diff --name-only -z` / `--raw -z` and match them to `diff --git` blocks, so the patch header is never
the source of truth. Also strip the trailing tab git adds after names with spaces (already done) and test it.

Tests: names with spaces, `é`, `"`, a tab, a leading `-`, a rename into a sensitive name (`config.json` -> `.env`).

### 0.3 Non-UTF-8 content crashes with exit 1 (looks like "blocked") [confirmed]
A staged Latin-1 file (`# caf\xe9`) raises `UnicodeDecodeError` inside `subprocess.run(..., text=True)`. The traceback exits
**1**, which the hook and CI read as "blocked by a finding". On Windows, `text=True` decodes with the ANSI code page, so this
also happens for valid UTF-8 containing bytes such as `0x81`/`0x8D` **[to test on Windows]**.

Fix:
- `_git`: `encoding="utf-8", errors="surrogateescape"` (or `"replace"`), never the locale.
- `Path.read_text(...)`: always `encoding="utf-8", errors="replace"` (`_file_lines`, `_repo_settings`, `doctor`), and
  `open(..., encoding="utf-8")` for the skips log.
- `main()`: catch any unexpected `Exception` and return **2** with a one-line message (traceback only with
  `SMART_COMMIT_GUARD_DEBUG=1`). Exit 1 must only ever mean "a finding blocked".

### 0.4 A string instead of a list in `.secret-guard.toml` disables the scan [confirmed]
`skip = "tests/*"` (a string) becomes `list("tests/*")` = `["t","e",...,"*"]`. The `"*"` glob matches every path, so the
scan **passes with exit 0**. `allowlist = "abc"` silently does nothing.

Fix: validate the file: `skip` and `allowlist` must be lists of strings; unknown top-level keys are an error (catches
typos such as `allow_list`); return exit 2 with the key name. Also warn when a skip glob matches every changed path or is
`*` / `**`.

### 0.5 Secrets reach a local HTTP proxy [confirmed]
`urllib.request.urlopen` honours `HTTP_PROXY`/`HTTPS_PROXY`. With `HTTP_PROXY=http://corp-proxy:3128` and no `NO_PROXY`,
`proxy_bypass("localhost")` is `False`, so the **unmasked** candidate line (local mode does not mask) is sent to the
corporate proxy. This breaks the "nothing leaves the machine" promise.

Fix: build the opener with `urllib.request.build_opener(urllib.request.ProxyHandler({}))` for loopback URLs. For hosted
URLs keep proxy support (corporate networks need it) but document it. Also disable redirects: a subclass of
`HTTPRedirectHandler` that raises, so a local server cannot bounce the payload to another host.

Tests: a `post` stub cannot cover this, so add a test that builds the real opener and asserts there is no `ProxyHandler`
with entries (or start a throwaway `http.server` on 127.0.0.1 with `HTTP_PROXY` pointing at a dead port and assert the call
still succeeds).

### 0.6 Hosted mode: send the real line, drop masking for the model [by reading; decided]
Problem: with `SECRET_GUARD_ALLOW_HOSTED=1`, `_judge` sends `masked` text (for example `password = "Aaaaa9999!Aaaa"`). The
question's own `false` criterion says *"a masked value (runs of A/a/9/*)"* is not a credential. So in hosted mode the model
is told that every input is a non-secret, and a masked value carries too little signal to judge anyway. Expected effect:
every model-judged candidate scores low and passes. Rule hits still block.

**Decision:** the model always receives the same unmasked candidate line, local or hosted. Masking stays for everything a
human or log sees (terminal, `--json`, SARIF, skips log, allowlist fingerprints). Choosing a hosted backend means trusting
it with the candidate lines. The hosted opt-in stays, and it is now an explicit consent to that.

Changes:
- `policy.py`: remove the `hosted` parameter from `scan()` and `_judge()`; always send `line.text` (or the centred window from
  0.9). `cli.py`: stop computing and passing `hosted`. `evals/run_eval.py` needs no change.
- `config.py`: keep `SECRET_GUARD_ALLOW_HOSTED=1` as the gate for non-loopback URLs. Reword the refusal: "...is not a local
  server; set SECRET_GUARD_ALLOW_HOSTED=1 to send candidate lines (which may contain real secrets) to it". Require `https://`
  for hosted URLs (see 2.3); this matters more now that raw values are sent.
- Only candidate lines are sent, never whole files or the full diff, and rule hits outside example paths still never reach
  the model. Keep both properties and say so in the docs. Lines that rules already block never leave the machine.
- `doctor` with a hosted URL: print a `WARN` that candidate lines are sent unmasked to `<host>`.
- Hosted scope, so a team can use a hosted model in CI without sending developers' commits to it (see 0.6.1 below).
- Keep the question's "a masked value (runs of A/a/9/*)" criterion: it now only covers values that are masked in the
  source itself (docs showing `****` or `AAAA9999`), which is still correct.

Tests and docs to update in the same change:
- `tests/unit/test_policy.py::test_given_hosted_when_scanning_then_the_model_only_sees_masked_values`: replace it with a test
  that the decider receives the original line in every mode.
- `tests/unit/test_config.py` and `test_cli.py` hosted tests: keep them (refusal without opt-in; nothing sent). Add one for
  the new message and one for `http://` being refused for a hosted URL.
- `SPEC.md`: rewrite the "Trust boundary" bullets ("only redacted snippets are sent" goes) and the BDD line "the request
  body contains the masked value and not the original" (it becomes "the request body contains only the candidate line, not
  other lines or files").
- `README.md` "Privacy" section and the `SECRET_GUARD_ALLOW_HOSTED` row: say plainly that a hosted backend receives the
  unmasked candidate lines, so only use one you would trust with the secrets themselves (for example a self-hosted server on
  your own network).

To measure in the model environment: run the eval against a hosted endpoint with the change and confirm the scores match
the local run for the same model (they should, since the input is now identical). If a different hosted model is used, it
needs its own thresholds (4.3, "Other models").

### 0.6.1 Hosted scope: allow a hosted model in CI but not in the commit hook [new feature]
Why: CI runs on a server the team already trusts with the code, and its secrets live in the CI provider anyway. A
developer's commit hook runs on a laptop, often with work in progress that was never meant to leave it. Some teams will
want a hosted model only in CI.

Design:
- New setting `SECRET_GUARD_HOSTED_SCOPE` with values `all` (default, the 0.6 behaviour) and `ci`.
- With `ci`, a hosted URL is used only for `scan --diff` and `scan --files`. For `scan --staged` (the hook) the model is
  **not called**: model-only candidates are handled exactly like "model unavailable" today (warn and allow) and rule hits
  still block. The commit is not refused (exit 2 on every commit would push people to `--no-verify`); CI is the backstop.
  A loopback URL is never affected by the scope.
- The scope follows the scan mode, not CI environment variables (`CI`, `GITHUB_ACTIONS`): the mode is reliable and cannot be
  changed by a stray variable. Note in the docs that `--files` run locally counts as "ci" too.
- The note printed for the hook says why: "hosted model not used for commits (SECRET_GUARD_HOSTED_SCOPE=ci); ambiguous
  candidates only warn, CI will judge them". In `--json`, add `"model_skipped": "hosted_scope"` next to `model_unavailable`.
- It may also be set in `.secret-guard.toml` (`[model] hosted_scope = "ci"`), because it can only **narrow** where data goes.
  The committed file must never be able to widen it: an env value of `all` does not override a repo value of `ci`
  (most restrictive wins). This matches the 3.2 rule that hosted URLs come only from the env.
- Invalid value: exit 2 with the allowed values (same as other config errors).
- `doctor` prints the effective scope next to the hosted warning, for example
  `WARN model: hosted (api.example.com), used in CI only; commits fall back to rules`.

Tests:
- Scope `ci` + hosted URL + `--staged`: the decider is never called, a model-only candidate warns (exit 0), a rule hit still
  blocks (exit 1), and the note is printed.
- Scope `ci` + hosted URL + `--diff`/`--files`: the decider is called with the unmasked line.
- Scope `ci` + loopback URL + `--staged`: the decider is called (scope only applies to hosted URLs).
- Repo `ci` with env `all` resolves to `ci`; env `ci` with no repo setting resolves to `ci`; bad value exits 2.

Docs: a row in the README env-var table, a short "Hosted model in CI only" example (the GitHub Actions snippet without
`--no-model`, plus `SECRET_GUARD_BASE_URL`, `SECRET_GUARD_ALLOW_HOSTED=1` and `SECRET_GUARD_API_KEY` from repository
secrets), and a new row in the SPEC failure-handling table.

### 0.7 A second secret on the same line is printed in clear [confirmed]
`scan_line` returns only the first hit, and the preview masks only that value. Repro:
`creds = ("AKIA...", "wJalr.../K7MDENG/...")` prints the AWS **secret** key in full in the terminal and CI logs.

Fix:
- `scan_line` returns **all** hits on the line (`finditer` over every rule and candidate regex), deduplicated by span.
- The preview masks every hit value **and** any other token of 16 or more characters with entropy above 3.0 (defence in
  depth: the preview is shown in CI logs). The model payload is unmasked (see 0.6).
- Severity of the line is the most severe hit; the finding lists the rule names.
- Property test (Hypothesis, dev dependency only): for random lines with 1 to 3 injected secrets, no injected secret
  (beyond its known prefix) appears in `preview`, in `--json` output or in the skips log.

### 0.8 A placeholder earlier on a line hides a real secret later on it [confirmed]
`{"password": "changeme", "token": "q8Zr2LmW9vXp4TnK7"}` returns `None`: the first `_QUOTED_ASSIGNMENT` match is a
placeholder and the function returns immediately. One-line JSON, minified configs and `docker run -e A=... -e B=...` are
affected. 0.7's "all hits" change fixes this. Add this exact case to the tuning set.

### 0.9 The model sees only the first 300 characters of the line [by reading]
`t[:MAX_ITEM_CHARS]` keeps the prefix. For a long line (minified JSON, a one-line YAML flow map) the candidate value can be
after character 300, so the model judges text without the secret and the candidate is waved through. Fix: send a window of
about 300 characters **centred on the hit's span** (plus the variable name if it is before the window), with `…` at cut
edges. Test: a value at column 350 must appear in the payload.

---

## P1: detection quality (rules)

### 1.1 False negatives found in probes [confirmed]
| Input | Today | Change |
|---|---|---|
| `-----BEGIN PGP PRIVATE KEY BLOCK-----` | nothing | rule: `-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----` |
| `github_pat_11ABC...` (fine-grained PAT) | nothing | add `github_pat_[A-Za-z0-9_]{60,}` |
| `//registry.npmjs.org/:_authToken=...` (`.npmrc`) | nothing | content rule for `_authToken=`/`_auth=`/`npmAuthToken:` (candidate) plus `npm_[A-Za-z0-9]{36}` (rule) |
| a JWT `eyJ....eyJ....sig` | nothing | candidate rule (JWTs in tests are common, so model-judged, not a hard block) |
| `"wJalr.../K7MDENG/bPx..."` (40-char AWS secret, no secret-like name) | nothing: 2+ slashes, so `_looks_like_path_or_identifier` skips it | treat a value as a path only if it starts with `/`, `./`, `~/` or a drive letter, or each segment is lowercase/dictionary-like; keep base64-looking values |
| `HF = "hf_..."` | candidate only | rule `hf_[A-Za-z0-9]{30,}` |

More prefixes worth adding as high-confidence rules (each needs a positive and a negative unit test): Stripe `rk_live_`,
`whsec_`; Slack `xapp-`, `xoxe-`; GitLab `glptt-`, `gldt-`, `glrt-`; SendGrid `SG.<22>.<43>`; PyPI `pypi-AgEI`; npm
`npm_`; Shopify `shpat_|shpss_|shpca_`; DigitalOcean `dop_v1_`; Doppler `dp.pt.`; Telegram bot `\d{8,10}:AA[\w-]{33}`;
Azure Storage `AccountKey=[A-Za-z0-9+/=]{80,}`; Google OAuth `GOCSPX-`; Anthropic `sk-ant-` (already covered by `sk-`,
but name it for a better reason string).

Single source of truth: `redact._KNOWN_PREFIXES` duplicates the rule prefixes. Derive it from a rule table
(`name, regex, group, known_prefix, high_confidence`).

### 1.2 False positives found in probes [confirmed]
| Input | Today | Change |
|---|---|---|
| `"sk-learn-contrib-projects"` | **BLOCK** as API token (no model) | require at least one digit and one letter in the `sk-` tail, or a minimum entropy; check against real OpenAI/Anthropic key formats |
| UUID `"3f2b8c1e-9a4d-..."` | candidate (model call) | skip canonical UUIDs |
| 40/64-char hex in quotes (git SHA, sha256) | candidate (model call) | skip hex when the name or line contains `sha`, `hash`, `digest`, `checksum`, `commit`, `rev`, `integrity`, `etag`; still a candidate when the name is secret-like (`JWT_SECRET = "<hex>"`) |

**[to measure]** model calls per commit: replay the last 500 commits of 5 to 10 real repos
(`scan --diff C~1..C --json`) and count candidates. Target: under 1 model call per commit on average. Rank the top 20
candidate shapes and add skip rules for the boring ones (i18n keys, CSS hashes, base64 images, test vectors).

### 1.3 Placeholder filter is too eager [confirmed, to measure]
`DB_PASSWORD = "Password123!"` is dropped as a placeholder (`password` token followed by a digit). Weak but real
passwords like this are exactly what leaks in practice. Same for values starting with `Test1`, `Secret2026!`, `Token...`.
Proposal: the "placeholder word" check only drops a value when the rest is also low-entropy or a known pattern
(`your-...-here`, `xxx`, `changeme`, `<...>`, `...`). Otherwise send it to the model. Add these as `real` cases to the
eval and check the false-block rate on the `ok` cases does not rise.

### 1.4 Generated files and lockfiles are skipped entirely [by reading]
`.min.js` and `.map` can carry inlined API keys (frontend builds, `sourcesContent`). Lockfiles can contain
`https://user:token@registry/...` in `resolved` URLs. Proposal: for these files run **only the high-confidence rules**
(no candidates, so no model calls and no noise). Keep skipping real binaries.

### 1.5 More sensitive file names [by reading]
Candidates: `.vault-token`, `.cargo/credentials.toml` and `.cargo/credentials`, `credentials.tfrc.json`,
`.gem/credentials`, `.composer/auth.json`, `.config/gh/hosts.yml`, `*.ovpn` with inline keys (content rule better),
`secrets.yml`/`secrets.yaml` (decide: name block or candidate-only). `.npmrc` and `.yarnrc.yml` are often committed without
tokens, so use content rules for them (1.1), not a name block. Each addition needs the template exemption test.

---

## P1: correctness of the CLI and config

### 2.1 `.secret-guard.toml` is read from the cwd, and `--files` paths are not normalized [confirmed]
- From a subdirectory, `scan --files x.py` does not read the root config (the skip glob was ignored).
- `--files ./sub/x.py` does not match `skip = ["sub/*"]`, and its fingerprint differs from the `sub/x.py` one, so an
  allowlist entry made in CI does not work locally.
Fix: resolve the repo root once (`git rev-parse --show-toplevel`, falling back to the cwd outside git); read the config
from there; convert every `--files` path to a repo-relative POSIX path before skip, rules and fingerprints. Also apply this
on Windows (backslashes) **[to test on Windows]**.

### 2.2 Model call budget [by reading]
- 30 sequential calls with a 10 s timeout can take up to about 5 minutes against a slow but responsive server. Add a total
  deadline (`SECRET_GUARD_BUDGET`, default 5 s for `--staged`, longer for CI); unjudged candidates then warn, as today.
- Deduplicate identical `(path, line text)` candidates in a scan (the same secret pasted in several places).
- **[to measure]** Parallel calls (`ThreadPoolExecutor`, 2 to 4 workers): does ollaya serve them concurrently, and does
  the score stay identical (batching changed scores; concurrency should not, but check)?
- Optional verdict cache in the git dir, keyed by `sha256(model, question version, line text)` and storing only `p`, so
  `git commit --amend` and retries don't re-judge. The cache must never store the text.

### 2.3 Config validation gaps [confirmed]
`SECRET_GUARD_TIMEOUT=0` is accepted and fails with a confusing `Operation now in progress`. Require `timeout > 0`. For a
hosted URL require `https://` (over plain HTTP, the Bearer token and the unmasked candidate lines from 0.6 travel in clear)
unless `SECRET_GUARD_ALLOW_INSECURE=1`.

### 2.4 Merge commits [to measure]
During a merge, `git diff --cached` contains every line brought in from the other branch. That can surface old findings
nobody in this commit wrote and use up the 30-call cap. Options: when `MERGE_HEAD` exists, scan only lines not present in
either parent (`git diff --cached --cc` style), or rules only. Test with a real merge of two branches.

### 2.5 Smaller items
- `--version` flag and `__version__` (from `importlib.metadata`); `doctor` prints it.
- `--json` on a tool error prints `{"exit_code": 2, "error": "..."}` instead of nothing.
- `scan --files` reads whole files before checking the suffix: skip binary suffixes and files with `\0` in the first 8 KB
  before reading the rest; cap file size (for example 2 MB, with a warning).
- `--diff` with a single revision silently means "working tree vs revision". Reject it unless it contains `..`, or document.
- Windows shared hook: also look for `$root/.venv/Scripts/smart-commit-guard.exe` **[to test on Windows]**.
- `_executable()` on Windows: `sys.argv[0]` ends in `.exe`, so the name check fails and it falls back to `which`.
- Duplicate regex fragments: `_NAME` and `_NAME_WORD` in `rules.py` are identical.

---

## P2: features for adoption

### 3.1 CI and integrations
- `scan --all` (or `--files -` reading NUL-separated paths from stdin). The README's `--files $(git ls-files)` hits the
  argument-length limit on large repos, and on Windows at 32 KB.
- Output formats: `--format sarif` (GitHub code scanning), and GitHub Actions annotations
  (`::error file=...,line=...::`) when `GITHUB_ACTIONS=true`. SARIF must contain the masked preview only.
- A `.pre-commit-hooks.yaml` (`entry: smart-commit-guard scan --staged`, `pass_filenames: false`) for the pre-commit
  framework, and a composite GitHub Action (`action.yml`) wrapping the README example.
- Push events: scan `${{ github.event.before }}..${{ github.sha }}` instead of the whole tree (handle the all-zero `before`
  of a new branch).

### 3.2 Allowlist and adoption
- **The allowlist is part of the diff it guards.** A PR can add `skip = ["*"]` and CI honours it. Proposal: in `--diff`
  mode, print a loud warning when `.secret-guard.toml` changes in the range, and add `--config-from REF` (for example
  `origin/main`) so CI can read the config from the base branch.
- Richer allowlist entries, keeping the plain list working:
  `[[allow]] fingerprint = "..." path = "..." reason = "..."`, so reviewers see why.
- Optional inline pragma (`# smart-commit-guard: allow`), off by default (`allow_inline = true` to enable), because it is
  easy to abuse. Visible in review, unlike `SKIP_SECRET_GUARD`.
- `--baseline FILE` / `baseline create` for adopting the tool on an existing repo (record current findings, fail only on
  new ones).
- Fingerprint robustness: today it hashes the whole masked line, so re-indenting breaks the allowlist. Consider hashing the
  stripped line. **This changes every fingerprint**: accept both v1 and v2 for one release, and add
  `smart-commit-guard allowlist migrate`.
- Repo-level model settings in `.secret-guard.toml` (`[model] base_url, name, block_at, warn_at`), with env vars still
  winning. Only allow hosted URLs from the env, never from the committed file (a PR must not be able to send your diff
  somewhere).

### 3.3 Hooks
- `install-hook --chain`: if a `pre-commit` hook already exists (husky, lefthook, a custom one), keep it as
  `pre-commit.local` and call it before the scan, instead of only `--force` clobbering it.
- Shared hook: write the `uvx` fallback pinned to the installing version's minor range
  (`uvx --from 'smart-commit-guard>=0.2,<0.3'`) instead of an unpinned `uvx smart-commit-guard`.
- `doctor`: also check that the hook can find the tool (run it the way the hook does), report the version it finds, and
  warn when `core.hooksPath` points at `.githooks` but the shared hook is missing or stale (compare with the template).

---

## P2: evals (all need the model environment)

### 4.1 Make the deterministic part a unit test (runs without the model)
Add `tests/unit/test_eval_cases.py`: for every case in `evals/cases_*.json`, assert the stage (`rule-block`, `model`,
`no-hit`) matches an expected value stored in the case, and that no `real` case is `no-hit`. This turns the eval's
"rules never surface" check into a CI regression gate. Add a `stage` field to each case.

### 4.2 Bigger and harder data
- Add every probe in this plan as a case (both labels).
- Generate cases from templates per secret family and file type (Python, JS, YAML, JSON, `.env`, Dockerfile, Terraform,
  shell, Markdown), with placeholders drawn from real conventions. Keep `tune` and `holdout` split by **template**, not by
  line, so the held-out set is not near-duplicates.
- A real-world `ok` corpus: candidates mined (with `--no-model --json`) from popular OSS repos that are known to have no
  live secrets. This measures the false-block rate that matters.
- Report per family recall and precision, with bootstrap confidence intervals (the current sets are too small for
  "1.00" to mean much).

### 4.3 Experiments to run
| Experiment | Question | Decide by |
|---|---|---|
| Hosted mode (0.6) | with unmasked input, does a hosted endpoint score the same as local for the same model? | identical p values (within noise) |
| Centred window (0.9) | does centring change scores for short lines? (it should not) | no regression on current sets |
| Context lines | send ±1 to 2 surrounding added lines | better precision on test fixtures, no recall loss |
| Question wording | with vs without `criteria`; mention the file path explicitly | calibration (ECE) and recall |
| Concurrency (2.2) | identical scores and lower wall time with 2 to 4 workers | same p values, lower p95 hook time |
| Other models | rerun with at least one more small local model | publish thresholds per model in `evals/thresholds.json` |
| Hook latency | median and p95 on real commit replay (1.2) | median <= 1 s, as in the spec |

Also store the model name, question version and tool version in `evals/last_run.json`, so runs can be compared.

---

## P3: engineering and release

- New `git.py` module: one place for the safe git invocation (0.1), path unquoting (0.2), encoding (0.3) and repo root
  (2.1). The CLI then has no raw `subprocess` calls.
- Rule table refactor (1.1): `rules.py` becomes data plus a loop, and a test asserts every rule has positive and negative
  examples.
- CI: add Python 3.14 to the matrix and classifiers; run `install-smoke` on macOS and Windows too; add coverage reporting;
  pin third-party actions by commit SHA and add Dependabot for actions; add the rules-only eval gate (4.1).
- Release: `CHANGELOG.md`; bump to **0.2.0** (allowlist fingerprints change for affected paths after 0.1, 0.2 and 2.1, and
  for every path if 3.2's whitespace normalisation lands, so it is not a patch release); keep the manual release workflow
  but also create the GitHub release with notes.
- Update `specs/secret-scan/SPEC.md` for every behaviour change above before implementing it (the spec is the contract the
  BDD tests follow).

---

## Suggested order for the next session
1. `git.py` with safe diff flags, path unquoting and UTF-8 decoding, plus catch-all exit 2 (0.1, 0.2, 0.3). Integration tests first (red), then fix.
2. Config validation and repo-root resolution (0.4, 2.1, 2.3).
3. Proxy and redirect hardening (0.5).
4. All-hits-per-line, full masking, centred window (0.7, 0.8, 0.9) with the property test.
5. Rule additions and FP fixes (1.1 to 1.5), each with unit tests and eval cases; then the rules-only eval gate (4.1).
6. Hosted mode sends unmasked candidate lines (0.6), with the spec, README and test updates listed there; then the hosted
   scope setting (0.6.1).
7. In the model environment: the 4.3 experiments; recalibrate thresholds; update the spec's eval section.
8. Features (3.x) as time allows; `--all`, SARIF/annotations and `.pre-commit-hooks.yaml` first.
