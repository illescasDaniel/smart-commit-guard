# Plan: smart-commit-guard 0.2.0

Status: **implemented**. The behaviour is in `CHANGELOG.md` and `specs/secret-scan/SPEC.md`; the model comparison is in
`MODEL_COMPARISON.md`; ideas for later are in `RESEARCH.md`. The long item-by-item plan this file used to hold (0.x
silent bypasses, 1.x rules, 2.x CLI, 3.x adoption features, 4.x evals, P3 release work) is in git history
(`git log -p specs/next-version/PLAN.md`).

## Still to do

- **Windows and macOS checks** (needs those machines; the CI matrix runs the unit tests on all three, read its results):
  - `text=True` code page crash is fixed by explicit UTF-8, but test it on Windows.
  - `--files` with backslash paths.
  - The shared hook looking for `.venv/Scripts/smart-commit-guard.exe`, and `_executable()` with `.exe`.
  - CI `install-smoke` on macOS and Windows (`Scripts` vs `bin`).
- **Dropped for now**: `my-jev-4b` / `Metask-Jev-4B` (BF16 safetensors only; they need a GGUF Q8 conversion and their own
  letter-readout adapter), and every model that does not fit in 6.5 GB of VRAM.
- Candidates for later versions: see the end of `RESEARCH.md` (`pre-push` hook, global template-dir install, per-rule
  stopwords, severity levels, BPE-based randomness test).

## What was measured (2026-10-06, `jevk5:4b` via ollaya, RTX 4070 laptop, Linux)

Details and tables: `MODEL_COMPARISON.md` (models, larger eval sets, prompt experiments) and `evals/last_run.json` (hand-written
sets).

- **Eval on the hand-written sets** (tune 75 lines / 32 real, held-out 42 / 16): at block 0.5 / warn 0.4, tune recall 0.97 and
  precision 1.00 (the one miss is the AWS documentation example secret, which still warns); held-out 1.00 / 1.00.
- **Larger eval** (1,056 lines: 356 real, 700 ok, template-split generated cases, open-source `ok` corpus, bootstrap intervals):
  `jevk5:4b` AUC 0.998, recall 0.98 and 1.6 % false blocks at its fitted threshold. `jeb:4b` is a close second; `snap:2b` is too weak.
  Per-model fitted thresholds are in `evals/thresholds.json`; the defaults (0.5 / 0.4) stay.
- **Prompt experiments**: dropping `criteria`, naming the file path or adding a line of context before and after the candidate all
  stay within noise of the shipped question; context doubled the false blocks. The question stays as is.
- **Window (0.9)**: lines up to 300 characters are sent whole. For long lines a window centred on the candidate beats the first
  1,000 characters (6 versus 10 score crossings of 0.5 over 69 variants).
- **Real-repo replay** (486 non-merge commits of 7 local repos): 1.11 model calls per commit on average, 91 % of commits need none.
  The noisiest sources (`.svg` ids, checksum files, Xcode ids) are now rules-only by path.
- **Placeholders (1.3)**: a bare `password` / `token` / `secret` / `key` is still a placeholder, but `Password123!` goes to the
  model (scores 0.60-0.89, no rise in false blocks).
- **Parallel calls (2.2)**: no speed-up on this GPU (the server serialises them), so the batch size stays 1 and there is no
  worker pool. The 5 s hook budget is about 60 to 70 calls.
- **Merge commits (2.4)**: over 33 real merges, lines in neither parent produced 0 candidates; implemented for staged merges
  (`MERGE_HEAD`, octopus too). `--diff` ranges are unchanged because CI scans each branch commit.
- **Big binaries (0.1)**: a `--numstat` pre-pass drops binary files over 256 KiB; git output for a 450 MB change went from
  502 MB to 7 MB.
- **Commit messages**: 2 warnings (merge subjects with long branch slugs) and 0 blocks over 460 messages of 6 repos.
- **Stripe publishable keys**: both 4B models blocked `pk_live_...` lines, so they are now a rule (public identifiers, never a
  candidate); `sk_` and `rk_` keys still block.
- **Doctor / hooks**: verified in a temp repo with the real hooks (pre-commit blocks, commit-msg blocks a token in a message,
  clean commit passes; `doctor` flags stale hooks). Actions are pinned by SHA and CI runs `scripts/pin_actions.py --check`.

- **Hosted check (0.6)**: 60 lines scored with TypeSafe `jev-latest` against local `jevk5:4b`: AUC 1.000 vs 0.997, same ranking, 242 ms median
  per call (`MODEL_COMPARISON.md`). A hosted model still needs its own thresholds if used for blocking at scale.

## Decisions worth remembering
- Model choice lives in `~/.config/smart-commit-guard/config.json` (user-owned, may name a server and key); the repo file may only narrow;
  a `.env` is never read by the tool.
- A hosted backend receives the candidate line unmasked (the model must see the value); output stays masked. `hosted_scope = "ci"`
  keeps a hosted model out of the commit hook.
- Loopback URLs bypass proxies and no redirects are followed.
- Allowlist fingerprints are `v2:` (hash of the stripped line); v1 entries are still read; `allowlist migrate` rewrites them.
- The model sees one candidate per call (MAX_BATCH = 1): scores vary with position in a batch.
