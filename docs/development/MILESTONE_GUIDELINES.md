# Milestone guidelines

How this project defines, scopes, and completes a milestone, based on how Milestones 1
through 4 were actually run.

See also: [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) (what exists through the
current milestone), [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md) (branch/PR
flow), [PROJECT_STATE.md](../../PROJECT_STATE.md) (the current milestone's live
status).

## Milestone boundaries

Each milestone in this project has shipped as a single, narrowly-scoped, independently
reviewable increment:

| Milestone | Scope |
|-----------|-------|
| 1 | Platform foundation: FastAPI app, typed config, async PostgreSQL/Redis, Alembic, domain models, Docker Compose. |
| 2 | Bitbucket webhook ingestion, SCM provider abstraction, signature validation, idempotency, persistence -- no scanning, no merge decisions. |
| 3 | Provider-agnostic repository workspace: secure clone/fetch of the exact source commit, diff generation, cleanup -- no scanning yet. |
| 4 | Provider-agnostic scanner runtime: six scanner adapters, normalized findings, isolated/sandboxed execution -- no baseline comparison, no merge policy, no status publishing, no notifications, no LLM. |

Each milestone's own `docs/architecture/milestone-N.md` states explicitly, in its
"Scope" section, what it does *not* do -- usually naming the very next milestone by
number. That's a deliberate pattern: **the boundary of a milestone is defined as much
by what it excludes as by what it includes.**

## Require a clear scope and acceptance criteria before development

Before writing code for a milestone, make sure you can state, in the same terms the
existing architecture docs use:

- What the milestone must implement (a short list, not a paragraph).
- What it must explicitly **not** implement yet (name the excluded functionality, not
  just "later").
- What security/behavioral requirements apply (this project has consistently paired
  functional requirements with an explicit security requirements list -- see
  Milestone 3's and Milestone 4's architecture docs).
- What "done" looks like in verifiable terms (a specific test list, specific
  requirement compliance table -- not "it works").

If any of this is unclear from the user's instructions, ask before starting
significant implementation work, rather than guessing scope.

## Do not implement later-milestone functionality early

This has been enforced milestone over milestone in this repository: Milestone 2's
webhook service creates a `WorkflowRun` row but does not clone anything or run
scanners. Milestone 3's workspace service produces a checked-out commit and diff but
does not scan it. Milestone 4's scanner runtime produces normalized findings but does
not compare them to a baseline, decide a merge policy, publish a status check, send a
notification, or call an LLM -- and does not write `ScanRun`/`Finding` rows to the
database, even though those tables already exist (they were created in Milestone 1
specifically *for* a later milestone to use). Resist the temptation to "finish the
loop" early; a milestone that quietly absorbs the next one's scope makes both harder to
review independently.

## Required before/alongside development

For each milestone:

- **Architecture notes**: add or update `docs/architecture/milestone-N.md` describing
  scope, components, and security notes -- follow the existing milestones' structure
  and level of detail. Never rewrite a *previous* milestone's architecture doc to
  describe new behavior; add a new one.
- **Tests**: unit and (where applicable) integration tests covering the new
  functionality, including negative/failure cases, not just the happy path (see how
  Milestone 3's and 4's test suites cover timeout, malformed output, path-traversal
  rejection, and secret redaction, not just successful runs).
- **Configuration updates**: new settings belong in `src/protecto_prime_agent/config.py`
  (a `Settings` field with a sensible default) and `.env.example` (with the same
  default, never a real secret).
- **README updates**: add a bullet to `README.md`'s notes section summarizing what the
  milestone added, and link to its architecture doc.
- **Deployment impact review**: check whether the milestone changes
  `docker-compose.yml`, `Dockerfile`, environment variables, or anything documented in
  [docs/deployment/](../deployment/) or [docs/operations/](../operations/), and update
  those documents in the same change -- don't let deployment docs drift from what the
  code actually does.

## Milestone completion checklist

- [ ] Scope matches what was actually requested (no less, no more).
- [ ] No later-milestone functionality was implemented.
- [ ] `docs/architecture/milestone-N.md` exists/updated for this milestone.
- [ ] New/changed configuration is in `config.py` and `.env.example`, documented in
      [docs/deployment/ENVIRONMENT_VARIABLES.md](../deployment/ENVIRONMENT_VARIABLES.md).
- [ ] `README.md` mentions the milestone and links to its architecture doc.
- [ ] Deployment/operations docs reviewed for impact and updated if needed.
- [ ] Unit tests added for new functionality, including failure/negative cases.
- [ ] `ruff check .`, `pyright`, `pytest -q`, `docker compose config` all pass (see
      [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md#standard-verification-commands)).
- [ ] `git status` reviewed -- no generated files, no secrets, nothing unrelated staged.
- [ ] Requirement compliance table completed (below).
- [ ] Remaining risks documented (below).
- [ ] Handover written before starting the next milestone (below).

## Requirement compliance table template

Fill this in for every milestone, mirroring the format already used in this project's
milestone reports:

| # | Requirement | Status | Notes |
|---|---|---|---|
| 1 | *(requirement as stated)* | ✅ / ⚠️ / ❌ | *(what was done, or why not)* |
| 2 | ... | | |

Use ✅ for fully met, ⚠️ for partially met or met with a caveat (explain the caveat),
❌ for not met (explain why, and whether that's expected/deferred).

## Remaining risks section

Every milestone report should end with an explicit, named list of what is *not* fully
solved -- known limitations, deferred hardening, or things that only work under
certain conditions. This project's existing architecture docs do this well; e.g.
Milestone 4's "Remaining risks / known limitations" names that scanner container
images aren't built yet, that pip-audit needs network access, and that gitleaks isn't
pip-installable. Don't omit this section because everything "looks done" -- the point
is to surface what a reviewer or the next session needs to know.

## Handover process before starting the next milestone

Before beginning work on the next milestone, produce a handover using
[sessions/HANDOVER_TEMPLATE.md](../../sessions/HANDOVER_TEMPLATE.md) and make sure
[PROJECT_STATE.md](../../PROJECT_STATE.md) reflects the just-completed milestone's real,
verified status (not an aspirational one). A new session should be able to read
`PROJECT_STATE.md` and the latest handover and know, without re-deriving it from
scratch: what branch it's on, what's done, what's uncommitted, and what to do next.
