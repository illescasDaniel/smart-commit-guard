# Choosing a model

A decision model judges the ambiguous candidates (`DB_PASS = "Winter2026!Admin"` real, `API_KEY = "your-api-key-here"` placeholder). You need **one** of:

1. **A local model (the default).** The tool talks to a local server that speaks the `POST /v1/systemone` API, and the default model is
   `jevk5:4b`, served by **ollaya**: pull the model and keep the server running (it listens on `http://localhost:11435`):

   ```bash
   ollaya pull jevk5:4b
   ollaya serve            # or run it as a service
   smart-commit-guard doctor   # "ok    model: jevk5:4b at http://localhost:11435"
   ```

   It needs about 5.5 GB of GPU memory and answers in about 80 ms. Nothing leaves your machine. No settings file is needed for this.
2. **A hosted model.** For example TypeSafe Jev: create a key at `console.typesafe.ai/settings/keys`, export it
   (`export TYPESAFE_API_KEY=...`), run `smart-commit-guard config init` and uncomment the hosted block in the file it writes
   (`base_url` `https://api.typesafe.ai`, `model` `jev-latest`, `allow_hosted`, `api_key_env`). Candidate lines are sent **unmasked**,
   so read [Privacy](#privacy), and consider `"hosted_scope": "ci"` so only CI calls it.
3. **No model.** Rules only (`--no-model`): rule hits block, ambiguous candidates only warn.

Back to the [README](../README.md).


## Your settings file: choosing a model

The model is a per-user choice, so it lives outside every repository. Run `smart-commit-guard config init` once; it writes
`~/.config/smart-commit-guard/config.jsonc` (mode 600) with the default and the hosted-model settings as comments. The file is
JSON with comments (`//` and `/* */`). `config path` prints its location: `$XDG_CONFIG_HOME/smart-commit-guard/` if set,
`%APPDATA%\smart-commit-guard\` on Windows, or the path in `SECRET_GUARD_CONFIG`. An existing `config.json` is read too.

```jsonc
{
	// The default: a local ollaya server. Nothing leaves your machine.
	"base_url": "http://localhost:11435",
	"model": "jevk5:4b"

	// A hosted model (candidate lines are sent UNMASKED: only use a server you would trust with the secrets):
	//   "base_url": "https://api.typesafe.ai",
	//   "model": "jev-latest",
	//   "allow_hosted": true,
	//   "api_key_env": "TYPESAFE_API_KEY",     // the NAME of an environment variable that holds the key
	//   "hosted_scope": "ci"                   // the commit hook never calls it; CI does
}
```

Keys: `base_url`, `model`, `api_key`, `api_key_env`, `timeout`, `allow_hosted`, `hosted_scope`, `budget`, `block_at`, `warn_at`
(same meaning as the variables below). Prefer `api_key_env` to `api_key`: the key then never sits in a file, and a file that
holds a key and is readable by others gets a warning.

**Precedence, per setting:** environment variable, then this file, then the repo's `[model]` table (model name and thresholds
only), then the default. Only this file and the environment can name a server or a key; the repo file never can, so a pull
request cannot send your diff somewhere. "Environment variable" means a real one that you export (in your shell profile, a CI
`env:` block...). **A `.env` file is never read.** (This repo's `.env` / `.env.example` are only for its own eval scripts.)

## Environment variables

Each of these overrides the same setting in your settings file.

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_GUARD_BASE_URL` | `http://localhost:11435` | model server |
| `SECRET_GUARD_MODEL` | `jevk5:4b` | model name sent to the server |
| `SECRET_GUARD_API_KEY` | unset | Bearer token, only if the server wants one |
| `SECRET_GUARD_TIMEOUT` | `10` | seconds per model call (must be > 0) |
| `SECRET_GUARD_BLOCK_AT` / `SECRET_GUARD_WARN_AT` | `0.5` / `0.4` | thresholds, see [Other models](#other-models) |
| `SECRET_GUARD_ALLOW_HOSTED` | unset | must be `1` to use a non-local URL, see [Privacy](#privacy); hosted URLs must be `https` |
| `SECRET_GUARD_HOSTED_SCOPE` | `all` | `ci` keeps a hosted model out of the commit hook (`scan --staged`); `[model] hosted_scope` in `.secret-guard.toml` can only narrow it |
| `SECRET_GUARD_BUDGET` | `5` for `--staged`, `120` otherwise | total seconds of model time per scan; candidates left over only warn |
| `SECRET_GUARD_ALLOW_INSECURE` | unset | `1` allows an `http://` hosted URL on a network you fully control |
| `SMART_COMMIT_GUARD_DEBUG` | unset | `1` prints the traceback of an unexpected error |
| `SKIP_SECRET_GUARD` | unset | `1` bypasses the commit hook once, see [project-config.md](project-config.md) |

## Other models

Thresholds are calibrated per model. On 1,056 labelled lines that reach the model (356 real, 700 not; synthetic cases split by
template, plus real lines from 95 open-source packages), with thresholds fitted on one half and scored on the other:

| model | AUC | recall | false blocks | median call | GPU memory |
|---|---|---|---|---|---|
| `jevk5:4b` (default) | 0.998 | 0.98 | 1.6 % | 82 ms | 5.6 GB |
| `jeb:4b` | 0.994 | 0.99 | 3.6 % | 75 ms | 5.3 GB |
| `snap:2b` | 0.855 | 0.61 | 5.2 % | 43 ms | 3.1 GB |
| hosted TypeSafe `jev-latest` | 1.000 (60 lines only) | 1.00 | 0 | 242 ms | none |

At the defaults (block 0.5, warn 0.4) `jevk5:4b` has recall 0.97 and 1 % false blocks on that set. The cases are mostly synthetic, so
treat the numbers as optimistic for real code. The full report, per-model thresholds (`evals/thresholds.json`) and prompt
experiments are in [`specs/next-version/MODEL_COMPARISON.md`](specs/next-version/MODEL_COMPARISON.md). For another model, rerun
the comparison and set `block_at` / `warn_at` for it in your settings file:

```bash
uv run python evals/compare_models.py run MODEL && uv run python evals/compare_models.py report
```

## Privacy

The staged diff may contain real secrets, so the default backend is **local** and nothing is sent anywhere else.

- A non-local `SECRET_GUARD_BASE_URL` is refused (exit 2) unless `SECRET_GUARD_ALLOW_HOSTED=1`, and it must be `https`.
- **A hosted backend receives the candidate lines unmasked**: the model has to see the real value to judge it, and a masked
  value carries too little signal. Only use a hosted backend you would trust with the secrets themselves (for example a
  server you host on your own network), or limit it to CI with `SECRET_GUARD_HOSTED_SCOPE=ci`.
- Only candidate lines are sent (a window of about 300 characters around the candidate for very long lines), never whole
  files or the full diff. Lines that the rules already block are never sent.
- Local model calls ignore `HTTP_PROXY`/`HTTPS_PROXY`, so an unmasked line never goes through a corporate proxy on its way to
  `localhost`. Hosted calls honour them. Redirects are never followed.
- Everything printed (terminal, `--json`, SARIF, the skips log, allowlist fingerprints) is masked. No telemetry.
