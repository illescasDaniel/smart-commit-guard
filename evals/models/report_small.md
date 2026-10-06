# Model comparison

44 lines that reach the model: 28 real, 16 ok (0 from open-source packages, 0 generated, 44 hand-written).

## Summary (test half: held-out templates, held-out OSS packages, held-out hand-written set)

Threshold fitted on the tune half at <= 2 % false blocks. Intervals: bootstrap 95 %.

| model | disk | AUC (all) | AUC test [95 %] | threshold | recall test [95 %] | false blocks test [95 %] | recall @0.5 | false @0.5 | p50 ms | p95 ms | VRAM peak MiB | VRAM loaded MiB | cold start s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `jeb:4b` | 4.6 GB | 0.991 | 1.000 [1.000, 1.000] | 0.64 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 | 0.000 | 67 | 73 | +5110 | +5110 | 2.4 |
| `jevk5:4b` | 4.5 GB | 0.996 | 1.000 [1.000, 1.000] | 0.48 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 | 0.000 | 73 | 80 | +5496 | +5489 | 2.8 |
| `snap:2b` | 2.7 GB | 0.938 | 1.000 [1.000, 1.000] | 0.50 | 0.333 [0.000, 0.700] | 0.000 [0.000, 0.000] | 0.333 | 0.000 | 40 | 44 | +3038 | +3038 | 1.7 |

## Recall by family at each model's fitted threshold (test half)

| family | n | `jeb:4b` | `jevk5:4b` | `snap:2b` |
|---|---|---|---|---|
| hand-written | 9 | 0.53 | 0.53 | 0.18 |

## False blocks by source of `ok` lines at each model's fitted threshold (test half)

| source | n | `jeb:4b` | `jevk5:4b` | `snap:2b` |
|---|---|---|---|---|
| hand-written | 8 | 0 | 0 | 0 |
| generated | 0 | 0 | 0 | 0 |
| oss | 0 | 0 | 0 | 0 |
