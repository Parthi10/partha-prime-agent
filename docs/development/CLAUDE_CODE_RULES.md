# Claude Code rules for this repository

These are durable, non-negotiable operating rules for any AI coding session (Claude
Code or otherwise) working in this repository. They apply regardless of which
milestone is in progress. If a user instruction and this document conflict, the
explicit, in-session instruction from the user wins for that session -- but absent an
explicit instruction, these rules are the default.

See also: [sessions/SESSION_PROMPT.md](../../sessions/SESSION_PROMPT.md) (the prompt
that opens a session with these rules in effect) and
[PROJECT_STATE.md](../../PROJECT_STATE.md) (what to read first, every session).

## 1. Never discard existing work

Existing uncommitted work in the working tree -- staged or unstaged -- must never be
discarded. Before touching anything, run `git status` and `git diff` (or `git diff
--stat`) and understand what is already there. If it's unclear whether an existing
uncommitted change is intentional work-in-progress or stray output, treat it as
work-in-progress and preserve it.

## 2. Never reset, restore, overwrite, or delete without explicit approval

Do not run `git reset --hard`, `git checkout -- <path>`, `git restore`, `git clean
-fd`, or any other destructive/history-rewriting command against existing work unless
the user has explicitly asked for that specific action in the current session. This
includes deleting files that look unrelated, unfamiliar, or "probably generated" --
investigate first (see [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md)'s
"generated-file cleanup checks"), don't assume and delete.

## 3. Never commit, push, open a pull request, or merge unless explicitly asked

Making changes to files is expected. Committing them, pushing them, opening a pull
request, or merging is a separate, explicit action that requires the user to ask for
it in that session. A prior session's approval does not carry forward. When in doubt,
stop and describe what you would commit/push/open, and wait.

## 4. The user performs the final merge

Even when a pull request exists and has been reviewed, the agent does not merge it.
Merging `feature/milestone-N-...` into `develop` (and, later, `develop` into `main`) is
the user's action alone. See
[DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md#branch-flow).

## 5. Work only on the current approved milestone

Implement what the current milestone's requirements describe -- no more. Do not add
functionality that belongs to a later milestone "while you're in there," even if it
would be convenient or the code is adjacent. See
[MILESTONE_GUIDELINES.md](MILESTONE_GUIDELINES.md) for how milestone boundaries are
defined and verified in this project (e.g. Milestone 4's scanner runtime explicitly
does not implement baseline comparison, merge policy/blocking, status publishing,
notifications, or LLM functionality -- those are later milestones, and every
Milestone 4 architecture note says so explicitly).

## 6. Do not implement future milestones

If a future milestone's functionality would be a natural extension of current work
(e.g., wiring the Milestone 4 scanner runtime into an end-to-end orchestrator, or
persisting `NormalizedFinding` to the `Finding` table), leave it undone and say so in
your report. Note it as a "next recommended step" (see
[sessions/HANDOVER_TEMPLATE.md](../../sessions/HANDOVER_TEMPLATE.md)) rather than
building it preemptively.

## 7. Read the repository and existing documents before making changes

Before writing code or documentation, review: `PROJECT_STATE.md`, the current branch's
`git status`/`git log`, the relevant `docs/architecture/milestone-N.md`, `README.md`,
and the actual source files you're about to touch or document. Documentation and code
must describe what the repository actually contains -- never invent commands, files,
services, migrations, or features that don't exist.

## 8. Run the required verification commands before reporting completion

Before telling the user a task is done, run (and report the results of):

```bash
ruff check .
pyright
pytest -q
docker compose config
git status
```

If the task also touches the working tree's tracked line endings/whitespace, also run
`git diff --check`. See
[DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md#standard-verification-commands) for
the full standard set. Do not claim tests pass, lint is clean, or the container config
is valid without having actually run these in the current session.

## 9. Never expose, persist, or log credentials or access tokens

This repository has concrete, tested controls for this (see
[docs/architecture/milestone-3.md](../architecture/milestone-3.md)'s ephemeral
`GIT_ASKPASS` mechanism and `redact_secrets`, and
[docs/architecture/milestone-4.md](../architecture/milestone-4.md)'s `build_minimal_env`
allowlist and `sanitize_text`). Any new code must uphold the same standard: never write
a secret to a file that isn't immediately and reliably cleaned up, never include a
secret in a log line, exception message, audit record, or committed file, and never add
a real credential to an example, `.env.example`, or documentation.

## 10. Never execute untrusted repository code

When working with or extending the scanner runtime or repository workspace service,
never run a scanned/cloned repository's own code: no test suite, no setup script, no
`Makefile` target, no migration, no application startup command. Every scanner adapter
and the workspace service's git command list is a fixed, hand-written template --
never templated from repository content. Preserve this property in any change.

## 11. Never install dependencies from a repository being scanned

Do not add a `pip install -r requirements.txt`, `npm install`, or equivalent step
anywhere in the scan or clone path. `pip-audit` in particular reads dependency pins to
query a vulnerability database -- it must never be used to actually install the
audited packages.

## 12. Clearly report assumptions, risks, test results, and remaining gaps

Every session's final report to the user should state, plainly: what was assumed (if
anything was ambiguous), what could go wrong or is not yet covered (risks/gaps), the
exact test command output and count, and what remains to be done. Do not round up
partial completion to "done." See
[sessions/HANDOVER_TEMPLATE.md](../../sessions/HANDOVER_TEMPLATE.md) for the exact
structure expected at the end of a session.
