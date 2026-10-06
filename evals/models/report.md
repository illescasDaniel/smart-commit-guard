# Model comparison

1056 lines that reach the model: 356 real, 700 ok (586 from open-source packages, 427 generated, 43 hand-written).

## Summary (test half: held-out templates, held-out OSS packages, held-out hand-written set)

Threshold fitted on the tune half at <= 2 % false blocks. Intervals: bootstrap 95 %.

| model | disk | AUC (all) | AUC test [95 %] | threshold | recall test [95 %] | false blocks test [95 %] | recall @0.5 | false @0.5 | p50 ms | p95 ms | VRAM peak MiB | VRAM loaded MiB | cold start s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `jevk5:4b` | 4.5 GB | 0.998 | 0.998 [0.996, 1.000] | 0.45 | 0.977 [0.953, 0.995] | 0.016 [0.003, 0.033] | 0.972 | 0.010 | 82 | 102 | +5557 | +5497 | 1.5 |
| `jeb:4b` | 4.6 GB | 0.997 | 0.994 [0.988, 0.998] | 0.47 | 0.994 [0.981, 1.000] | 0.036 [0.017, 0.057] | 0.983 | 0.036 | 75 | 89 | +5274 | +5108 | 1.3 |
| `snap:2b` | 2.7 GB | 0.890 | 0.855 [0.809, 0.892] | 0.24 | 0.614 [0.538, 0.682] | 0.052 [0.028, 0.078] | 0.176 | 0.026 | 43 | 48 | +3097 | +3053 | 1.2 |

## Recall by family at each model's fitted threshold (test half)

| family | n | `jeb:4b` | `jevk5:4b` | `snap:2b` |
|---|---|---|---|---|
| alnum | 26 | 1.00 | 1.00 | 0.62 |
| base64 | 26 | 1.00 | 1.00 | 0.69 |
| hand-written | 9 | 1.00 | 1.00 | 0.78 |
| hex | 26 | 0.96 | 0.96 | 0.42 |
| human_password | 19 | 1.00 | 0.95 | 0.21 |
| jwt | 28 | 1.00 | 1.00 | 0.93 |
| passphrase | 17 | 1.00 | 0.94 | 0.35 |
| prefixed | 25 | 1.00 | 0.96 | 0.80 |

## False blocks by source of `ok` lines at each model's fitted threshold (test half)

| source | n | `jeb:4b` | `jevk5:4b` | `snap:2b` |
|---|---|---|---|---|
| hand-written | 8 | 0 | 0 | 0 |
| generated | 41 | 0 | 2 | 0 |
| oss | 257 | 11 | 3 | 16 |
