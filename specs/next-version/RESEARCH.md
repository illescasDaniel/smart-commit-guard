# What similar tools do, and what we took from them

Researched 2026-10-05 from the projects' own READMEs and a few summary articles (links at the end). The tools differ in goal:
they are pattern or verification scanners, while smart-commit-guard adds a small decision model for ambiguous cases. Ideas are
sorted by what we did with them.

## Adopted (implemented in 0.2.0)
| Idea | From | What we did |
|---|---|---|
| Baseline file: record today's findings, fail only on new ones | detect-secrets (`.secrets.baseline`), gitleaks (`--baseline-path`) | `baseline create`, `scan --baseline` |
| Inline allow marker on a line | gitleaks `#gitleaks:allow`, detect-secrets `# pragma: allowlist secret` | `allow_inline = true`; the other tools' markers are accepted too, so migrating costs nothing |
| Allow entries by fingerprint, with a reason | gitleaks `.gitleaksignore`, detect-secrets audit labels | `[[allow]]` with a required `reason`, optional `path` glob |
| Decode encoded secrets before matching | gitleaks (percent, hex, base64, recursive), Betterleaks (doubly/triply encoded) | base64 tokens are decoded (2 levels) and checked against the known secret shapes; catches Kubernetes `Secret` data and encoded keys |
| Heuristic filters for "typed by a person" values | detect-secrets (sequential strings, UUIDs, templated values, lock files) | sequential and repeated values (`abcdef...`, `123456...`, `aaaa...`) are placeholders; UUIDs and hash lines were already handled |
| Skip lockfiles by default but not blindly | detect-secrets, Talisman (`scopeconfig`) | rules-only for lockfiles and generated files |
| Chain with the hooks a project already has | pre-commit framework, husky | `install-hook --chain`, `.pre-commit-hooks.yaml`, `action.yml` |
| SARIF and CI annotations | gitleaks (SARIF, JUnit), ggshield | `--format sarif`, GitHub annotations |
| Push events: scan the pushed range | trufflehog `--since-commit`, gitleaks `--log-opts` | `--diff before..sha`, with the all-zero `before` of a new branch handled |

## Not adopted, with the reason
- **Live verification of a secret against the provider's API** (TruffleHog: `GetCallerIdentity` for AWS, 800+ detectors, states
  verified / unverified / unknown). It removes most false positives, but it sends the candidate secret to a third party and tests
  it, which conflicts with "nothing leaves the machine". If ever added: opt-in per detector, CI only, never in the hook.
- **A bigger rule set** (gitleaks about 150 rules, TruffleHog 800+, ggshield 500+). We keep a small, tested table plus the model
  for the ambiguous rest. A cheap way to grow it safely is to import gitleaks' public rule TOML as a test corpus (positive
  examples only) and see which shapes we miss.
- **History scanning** (git-secrets `--scan-history`, gitleaks, TruffleHog). Out of scope in the spec; `--diff A..B` covers a range.
- **Archive scanning, S3 / Docker / Slack sources** (gitleaks, TruffleHog, ggshield). Different product.
- **Cloud API and dashboards** (ggshield). We have no server.
- **Talisman's content-checksum ignore** ("ignore this file until its content changes"). Our fingerprints already bind an entry to
  the path and the masked line shape, so a changed secret on the same line shape stays allowed; a checksum would be stricter.
  Worth reconsidering if reviewers ask for "allow this exact content only".

## Done since
- **`commit-msg` scanning** (git-secrets installs `commit-msg` and `prepare-commit-msg` hooks): `scan --message`, the
  `commit-msg` hook, `--diff --messages` and `--text -` for CI. Rule hits block, candidates only warn.
  **TODO(local):** measure the false-warning rate on the messages of real repositories before considering a model for messages.

## Ideas worth doing next (need a decision)
1. **Global install through the git template directory** (git-secrets `init.templateDir`): every new clone gets the hook with no
   per-repo step. A `install-hook --global` would remove the "each clone runs once" gap in the README.
2. **`pre-push` hook** (Talisman, ggshield): scans the commits being pushed, which also covers commits made with
   `--no-verify`. `scan --diff` already does the work; the hook only has to read git's stdin refs.
3. **Per-rule stopwords and path allowlists** (gitleaks rule allowlists, `stopwords`): finer than the global `skip`.
4. **Severity levels and a threshold** (Talisman low / medium / high): lets a team block only on high.
5. **BPE "token efficiency" instead of entropy** (Betterleaks reports 98.6% recall versus 70.4% for entropy on the CredData
   dataset). Our entropy checks are only used for the literal and preview-masking heuristics, but this is a cheap-to-test
   upgrade; needs a tokenizer vocabulary (a dependency or a vendored table) and the CredData benchmark. **TODO(local):** measure.
6. **Rule-defined validation** (Betterleaks CEL) and **LLM-assisted analysis** (listed on Betterleaks' roadmap): the closest
   neighbour to what this project already does; worth watching, and a reason to publish our eval numbers.
7. **Audit mode** (`detect-secrets audit`): interactively label each baseline entry real or false positive. Could feed our eval
   sets with real-world labelled lines (**TODO(local)**).
8. **Honeytokens** (ggshield): planted fake credentials that alert when used. Out of scope, but a fake-secret fixture helps
   `doctor` prove the gate end to end.

## Sources
- [gitleaks](https://github.com/gitleaks/gitleaks), [Betterleaks announcement](https://bleepingcomputer.com/news/security/betterleaks-a-new-open-source-secrets-scanner-to-replace-gitleaks)
- [detect-secrets](https://github.com/Yelp/detect-secrets), [TruffleHog](https://github.com/trufflesecurity/trufflehog)
- [Talisman](https://github.com/thoughtworks/talisman), [git-secrets](https://github.com/awslabs/git-secrets), [ggshield](https://github.com/GitGuardian/ggshield)
- [gitleaks vs trufflehog](https://appsecsanta.com/secret-scanning-tools/gitleaks-vs-trufflehog)
