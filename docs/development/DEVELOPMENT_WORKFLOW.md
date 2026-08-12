# Development workflow

This documents the actual branching and review workflow this repository uses, as
observed from its git history, and the standard verification commands every change
should pass before being proposed for review.

See also: [CLAUDE_CODE_RULES.md](CLAUDE_CODE_RULES.md) (who is allowed to commit/push/
merge), [MILESTONE_GUIDELINES.md](MILESTONE_GUIDELINES.md) (what belongs in a given
branch's scope).

## Branch flow

```
develop
  -> feature/milestone-N-description
  -> commit
  -> push
  -> pull request
  -> review
  -> user merges to develop
```

This is exactly the pattern this repository's history shows: `main` was merged from
`develop` once (Milestone 1, PR #1), and each subsequent milestone has been developed
on its own `feature/milestone-N-description` branch and merged into `develop` by PR
(`feature/milestone-2-bitbucket-webhooks` -> PR #2 -> `develop`;
`feature/milestone-3-repository-workspace` -> PR #3 -> `develop`). The current branch,
`feature/milestone-4-scanner-runtime`, follows the same pattern and has not yet been
merged.

### Exact example commands

Starting a new milestone branch from `develop`:

```bash
git checkout develop
git pull origin develop
git checkout -b feature/milestone-5-short-description
```

Committing work (only when the user has explicitly asked for a commit -- see
[CLAUDE_CODE_RULES.md](CLAUDE_CODE_RULES.md)):

```bash
git status
git diff --stat
git add <specific files>            # never `git add -A` blindly -- review first
git commit -m "Implement Milestone 5 <short description>"
```

Pushing (only when explicitly asked):

```bash
git push -u origin feature/milestone-5-short-description
```

Opening a pull request (only when explicitly asked; this repository uses GitHub, and
`gh` is the CLI already used for this project):

```bash
gh pr create \
  --base develop \
  --head feature/milestone-5-short-description \
  --title "Implement Milestone 5 <short description>" \
  --body "Summary of scope, requirement compliance, test results."
```

Merging is the user's action, from the GitHub UI or:

```bash
gh pr merge <number> --merge   # or --squash, per the user's stated preference
```

An agent session should never run the `gh pr merge` command itself unless the user has
explicitly asked for it in that session (see
[CLAUDE_CODE_RULES.md](CLAUDE_CODE_RULES.md#4-the-user-performs-the-final-merge)).

## When to create a branch

Create a new `feature/milestone-N-description` branch when starting work on a new
milestone that doesn't yet have one, branching from an up-to-date `develop`. Do not
create a new branch for small follow-up fixes to the milestone currently in progress --
continue on the existing feature branch until it is merged.

## When to commit and push

Commit when a coherent, verified unit of work is complete (e.g., "the scanner registry
and its tests" rather than every individual file edit) **and the user has asked for a
commit**. Push once committed, **and the user has asked for a push**. Never commit
generated artifacts, secrets, or `.env` (see "generated-file cleanup checks" below and
`.gitignore`).

## Only the user performs the final merge

Reviewing a diff, running verification commands, and even opening a pull request are
things an agent session can do when asked. Merging `feature/milestone-N-...` into
`develop`, or `develop` into `main`, is reserved for the user. This applies even if the
PR shows as approved/mergeable.

## Handling uncommitted work

Before starting any new work in a session:

```bash
git status
git diff --stat
```

If uncommitted changes are already present, they represent unfinished work from a
prior session (or the user's own local edits) and must be preserved, not discarded or
overwritten. Read them, understand what they're for, and build on top of them rather
than resetting the tree. If continuing that work isn't the current task, leave the
changes in place and proceed with the new task alongside them -- don't stash or revert
them without being asked to.

## Generated-file cleanup checks

Before staging anything, confirm no generated or transient files have snuck into the
change set. Concretely, in this repository:

```bash
git status --porcelain | grep -E "__pycache__|\.pyc$|\.egg-info|\.pytest_cache|\.ruff_cache|\.DS_Store"
```

This should print nothing -- all of those paths are already covered by `.gitignore`
(`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`,
`.DS_Store`), but a manual check catches anything that ends up tracked anyway (e.g., if
`.gitignore` is edited incorrectly, or a file was force-added in the past). Also
confirm `.env` itself was never staged (`.gitignore` excludes it, but
`git status --porcelain | grep -E "^\?\? \.env$|^A  \.env$"` should be empty) --
`.env.example` is the only environment file meant to be committed.

## Standard verification commands

Run these before reporting any task complete, and before proposing a commit for
review:

```bash
ruff check .
pyright
pytest -q
docker compose config
git diff --check
git status
```

- `ruff check .` -- lint (see `[tool.ruff]` in `pyproject.toml`).
- `pyright` -- static type check (`[tool.pyright]` in `pyproject.toml`).
- `pytest -q` -- full test suite (`[tool.pytest.ini_options]` in `pyproject.toml`;
  `testpaths = ["tests"]`).
- `docker compose config` -- validates `docker-compose.yml` resolves correctly without
  needing the containers to actually be running.
- `git diff --check` -- flags whitespace errors (trailing whitespace, conflict
  markers) in the diff; run this against whatever is currently staged/unstaged.
- `git status` -- confirms exactly what would be committed/pushed, and that nothing
  unexpected (generated files, unrelated changes) is present.

See [MILESTONE_GUIDELINES.md](MILESTONE_GUIDELINES.md#milestone-completion-checklist)
for how these fit into completing a milestone, and
[sessions/DEVELOPMENT_CHECKLIST.md](../../sessions/DEVELOPMENT_CHECKLIST.md) for a
checkbox version of the whole workflow.
