# Model comparison

1073 lines that reach the model: 356 real, 717 ok (586 from open-source packages, 443 generated, 44 hand-written).

## Summary (test half: held-out templates, held-out OSS packages, held-out hand-written set)

Threshold fitted on the tune half at <= 2 % false blocks. Intervals: bootstrap 95 %.

| model | disk | AUC (all) | AUC test [95 %] | threshold | recall test [95 %] | false blocks test [95 %] | recall @0.5 | false @0.5 | p50 ms | p95 ms | VRAM peak MiB | VRAM loaded MiB | cold start s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `jevk5:4b` | 4.5 GB | 0.989 | 0.989 [0.980, 0.996] | 0.62 | 0.938 [0.899, 0.970] | 0.019 [0.006, 0.034] | 0.972 | 0.025 | 71 | 90 | +5580 | +5371 | 1.6 |
| `jeb:4b` | 4.6 GB | 0.989 | 0.987 [0.978, 0.995] | 0.64 | 0.943 [0.907, 0.976] | 0.045 [0.023, 0.069] | 0.983 | 0.051 | 67 | 80 | +5142 | +5142 | 1.3 |
| `snap:2b` | 2.7 GB | 0.886 | 0.852 [0.806, 0.892] | 0.28 | 0.517 [0.444, 0.593] | 0.054 [0.030, 0.083] | 0.176 | 0.025 | 39 | 44 | +3038 | +3038 | 1.1 |

## Recall by family at each model's fitted threshold (test half)

| family | n | `jeb:4b` | `jevk5:4b` | `snap:2b` |
|---|---|---|---|---|
| alnum | 26 | 1.00 | 1.00 | 0.50 |
| base64 | 26 | 0.92 | 0.96 | 0.54 |
| hand-written | 9 | 0.53 | 0.53 | 0.35 |
| hex | 26 | 0.96 | 0.85 | 0.35 |
| human_password | 19 | 0.84 | 0.79 | 0.21 |
| jwt | 28 | 0.96 | 1.00 | 0.89 |
| passphrase | 17 | 0.94 | 0.94 | 0.24 |
| prefixed | 25 | 0.92 | 0.96 | 0.64 |

## False blocks by source of `ok` lines at each model's fitted threshold (test half)

| source | n | `jeb:4b` | `jevk5:4b` | `snap:2b` |
|---|---|---|---|---|
| hand-written | 8 | 0 | 0 | 0 |
| generated | 49 | 5 | 6 | 2 |
| oss | 257 | 9 | 0 | 15 |
