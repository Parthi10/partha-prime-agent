# Project state

**Read this file first, before anything else, at the start of every session.** It is
the single source of truth for where this project actually stands. If anything here
conflicts with what you observe in the repository (`git status`, `git log`, running
the tests), trust what you observe and update this file -- don't trust a stale
description over the real repository state.

Last verified: this session, on `feature/milestone-4-scanner-runtime`, via
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
| 4 -- Scanner runtime | **Implemented and locally verified on `feature/milestone-4-scanner-runtime`; NOT yet committed, pushed, or merged** | `docs/architecture/milestone-4.md` |

## Current milestone and status

**Milestone 4: Scanner Runtime.**

- All source code for the scanner runtime (`src/protecto_prime_agent/scanners/`, six
  adapters, registry, runner, execution backends, normalization/redaction, injectable
  audit writer) and its test suite
  (`tests/test_scanner_{normalization,execution,registry,runner,adapters}.py`) are
  present in the working tree.
- Configuration (`src/protecto_prime_agent/config.py`, `.env.example`),
  `pyproject.toml` scanner dependencies, and `docs/architecture/milestone-4.md` are
  present.
- A full deployment/operations/development documentation set was added in this session
  (see "Documentation" below).
- **None of this is committed.** `git status` on `feature/milestone-4-scanner-runtime`
  shows the scanner runtime and its docs/tests as modified/untracked changes in the
  working tree, not as commits. Nothing has been pushed, and no pull request exists for
  this branch's Milestone 4 work.
- Verification (ruff, pyright, pytest, docker compose config) passes against this
  uncommitted working tree -- see "Latest verified test count" below. This confirms the
  *implementation* is complete and correct; it does not mean the milestone has been
  reviewed, committed, or merged.

## Current branch

`feature/milestone-4-scanner-runtime` (tracks `origin/feature/milestone-4-scanner-runtime`,
up to date with that remote as of last check -- but note the remote branch itself does
not yet contain the uncommitted Milestone 4 work described above, since nothing has
been pushed).

## Latest verified test count

```
pytest -q  ->  118 passed
ruff check .        ->  All checks passed!
pyright              ->  0 errors, 0 warnings, 0 informations
docker compose config ->  valid (no errors)
```

## Current architecture summary

FastAPI app with two webhook endpoints (GitHub, Bitbucket) behind a provider
abstraction (`SCMProvider` protocol); a provider-agnostic `WebhookService` that
persists `Repository`/`PullRequest`/`WebhookEvent`/`WorkflowRun` rows to PostgreSQL and
writes an `AuditLog` row; a provider-agnostic `RepositoryWorkspaceService` (Milestone 3)
that securely clones/fetches a PR's exact source commit into an isolated workspace; and
a provider-agnostic scanner runtime (Milestone 4, `ScannerRunner`/`ScannerRegistry`)
that runs six static analysis tools (ruff, bandit, semgrep, pyright, gitleaks,
pip-audit) against that workspace and normalizes their output. **The webhook flow and
the workspace/scanner services are not yet wired together** -- each was built and
tested as an independent, reusable component; end-to-end orchestration is future work.
Scan results (`NormalizedFinding`/`AggregatedScanResult`) are in-memory only; the
`ScanRun`/`Finding`/`PolicyDecision`/`Notification`/`Report` tables exist in the schema
(Milestone 1) but nothing writes to them yet. Full detail:
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

Full index in [README.md](README.md#documentation-index). Newly added this session:
`docs/development/{CLAUDE_CODE_RULES,DEVELOPMENT_WORKFLOW,MILESTONE_GUIDELINES,PROJECT_ARCHITECTURE}.md`,
`sessions/{SESSION_PROMPT,HANDOVER_TEMPLATE,DEVELOPMENT_CHECKLIST}.md`, and this file.
`docs/deployment/*.md` and `docs/operations/*.md` (created in a prior session for
Milestone 4) were expanded this session with broader, repository-wide coverage
(general local-setup troubleshooting, full production-deployment checklist, Docker
command reference, environment-variable required/secret annotations).

## Next planned milestone

**Not yet defined in this repository.** No `docs/architecture/milestone-5.md` exists,
and no session instructions have specified Milestone 5's scope. Based on what
Milestones 3 and 4 repeatedly name as explicitly out of scope, likely candidates for a
future milestone (to be confirmed with the user before starting, per
[docs/development/MILESTONE_GUIDELINES.md](docs/development/MILESTONE_GUIDELINES.md))
include, in no particular order: wiring the webhook flow to the workspace and scanner
services end-to-end; persisting `NormalizedFinding`/scan results to `ScanRun`/`Finding`;
baseline comparison; merge policy/merge blocking (`PolicyDecision`); GitHub/Bitbucket
status/check publishing; email notifications (`Notification`); LLM-driven review; a
GitLab provider; and building/publishing the six scanner container images for
`ContainerExecutionBackend`. **Do not start implementing any of these without explicit
scope confirmation first.**

## Known risks

- **Milestone 4 work is uncommitted.** A hard reset, `git clean -fd`, or checkout of a
  clean branch would destroy it. See rule 2 above.
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
