# Project state

**Read this file first, before anything else, at the start of every session.** It is
the single source of truth for where this project actually stands. If anything here
conflicts with what you observe in the repository (`git status`, `git log`, running
the tests), trust what you observe and update this file -- don't trust a stale
description over the real repository state.

Last verified: this session, on `feature/milestone-5-scan-orchestration`, via
`ruff check .`, `pyright`, `pytest -q`, and `docker compose config` (see "Latest
verified test count" below for exact numbers).

## Project name

Protecto Prime Agent -- an internal PR review platform: webhook ingestion from GitHub/
Bitbucket, secure repository workspace preparation, and a static-analysis scanner
runtime, built on FastAPI, PostgreSQL, Redis, and Docker Compose.

## Current completed milestones

| Milestone | Status | Where |
|---|---|---|
| 1 -- Platform foundation | Merged to `develop` (and to `main` via PR #1) | `docs/architecture/v1.md` (currently an empty placeholder file) |
| 2 -- Bitbucket webhook ingestion | Merged to `develop` (PR #2) | `docs/architecture/milestone-2.md` |
| 3 -- Repository workspace (secure clone/fetch) | Merged to `develop` (PR #3) | `docs/architecture/milestone-3.md` |
| 4 -- Scanner runtime | Committed directly to `develop` (`8d7b832`) -- no feature-branch PR exists for it, since `develop`'s tip already matched `feature/milestone-4-scanner-runtime` when this was discovered. Included in PR #4 (open, unmerged as of this writing). | `docs/architecture/milestone-4.md` |
| 5 -- Scan orchestration | **Implemented and locally verified on `feature/milestone-5-scan-orchestration`; NOT yet committed** | `docs/architecture/milestone-5.md` |

## Current milestone and status

**Milestone 5: Scan Orchestration -- implemented, locally verified, not yet committed.**

`ScanOrchestrationService` (`src/protecto_prime_agent/services/scan_orchestration_service.py`)
wires the previously-independent webhook (Milestone 2), workspace (Milestone 3), and
scanner runtime (Milestone 4) components together end-to-end: when a webhook is
accepted, `WebhookService` now schedules orchestration as a FastAPI background task,
which prepares the workspace, runs the scanner runtime, and persists results to
`ScanRun`/`Finding`. Full detail, including why background tasks (not a message queue)
and the exact status-transition/failure-handling model:
[docs/architecture/milestone-5.md](docs/architecture/milestone-5.md).

**None of this is committed yet.** `git status` on
`feature/milestone-5-scan-orchestration` shows it all as modified/untracked changes in
the working tree. Files touched this session:

- New: `src/protecto_prime_agent/services/scan_orchestration_service.py`,
  `tests/test_scan_orchestration_service.py`, `docs/architecture/milestone-5.md`.
- Modified: `src/protecto_prime_agent/services/webhook_service.py` (accepts
  `background_tasks`/`orchestrator`, schedules orchestration after an accepted
  webhook), `src/protecto_prime_agent/api/v1/webhooks.py` (both endpoints now take
  and forward FastAPI's injected `BackgroundTasks`), `tests/test_bitbucket_webhook.py`
  (the one router-level HTTP test now mocks `ScanOrchestrationService`),
  `tests/test_webhook_persistence.py` (3 new tests covering scheduling behavior),
  `README.md`, `docs/development/PROJECT_ARCHITECTURE.md` (diagram, "not yet
  implemented" list, and new orchestration section updated).

Explicitly out of scope for this milestone (per
[docs/development/MILESTONE_GUIDELINES.md](docs/development/MILESTONE_GUIDELINES.md)):
baseline comparison, merge policy/merge blocking, GitHub/Bitbucket status publishing,
email notifications, LLM-driven review, a GitLab provider, and scanner container
images -- none of these were touched.

## Current branch

`feature/milestone-5-scan-orchestration` (tracks
`origin/feature/milestone-5-scan-orchestration`; the remote branch does not yet
contain this session's uncommitted Milestone 5 work).

## Latest verified test count

Verified on `feature/milestone-5-scan-orchestration`, without Docker Compose services
running:

```
pytest -q  ->  124 passed, 2 failed (test_integration_health.py::test_database_health
                and ::test_redis_health -- require live Postgres/Redis; not code
                regressions; same 2 pre-existing failures as before this session's work)
ruff check .        ->  All checks passed!
pyright              ->  0 errors, 0 warnings, 0 informations
docker compose config ->  valid (no errors)
```

124 = 116 (pre-Milestone-5 baseline) + 8 new tests (5 in
`test_scan_orchestration_service.py`, 3 in `test_webhook_persistence.py`).

## Current architecture summary

FastAPI app with two webhook endpoints (GitHub, Bitbucket) behind a provider
abstraction (`SCMProvider` protocol); a provider-agnostic `WebhookService` that
persists `Repository`/`PullRequest`/`WebhookEvent`/`WorkflowRun` rows to PostgreSQL,
writes an `AuditLog` row, and (Milestone 5) schedules scan orchestration as a
background task; a provider-agnostic `RepositoryWorkspaceService` (Milestone 3) that
securely clones/fetches a PR's exact source commit into an isolated workspace; a
provider-agnostic scanner runtime (Milestone 4, `ScannerRunner`/`ScannerRegistry`) that
runs six static analysis tools (ruff, bandit, semgrep, pyright, gitleaks, pip-audit)
against that workspace and normalizes their output; and (Milestone 5)
`ScanOrchestrationService`, which now wires all of the above together end-to-end and
persists `NormalizedFinding`/`AggregatedScanResult` to `ScanRun`/`Finding`. The
`PolicyDecision`/`Notification`/`Report` tables still exist in the schema (Milestone 1)
but nothing writes to them yet -- baseline comparison, merge policy, status
publishing, notifications, and LLM review remain future work. Full detail:
[docs/development/PROJECT_ARCHITECTURE.md](docs/development/PROJECT_ARCHITECTURE.md)
(includes a Mermaid diagram).

## Mandatory project rules

See [docs/development/CLAUDE_CODE_RULES.md](docs/development/CLAUDE_CODE_RULES.md) for
the full, authoritative list. In summary:

1. Never discard existing uncommitted work.
2. Never reset, restore, overwrite, or delete without explicit approval.
3. Never commit, push, open a pull request, or merge unless explicitly asked.
4. The user performs the final merge.
5. Work only on the current approved milestone; do not implement future milestones.
6. Read the repository and existing documents before making changes.
7. Run the required verification commands before reporting completion.
8. Never expose, persist, or log credentials or access tokens.
9. Never execute untrusted repository code.
10. Never install dependencies from a repository being scanned.
11. Clearly report assumptions, risks, test results, and remaining gaps.

## Mandatory verification commands

Run before reporting any task complete (see
[docs/development/DEVELOPMENT_WORKFLOW.md](docs/development/DEVELOPMENT_WORKFLOW.md#standard-verification-commands)):

```bash
ruff check .
pyright
pytest -q
docker compose config
git diff --check
git status
```

## Documentation

Full index in [README.md](README.md#documentation-index). This session added
`docs/architecture/milestone-5.md` and updated `README.md` and
`docs/development/PROJECT_ARCHITECTURE.md` (new orchestration section, refreshed
Mermaid diagram, refreshed "not yet implemented" list) to reflect Milestone 5.

## Next planned milestone

**Not yet defined in this repository.** No session instructions have specified
Milestone 6's scope yet. Likely candidates (to be confirmed with the user before
starting, per
[docs/development/MILESTONE_GUIDELINES.md](docs/development/MILESTONE_GUIDELINES.md)),
in no particular order: baseline comparison; merge policy/merge blocking
(`PolicyDecision`); GitHub/Bitbucket status/check publishing; email notifications
(`Notification`); LLM-driven review; a GitLab provider; building/publishing the six
scanner container images for `ContainerExecutionBackend`; and replacing Milestone 5's
in-process `BackgroundTasks` orchestration with a durable task queue (see Milestone
5's "Remaining risks"). **Do not start implementing any of these without explicit
scope confirmation first.**

## Known risks

- **Milestone 5 work is uncommitted.** A hard reset, `git clean -fd`, or checkout of a
  clean branch would destroy it. See rule 2 above.
- **`develop` is not yet merged to `main`.** PR #4
  (https://github.com/Parthi10/partha-prime-agent/pull/4) is open but unmerged as of
  this writing; `main` is still 4 commits behind `develop` (missing milestones 2-4)
  until it's reviewed and merged.
- **No durable orchestration queue.** Milestone 5 schedules scan orchestration via
  FastAPI's in-process `BackgroundTasks`. A process restart mid-scan loses that
  orchestration with no automatic recovery; there is no retry on transient failure and
  no limit on concurrent scans under a webhook burst. See
  [docs/architecture/milestone-5.md](docs/architecture/milestone-5.md#remaining-risks--known-limitations).
- **Alembic migrations currently fail**: `alembic current`/`alembic upgrade head` raise
  `KeyError: 'formatters'` because `alembic.ini` lacks the logging-config sections
  `fileConfig` expects. Verified in this session. Tables are created in practice via
  `init_db()`'s automatic `Base.metadata.create_all` at app startup. See
  [docs/operations/TROUBLESHOOTING.md](docs/operations/TROUBLESHOOTING.md#alembic-migration-commands-fail-with-keyerror-formatters).
- **Editable-install `PYTHONPATH` quirk**: a plain `python -c "import
  protecto_prime_agent"` or `uvicorn protecto_prime_agent.main:app` can raise
  `ModuleNotFoundError` even though `pip show` reports the package installed; `pytest`
  is unaffected (`pythonpath = ["src"]` in `pyproject.toml`). Workaround: run with
  `PYTHONPATH=src`. See
  [docs/operations/TROUBLESHOOTING.md](docs/operations/TROUBLESHOOTING.md#wrong-python-interpreter--module-not-found).
- **No scanner container images exist yet.** `ContainerExecutionBackend` is unit-tested
  for the safety of the `docker run` invocation it builds but is not exercised
  end-to-end; production scanning currently has no isolated-container path actually
  running. See
  [docs/deployment/PRODUCTION_DEPLOYMENT.md](docs/deployment/PRODUCTION_DEPLOYMENT.md#scanner-images).
- **pip-audit requires network access** (the one scanner that does) -- see
  [docs/deployment/PRODUCTION_DEPLOYMENT.md](docs/deployment/PRODUCTION_DEPLOYMENT.md#pip-audits-network-access-requirement).
- **gitleaks is not in the `api` Docker image** (Go binary, not pip-installable) -- see
  [docs/deployment/DOCKER_SETUP.md](docs/deployment/DOCKER_SETUP.md#whats-inside-the-api-image).
- **No automated stale-workspace/scanner-output reaper is scheduled** -- both cleanup
  paths exist as callable methods but nothing invokes them on a recurring schedule. See
  [docs/deployment/PRODUCTION_DEPLOYMENT.md](docs/deployment/PRODUCTION_DEPLOYMENT.md#cleanup-jobs).
