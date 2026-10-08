# Using smart-commit-guard in CI

The hook runs on each developer's machine; CI is the backstop that catches `git commit --no-verify` and a hook that was never installed. Back to the [README](../README.md).

CI is the backstop: it catches `git commit --no-verify` and ignores `SKIP_SECRET_GUARD`. A GitHub Actions example
(no model in CI: rule hits block, ambiguous candidates only warn):

```yaml
name: Secret scan
on:
  push:
    branches: [main]
  pull_request:

jobs:
  smart-commit-guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0          # the diff scan needs the base branch
      - uses: astral-sh/setup-uv@v10
      - name: Scan the pull request's added lines
        if: github.event_name == 'pull_request'
        run: uvx --from 'smart-commit-guard>=0.3,<0.4' smart-commit-guard scan --no-model --diff "origin/${{ github.base_ref }}...HEAD"
      - name: Scan the whole tree
        if: github.event_name == 'push'
        run: uvx --from 'smart-commit-guard>=0.3,<0.4' smart-commit-guard scan --no-model --all
```

CI can also use the SARIF format for GitHub code scanning, `--all` instead of
`--files $(git ls-files)` (which hits the argument-length limit on large repos), and `--config-from origin/main` so a pull
request cannot change its own skip list. A GitHub Actions run prints findings as inline annotations on its own.

```yaml
      - run: uvx --from 'smart-commit-guard>=0.3,<0.4' smart-commit-guard scan --no-model --all
      - run: uvx --from 'smart-commit-guard>=0.3,<0.4' smart-commit-guard scan --no-model --diff "origin/${{ github.base_ref }}...HEAD" --config-from "origin/${{ github.base_ref }}" --format sarif > results.sarif
```

### Commit messages

Secrets also leak through commit messages (`git commit -m "debugging with AKIA..."`), and a message is permanent once pushed.
The `commit-msg` hook runs `scan --message` on the message; for the CI backstop add `--messages` to a diff scan, which also
scans the message of every commit in the range (it catches `--no-verify`, a hook that was never installed, and the message
GitHub builds for a squash merge):

```yaml
      - run: uvx --from 'smart-commit-guard>=0.3,<0.4' smart-commit-guard scan --no-model --diff "origin/${{ github.base_ref }}...HEAD" --messages
      # a pull request title and body are not commits: pipe them in
      - run: printf '%s\n%s\n' "$TITLE" "$BODY" | uvx --from 'smart-commit-guard>=0.3,<0.4' smart-commit-guard scan --text -
        env:
          TITLE: ${{ github.event.pull_request.title }}
          BODY: ${{ github.event.pull_request.body }}
```

Messages follow different rules than code: **rule hits block** (AWS keys, tokens, private keys, connection strings), but
candidates (`the password is ...`) **only warn**, and the model is never called, because prose is too noisy to block on a score.
When a message is blocked, git keeps it in `.git/COMMIT_EDITMSG`; fix it and run `git commit -e -F .git/COMMIT_EDITMSG`. Text
below the `-v` scissors line (the diff) is not scanned as message text, comment lines are. `SKIP_SECRET_GUARD=1` skips the message
hook too, and so does `# smart-commit-guard: allow` on a line when `allow_inline = true`.

### Hosted model in CI only

CI runs on a server your team already trusts with the code, while a commit hook runs on a laptop with work in progress. To
use a hosted model only in CI, keep the hook on rules and set the scope (the repo file can only narrow it):

```toml
# .secret-guard.toml
[model]
hosted_scope = "ci"      # the commit hook never calls a hosted model; ambiguous candidates only warn there
```

In the workflow, run the scan without `--no-model` and give it the endpoint and the key from repository secrets (CI has no settings file, so
it uses environment variables):

```yaml
      - name: Scan the pull request's added lines (hosted model)
        env:
          SECRET_GUARD_BASE_URL: ${{ secrets.SECRET_GUARD_BASE_URL }}   # https only
          SECRET_GUARD_ALLOW_HOSTED: "1"
          SECRET_GUARD_API_KEY: ${{ secrets.SECRET_GUARD_API_KEY }}
        run: uvx --from 'smart-commit-guard>=0.3,<0.4' smart-commit-guard scan --diff "origin/${{ github.base_ref }}...HEAD"
```

`scan --files` and `--all` count as CI too, even when run locally.

### Push events

To scan what a push added instead of the whole tree, use the range from the event. For a new branch GitHub sends an all-zero
`before`; that is handled (the whole branch is scanned):

```yaml
      - run: uvx --from 'smart-commit-guard>=0.3,<0.4' smart-commit-guard scan --no-model --diff "${{ github.event.before }}...${{ github.sha }}"
```

Check out with `fetch-depth: 0`. After a force-push the old `before` commit can be gone; scan the branch against its base then.
