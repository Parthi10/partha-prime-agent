# Protecto Prime Agent

Protecto Prime Agent V1 provides an internal PR review platform foundation using FastAPI, PostgreSQL, Redis, and Docker Compose.

> **Start here:** [PROJECT_STATE.md](PROJECT_STATE.md) is the single source of truth
> for what has actually been built, what's in progress, and what's next. Read it before
> making any change, and especially before starting a new coding session (see
> [sessions/SESSION_PROMPT.md](sessions/SESSION_PROMPT.md)).

## Documentation index

**Project state and session handling**
- [PROJECT_STATE.md](PROJECT_STATE.md) -- current milestone, branch, verified test count, architecture summary, mandatory rules, known risks. Read this first.
- [sessions/SESSION_PROMPT.md](sessions/SESSION_PROMPT.md) -- reusable prompt template for opening a new session.
- [sessions/HANDOVER_TEMPLATE.md](sessions/HANDOVER_TEMPLATE.md) -- what to fill in at the end of a session.
- [sessions/DEVELOPMENT_CHECKLIST.md](sessions/DEVELOPMENT_CHECKLIST.md) -- checkbox checklist covering a full development cycle.

**Development process**
- [docs/development/CLAUDE_CODE_RULES.md](docs/development/CLAUDE_CODE_RULES.md) -- non-negotiable rules for any coding session in this repository (never discard work, never commit/push/merge without explicit approval, etc).
- [docs/development/DEVELOPMENT_WORKFLOW.md](docs/development/DEVELOPMENT_WORKFLOW.md) -- branch flow, exact example commands, standard verification commands.
- [docs/development/MILESTONE_GUIDELINES.md](docs/development/MILESTONE_GUIDELINES.md) -- how milestones are scoped, completed, and handed over.
- [docs/development/PROJECT_ARCHITECTURE.md](docs/development/PROJECT_ARCHITECTURE.md) -- current architecture through Milestone 4, with a Mermaid diagram and explicit "not yet implemented" list.

**Architecture (milestone-by-milestone detail)**
- [docs/architecture/milestone-2.md](docs/architecture/milestone-2.md), [docs/architecture/milestone-3.md](docs/architecture/milestone-3.md), [docs/architecture/milestone-4.md](docs/architecture/milestone-4.md).

**Deployment**
- [docs/deployment/LOCAL_SETUP.md](docs/deployment/LOCAL_SETUP.md) -- macOS/Linux prerequisites, editable install, scanner dependencies (including gitleaks and the semgrep ruleset), database migrations, running the app, health-endpoint verification, common setup issues.
- [docs/deployment/DOCKER_SETUP.md](docs/deployment/DOCKER_SETUP.md) -- `docker-compose.yml` services, full command reference (build/start/stop/logs/status/rebuild/cleanup), volumes/ports/healthchecks, Apple Silicon notes, scanner-container considerations.
- [docs/deployment/PRODUCTION_DEPLOYMENT.md](docs/deployment/PRODUCTION_DEPLOYMENT.md) -- production guide: secrets management, migrations, PostgreSQL/Redis, workspace storage/quotas, scanner images, network controls, health/readiness, observability, rollback, backup, cleanup jobs, security hardening.
- [docs/deployment/ENVIRONMENT_VARIABLES.md](docs/deployment/ENVIRONMENT_VARIABLES.md) -- every `Settings` field plus the one test-only variable read outside `Settings`, with purpose/required-or-optional/default/secret-or-not/example.

**Operations**
- [docs/operations/SCANNER_RUNBOOK.md](docs/operations/SCANNER_RUNBOOK.md) -- how the scanner runtime works, all six scanners, selection, normalization, limits/cleanup, local vs. container execution.
- [docs/operations/TROUBLESHOOTING.md](docs/operations/TROUBLESHOOTING.md) -- general environment issues, Git/GitHub problems, workspace and scanner failure modes, safe diagnostic commands.

## Quick start

Minimal commands to get running locally. For prerequisites, database migrations,
health-endpoint verification, scanner dependencies (including gitleaks), and common
setup issues, see [docs/deployment/LOCAL_SETUP.md](docs/deployment/LOCAL_SETUP.md).

```bash
python3.12 -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env
docker compose up -d postgres redis
uvicorn protecto_prime_agent.main:app --reload
```

For the full `docker-compose.yml` command reference (build/start/stop/logs/rebuild/
cleanup), see [docs/deployment/DOCKER_SETUP.md](docs/deployment/DOCKER_SETUP.md).

## Verification

```bash
make lint       # ruff check .
make typecheck  # pyright
make test       # pytest
docker compose config
```

See [docs/development/DEVELOPMENT_WORKFLOW.md](docs/development/DEVELOPMENT_WORKFLOW.md#standard-verification-commands)
for the full standard verification set expected before any change is proposed for
review.

## Milestones

- Milestone 1 -- platform foundation: health checks, typed configuration, async PostgreSQL/Redis access, schema models, Alembic, containerized service orchestration.
- Milestone 2 -- Bitbucket webhook ingestion, SCM provider abstraction, validation, idempotency, and persistence. See [docs/architecture/milestone-2.md](docs/architecture/milestone-2.md).
- Milestone 3 -- provider-agnostic repository workspace service: secure clone/fetch of the exact PR source commit, diff generation, cleanup. See [docs/architecture/milestone-3.md](docs/architecture/milestone-3.md).
- Milestone 4 -- provider-agnostic scanner runtime (ruff, bandit, semgrep, pyright, gitleaks, pip-audit) with normalized findings and sandboxed execution. See [docs/architecture/milestone-4.md](docs/architecture/milestone-4.md).

Environment variables for all of the above are documented in
[docs/deployment/ENVIRONMENT_VARIABLES.md](docs/deployment/ENVIRONMENT_VARIABLES.md).
The full current architecture -- including what is and isn't wired together yet -- is
in [docs/development/PROJECT_ARCHITECTURE.md](docs/development/PROJECT_ARCHITECTURE.md).
