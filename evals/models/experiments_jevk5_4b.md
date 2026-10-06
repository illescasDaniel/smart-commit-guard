# Prompt experiments on `jevk5:4b` (1056 lines)

| variant | AUC test [95 %] | threshold | recall test | false blocks test | ECE (all) |
|---|---|---|---|---|---|
| baseline | 0.998 [0.996, 1.000] | 0.45 | 0.977 | 0.016 | 0.098 |
| no_criteria | 0.999 [0.997, 1.000] | 0.39 | 0.989 | 0.020 | 0.108 |
| path | 0.998 [0.996, 1.000] | 0.44 | 0.977 | 0.013 | 0.090 |
| context | 0.999 [0.998, 1.000] | 0.42 | 0.983 | 0.033 | 0.101 |
