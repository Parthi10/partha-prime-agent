# Development checklist

A checkbox-form companion to
[../docs/development/DEVELOPMENT_WORKFLOW.md](../docs/development/DEVELOPMENT_WORKFLOW.md)
and [../docs/development/MILESTONE_GUIDELINES.md](../docs/development/MILESTONE_GUIDELINES.md).
Copy this into a session's working notes (or a PR description) and check items off as
they're actually done -- don't check something off preemptively.

## Before starting

- [ ] **Branch check** -- `git branch --show-current` matches what
      `PROJECT_STATE.md`/the session prompt says it should be.
- [ ] **Status check** -- `git status` and `git diff --stat` reviewed; any existing
      uncommitted work identified and understood (not discarded).
- [ ] **Scope review** -- the current milestone's requirements are understood as a
      concrete list, including what is explicitly out of scope (see
      [../docs/development/MILESTONE_GUIDELINES.md](../docs/development/MILESTONE_GUIDELINES.md#require-a-clear-scope-and-acceptance-criteria-before-development)).
- [ ] **Architecture review** -- relevant existing code and
      `docs/development/PROJECT_ARCHITECTURE.md` / `docs/architecture/milestone-N.md`
      read before writing new code, so new work is consistent with what exists.

## During implementation

- [ ] **Implementation** -- matches the reviewed scope; no later-milestone
      functionality included.
- [ ] **Security review** -- credentials/tokens never logged or persisted; no
      untrusted repository code executed; no repository dependencies installed as
      part of a clone or scan (see
      [../docs/development/CLAUDE_CODE_RULES.md](../docs/development/CLAUDE_CODE_RULES.md)).
- [ ] **Unit tests** -- added for new functionality, including failure/negative cases.
- [ ] **Integration tests** -- added where applicable (e.g. real local git
      repositories, real installed scanner binaries) -- not just mocked happy paths.
- [ ] **Documentation** -- `docs/architecture/milestone-N.md` updated/created;
      `README.md` notes updated; any new deployment/operations impact reflected in
      `docs/deployment/` / `docs/operations/`.
- [ ] **Environment variables** -- new settings added to `config.py` and
      `.env.example` with safe defaults, and documented in
      `docs/deployment/ENVIRONMENT_VARIABLES.md`.

## Before reporting complete / before proposing a commit

- [ ] **Lint** -- `ruff check .` passes.
- [ ] **Type check** -- `pyright` passes.
- [ ] **Tests** -- `pytest -q` passes; exact pass count recorded (not approximated).
- [ ] **Docker validation** -- `docker compose config` succeeds.
- [ ] **Generated-file check** --
      `git status --porcelain | grep -E "__pycache__|\.pyc$|\.egg-info|\.pytest_cache|\.ruff_cache|\.DS_Store"`
      prints nothing; `.env` was never staged.
- [ ] **Diff review** -- `git diff --check` clean (no whitespace errors/conflict
      markers); `git diff --stat` / `git status` manually reviewed for anything
      unexpected or unrelated to the task.

## Before any git action beyond local edits

- [ ] **Commit approval** -- the user has explicitly asked for a commit in this
      session.
- [ ] **Push approval** -- the user has explicitly asked for a push in this session.
- [ ] **PR review** -- if a pull request is opened, its description states scope,
      requirement compliance, and test results plainly (see
      [../docs/development/MILESTONE_GUIDELINES.md](../docs/development/MILESTONE_GUIDELINES.md#requirement-compliance-table-template)).
- [ ] **User merge** -- confirmed the agent did not merge the PR; merging
      `feature/milestone-N-...` into `develop` (or `develop` into `main`) is the
      user's action alone (see
      [../docs/development/CLAUDE_CODE_RULES.md](../docs/development/CLAUDE_CODE_RULES.md#4-the-user-performs-the-final-merge)).

## Before ending the session

- [ ] [HANDOVER_TEMPLATE.md](HANDOVER_TEMPLATE.md) filled in.
- [ ] `PROJECT_STATE.md` updated to reflect the real, verified current state (not an
      aspirational one).
