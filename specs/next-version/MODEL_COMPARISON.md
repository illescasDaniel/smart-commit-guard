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

## Round 2: expanded evaluation (1,056 lines that reach the model: 356 real, 700 ok)

New data, all committed under `evals/`:
- `cases_generated.json` (427): 30 line templates (Python, JS, Java, Go, YAML, TOML, env, shell, curl, SQL, prose...) x 7
  kinds of secret value (human password, passphrase, hex, alnum, base64, prefixed token, JWT-like) with random synthetic
  values, plus `ok` values under sensitive-looking keys (TTLs, type names, labels, secret references, digests, git shas,
  UUIDs). `evals/generate_cases.py` regenerates it. Templates are split in half (`tune` / `test`).
- `cases_oss.json` (586): candidate lines mined from 95 installed open-source packages (`evals/mine_oss.py`), labelled `ok`;
  split by package. One line (a public OAuth client secret in lutris) was dropped as ambiguous.
- The two hand-written sets (43 model-stage lines), `tune` and `holdout` as before.
- Stripe publishable keys (`pk_live_...`) were in an earlier version of the set: both 4B models blocked them, so they became
  a rule (never a candidate) and left the set.

Protocol: one threshold per model, the lowest that keeps false blocks at or under 2 % on the `tune` half, scored on the `test`
half (held-out templates, held-out packages, the held-out hand-written set). 95 % intervals by bootstrap (1,000 resamples).
AUC does not depend on a threshold, so it is the fairest single number across models. Fitted thresholds: `evals/thresholds.json`.

| model | AUC test [95 %] | fitted threshold | recall test [95 %] | false blocks test [95 %] | recall / false blocks at 0.5 |
|---|---|---|---|---|---|
| `jevk5:4b` | **0.998** [0.996, 1.000] | 0.45 | 0.977 [0.953, 0.995] | **0.016** [0.003, 0.033] | 0.972 / 0.010 |
| `jeb:4b` | 0.994 [0.988, 0.998] | 0.47 | **0.994** [0.981, 1.000] | 0.036 [0.017, 0.057] | 0.983 / 0.036 |
| `snap:2b` | 0.855 [0.809, 0.892] | 0.24 | 0.614 [0.538, 0.682] | 0.052 [0.028, 0.078] | 0.176 / 0.026 |

Time and resources (whole run of 1,056 single-line calls, GPU memory measured with `nvidia-smi` every 50 ms minus the idle
desktop, so it includes the weights, KV cache and compute buffers):

| model | disk | p50 | p95 | throughput | cold start | GPU memory peak | GPU memory steady | server RAM |
|---|---|---|---|---|---|---|---|---|
| `jevk5:4b` | 4.5 GB | 82 ms | 102 ms | 11.8 calls/s | 1.5 s | 5.6 GB | 5.5 GB | about 11 MB |
| `jeb:4b` | 4.6 GB | 75 ms | 89 ms | 13.0 calls/s | 1.3 s | 5.3 GB | 5.1 GB | about 11 MB |
| `snap:2b` | 2.7 GB | 43 ms | 48 ms | 22.9 calls/s | 1.2 s | 3.1 GB | 3.1 GB | about 11 MB |

(Latency is a little higher than in the first run because the desktop was using the GPU at the same time: 1.5 GB idle.)

Recall by kind of secret at each model's fitted threshold (test half), `jevk5:4b` / `jeb:4b` / `snap:2b`: alnum 1.00 / 1.00 /
0.62, base64 1.00 / 1.00 / 0.69, hex 0.96 / 0.96 / 0.42, human password 0.95 / 1.00 / 0.21, passphrase 0.94 / 1.00 / 0.35,
JWT-like 1.00 / 1.00 / 0.93, prefixed token 0.96 / 1.00 / 0.80, hand-written 1.00 / 1.00 / 0.78.

False blocks on the `test` half by source of the `ok` line (n in brackets), `jevk5:4b` / `jeb:4b` / `snap:2b`: hand-written
(8) 0 / 0 / 0; generated (41) 2 / 0 / 0; open-source packages (257) 3 / 11 / 16.

## Prompt experiments (`jevk5:4b`, same set, `evals/experiments.py`)

| variant | AUC test [95 %] | recall test | false blocks test | ECE |
|---|---|---|---|---|
| shipped question | 0.998 [0.996, 1.000] | 0.977 | 0.016 | 0.098 |
| without `criteria` | 0.999 [0.997, 1.000] | 0.989 | 0.020 | 0.108 |
| file path named in the question | 0.998 [0.996, 1.000] | 0.977 | 0.013 | 0.090 |
| one real line of context before and after | 0.999 [0.998, 1.000] | 0.983 | 0.033 | 0.101 |

All within noise of each other, so the shipped question stays. Context lines did not help (the false-block rate doubled), which
also means the `/v1/systemone` input does not need to grow. (The generated lines have no file around them, so they got a fixed
neighbour pair; the open-source lines got their real neighbours.)

## What this says

1. **`jevk5:4b` stays the default.** It has the best AUC and the fewest false blocks on real-world lines (3 of 257 open-source
   lines at its fitted threshold, against 11 for `jeb:4b`, which blocks documentation examples such as `scott:tiger` URLs and
   `password="tiger"`). `jeb:4b` has slightly higher recall, a little less VRAM and latency, and is a sound second choice, for
   example as a cross-check.
2. **`snap:2b` is not accurate enough** (AUC 0.86, recall 0.61 at 5 % false blocks) although it halves the VRAM and latency.
3. **Both 4B models fit in 6.5 GB** with room to spare (5.3 to 5.6 GB), at 75 to 82 ms a call; the 5 s hook budget covers about 60 calls.
4. **Weakest real family for the shipped model: hex and human-chosen passwords** (0.94 to 0.96 recall at its threshold).

## Caveats
- The generated set is synthetic and template-based; real-world recall is probably lower. The open-source lines test only
  false blocks (all labelled `ok`); there is no real-world set of true secrets (none can be mined safely).
- Thresholds come from a 2 % false-block target on one half of the data, so they are noisy. The shipped defaults (block 0.5,
  warn 0.4) are unchanged: `jevk5:4b` at 0.5 has recall 0.972 and 1.0 % false blocks, which is within the interval of its fitted value.
- Round 1's fitted-threshold columns (`evals/models/report_small.md`) use 44 lines and mean nothing; use AUC there.
- GPU memory is total used minus idle; other desktop programs can move it by a few hundred MB.
