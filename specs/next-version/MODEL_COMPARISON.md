# Decision-model comparison (2026-10-06)

Hardware: RTX 4070 Laptop, 8 GB VRAM (about 1 GB used by the desktop, ~6.5 GB usable), ollaya 0.10.0 on llama.cpp, one
candidate line per request (what the tool sends). Reproduce with `evals/compare_models.py` (`run <model>`, then `report`).
Raw scores, latencies and memory samples are in `evals/models/scores_*.json`; the generated tables in `evals/models/report.md`.

## Round 1: screening on the hand-written sets (44 model-judged lines: 28 real, 16 ok)

| model | disk | AUC | recall / false blocks at 0.5 | p50 | GPU memory |
|---|---|---|---|---|---|
| `jevk5:4b` (current) | 4.5 GB | 0.996 | 1.00 / 0 | 73 ms | +5.5 GB |
| `jeb:4b` | 4.6 GB | 0.991 | 1.00 / 0 | 67 ms | +5.1 GB |
| `snap:2b` | 2.7 GB | 0.938 | 0.33 / 0 (scores run low: needs its own threshold) | 40 ms | +3.0 GB |
| `decider:2b` | 3.8 GB | 0.949 (run on ollaya 0.9) | 0.94 / 1 to 4 | 1,231 ms | F32: 7.4 GB used in total, HTTP 500 mid-run on 0.10 |

Dropped: `decider:2b` (overconfident, slow, does not fit comfortably). Not run: `my-jev-4b` and `Metask-Jev-4B` (BF16
safetensors only, no GGUF or ollaya tag; they would need a conversion and their own readout adapter), and everything that
does not fit in 6.5 GB (`winnow:e4b` 8.0 GB, `decider:4b` 8.4 GB, `kev:4b` 9.5 GB, the 9B, 12B and 27B models).
Top 2 by accuracy at a reasonable time: **`jevk5:4b` and `jeb:4b`**. `snap:2b` went along as the small, fast reference.

## Round 2: expanded evaluation (1,073 lines that reach the model: 356 real, 717 ok)

New data, all committed under `evals/`:
- `cases_generated.json` (443): 30 line templates (Python, JS, Java, Go, YAML, TOML, env, shell, curl, SQL, prose...) x 7
  kinds of secret value (human password, passphrase, hex, alnum, base64, prefixed token, JWT-like) with random synthetic
  values, plus `ok` values under sensitive-looking keys (TTLs, type names, labels, secret references, publishable keys,
  digests, git shas, UUIDs). `evals/generate_cases.py` regenerates it. Templates are split in half (`tune` / `test`).
- `cases_oss.json` (586): candidate lines mined from 95 installed open-source packages (`evals/mine_oss.py`), labelled `ok`;
  split by package. One line (a public OAuth client secret in lutris) was dropped as ambiguous.
- The two hand-written sets (44 model-stage lines), `tune` and `holdout` as before.

Protocol: one threshold per model, the lowest that keeps false blocks at or under 2 % on the `tune` half, scored on the `test`
half (held-out templates, held-out packages, the held-out hand-written set). 95 % intervals by bootstrap (1,000 resamples).
AUC does not depend on a threshold, so it is the fairest single number across models.

| model | AUC test [95 %] | fitted threshold | recall test [95 %] | false blocks test [95 %] | recall / false blocks at 0.5 |
|---|---|---|---|---|---|
| `jevk5:4b` | **0.989** [0.980, 0.996] | 0.62 | 0.938 [0.899, 0.970] | **0.019** [0.006, 0.034] | 0.972 / 0.025 |
| `jeb:4b` | 0.987 [0.978, 0.995] | 0.64 | **0.943** [0.907, 0.976] | 0.045 [0.023, 0.069] | 0.983 / 0.051 |
| `snap:2b` | 0.852 [0.806, 0.892] | 0.28 | 0.517 [0.444, 0.593] | 0.054 [0.030, 0.083] | 0.176 / 0.025 |

Time and resources (whole run of 1,073 single-line calls, GPU memory measured with `nvidia-smi` every 50 ms minus the idle
desktop, so it includes the weights, KV cache and compute buffers):

| model | disk | p50 | p95 | throughput | cold start | GPU memory peak | GPU memory steady | server RAM |
|---|---|---|---|---|---|---|---|---|
| `jevk5:4b` | 4.5 GB | 71 ms | 90 ms | 13.6 calls/s | 1.6 s | 5.6 GB | 5.4 GB | about 10 MB |
| `jeb:4b` | 4.6 GB | 67 ms | 80 ms | 14.6 calls/s | 1.3 s | 5.1 GB | 5.1 GB | about 10 MB |
| `snap:2b` | 2.7 GB | 39 ms | 44 ms | 25.3 calls/s | 1.1 s | 3.0 GB | 3.0 GB | about 10 MB |

Recall by kind of secret at each model's fitted threshold (test half): `jevk5:4b` / `jeb:4b` - alnum 1.00 / 1.00, base64
0.96 / 0.92, hex 0.85 / 0.96, human password 0.79 / 0.84, passphrase 0.94 / 0.94, JWT-like 1.00 / 0.96, prefixed token 0.96 /
0.92. `snap:2b` is weakest on human passwords (0.21), passphrases (0.24) and hex (0.35).

False blocks on the `test` half by source of the `ok` line (n in brackets), `jevk5:4b` / `jeb:4b` / `snap:2b`: hand-written
(8) 0 / 0 / 0; generated (49) 6 / 5 / 2; open-source packages (257) 0 / 9 / 15.

## What this says

1. **`jevk5:4b` stays the default.** It has the best AUC and the fewest false blocks on real-world lines (0 of 257 open-source
   lines at its fitted threshold, against 9 for `jeb:4b`). `jeb:4b` is statistically tied on AUC (the intervals overlap), has
   slightly higher recall, a little less VRAM and a little lower latency, but blocks more documentation examples
   (`scott:tiger` URLs, `password="tiger"`). It is a sound second choice, for example as a cross-check.
2. **`snap:2b` is not accurate enough** (AUC 0.85, recall 0.52 at 5 % false blocks) although it halves the VRAM and latency.
3. **Both 4B models fit in 6.5 GB** with room to spare (5.1 to 5.6 GB), at about 70 ms a call; the 5 s hook budget covers about 70 calls.
4. **Shared weakness: publishable keys.** Both 4B models block `pk_live_...` lines under `publishable_key` / `STRIPE_PUBLIC_KEY`
   (6 of 8 test cases for `jevk5:4b`, 5 for `jeb:4b`), and UUID values under `correlation_token`. A rule for known public prefixes
   (`pk_live_`, `pk_test_`) is cheaper than any model change.
5. **Weakest real family for both: human-chosen passwords** (0.79 to 0.84 recall), the same family the placeholder fix targeted.

## Caveats
- The generated set is synthetic and template-based; real-world recall is probably lower. The open-source lines test only
  false blocks (all labelled `ok`); there is no real-world set of true secrets (none can be mined safely).
- The `snap:2b` and `jeb:4b` thresholds come from a 2 % false-block target on one half of the data, so they are noisy.
- Round 1's fitted-threshold columns (`evals/models/report_small.md`) use 44 lines and mean nothing; use AUC there.
- GPU memory is total used minus idle; other desktop programs can move it by a few hundred MB.
