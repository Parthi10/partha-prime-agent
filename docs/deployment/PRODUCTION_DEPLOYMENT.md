# Production deployment

A production deployment guide for Protecto Prime Agent as it exists through
Milestone 4. This is written for **future** production use -- large parts of it are
explicitly marked as not yet supported by anything currently in this repository.
**No Kubernetes, OpenShift, Helm, or other cloud-orchestrator manifests exist in this
repository today.** Everything here describes what a production deployment must
provide, using this project's own components (`docker-compose.yml`, `Dockerfile`,
`Settings`) as the concrete starting point, not a specific target platform.

See also: [../architecture/milestone-3.md](../architecture/milestone-3.md) and
[../architecture/milestone-4.md](../architecture/milestone-4.md) for the full security
design this guide operationalizes, [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md),
[../operations/SCANNER_RUNBOOK.md](../operations/SCANNER_RUNBOOK.md).

## Prerequisites

- A container runtime capable of running the `api` image built from `Dockerfile` (any
  OCI-compatible runtime; this repository only defines/tests a `docker-compose.yml`
  topology, not a specific orchestrator).
- A managed or self-hosted PostgreSQL 16-compatible instance, reachable from the `api`
  workload.
- A managed or self-hosted Redis 7-compatible instance, reachable from the `api`
  workload.
- Persistent, quota-able storage for `WORKSPACE_ROOT` and `SCANNER_OUTPUT_ROOT` (see
  below) -- not required to be shared/networked storage, since each is ephemeral
  per-run and cleaned up automatically, but it must be local-fast disk with enough free
  space for `MAX_WORKSPACE_SIZE_MB`-sized workspaces.
- If running scanners via `ContainerExecutionBackend`: a container image registry and
  the ability to build/pin per-scanner images (not yet built -- see "Scanner images"
  below).

## Secrets management

None of `BITBUCKET_WEBHOOK_SECRET`, `GITHUB_WEBHOOK_SECRET`, `DATABASE_PASSWORD`, or
`REDIS_PASSWORD` should ever be committed, put in a Docker image layer, or placed in
plain-text `docker-compose.yml`-style environment blocks in production. Inject them at
deploy time via your platform's secret store (e.g. environment variables sourced from
a secrets manager, mounted secret files, or your orchestrator's native secrets object)
-- this repository does not implement or depend on any specific secrets-management
product; it only requires that these values arrive as environment variables matching
`Settings`' field names (see [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md)).
`.env.example` in this repository intentionally contains only non-secret placeholder
values -- never copy real production secrets into a file with that name pattern
tracked by git (`.gitignore` excludes `.env`/`.env.*` except `.env.example` for exactly
this reason).

## Environment configuration

Build the production environment from [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md)
end to end -- every variable `Settings` (`src/protecto_prime_agent/config.py`) reads
has a default suitable for local development only; review each one for a production
value (database/Redis endpoints, resource limits sized for expected repository sizes,
`SCANNERS_ENABLED`, tool versions matching whatever images you build).

## Database migration

Run schema setup deliberately in production rather than relying on `init_db()`'s
automatic `Base.metadata.create_all` (which this application also runs at every
startup -- safe for idempotent `CREATE TABLE IF NOT EXISTS`-equivalent behavior via
SQLAlchemy, but not a substitute for reviewed, versioned migrations in a
production database). The intended path is Alembic
(`alembic upgrade head`); as documented in
[LOCAL_SETUP.md](LOCAL_SETUP.md#7-database-migrations), this currently fails in this
repository's checked-in state (`alembic.ini` is missing logging-config sections
required by `fileConfig`) -- **fix that before relying on Alembic for a production
migration path**; do not deploy against a mechanism you have not verified works.

## Application deployment

Build and run the `api` image from `Dockerfile` (see
[DOCKER_SETUP.md](DOCKER_SETUP.md)) against production `DATABASE_*`/`REDIS_*`
configuration. There is no production-specific Dockerfile or multi-stage build in this
repository today -- the same image built for local Compose use is the only one defined.
Review `Dockerfile`'s `pip install .[dev]` before a production build: it installs
`pytest`/`ruff`/`pyright`/scanner tooling that a pure API-serving container does not
need, and installing scanner tools into the `api` image only matters if you intend to
run scanners in-process there via `LocalProcessExecutionBackend` (not recommended --
see below).

## PostgreSQL

Use a managed or independently-operated PostgreSQL instance in production, not the
`postgres:16-alpine` container from `docker-compose.yml` (that container has no
persistent volume configured and is intended for local development only -- see
[DOCKER_SETUP.md](DOCKER_SETUP.md#volumes)). Configure connection pooling/`pool_pre_ping`
behavior appropriately for your instance's connection limits (the application's engine
is created with `pool_pre_ping=True` already -- `database.py`).

## Redis

Same guidance as PostgreSQL: use a managed/independent Redis instance, not the local
Compose container. Redis is currently only used for the `/health/ready` check (see
[../development/PROJECT_ARCHITECTURE.md](../development/PROJECT_ARCHITECTURE.md#redis));
size it minimally until a future milestone adds real Redis-backed functionality (job
queue, cache, etc.).

## Persistent workspace storage

`WORKSPACE_ROOT` (Milestone 3) and `SCANNER_OUTPUT_ROOT` (Milestone 4) do not need to be
*persistent* across restarts (both are cleaned up automatically -- workspaces via
`mark_processing_complete`/`cleanup_stale_workspaces`, scanner output via a
`try/finally` around every scan), but they do need to be **fast, local, and
consistently available** to whatever process is running `RepositoryWorkspaceService`/
`ScannerRunner` at the time -- not networked storage with high latency, and not a path
that could differ between the process that created a workspace and the process that
later cleans it up (e.g. avoid pointing these at ephemeral per-pod storage in a
multi-replica deployment unless the same replica handles a given workflow run start to
finish).

## Workspace quotas

Both `RepositoryWorkspaceService` (`MAX_WORKSPACE_SIZE_MB`, checked before and after
fetch) and the scanner runtime's disk usage are **application-level, best-effort**
checks, not a hard sandbox. Apply an OS-level or container ephemeral-storage quota on
the filesystem/volume backing `WORKSPACE_ROOT` and `SCANNER_OUTPUT_ROOT` so that a
single runaway workspace or scan cannot exhaust the host regardless of an
application-level bug (see
[../architecture/milestone-3.md](../architecture/milestone-3.md#disk-and-workspace-size-protection)).

## Scanner images

**Recommendation: use isolated, per-scanner containers in production, not
`LocalProcessExecutionBackend`.** `LocalProcessExecutionBackend` runs scanner tools as
plain host subprocesses with no filesystem or network isolation and does not enforce
memory/process-count limits -- appropriate for development and CI, not for scanning
untrusted, externally-supplied repository content in production.

`ContainerExecutionBackend` (`src/protecto_prime_agent/scanners/execution.py`) defines
the exact, security-reviewed contract a production scanner container must run under.
Every invocation it constructs:

- never mounts the Docker socket, never sets `--privileged`
- mounts the repository workspace **read-only** (`:ro`)
- mounts a dedicated, isolated output directory read-write, plus a small
  `noexec,nosuid` tmpfs at `/tmp` (the rest of the container's root filesystem is
  `--read-only`)
- disables container networking (`--network none`) for every scanner except pip-audit
- drops all Linux capabilities (`--cap-drop ALL`) and disables privilege escalation
  (`--security-opt no-new-privileges`)
- runs as a non-root, unprivileged user (`--user 65534:65534`)
- enforces memory (`--memory`), CPU (`--cpus`), and process-count (`--pids-limit`)
  limits (cgroup-based, not POSIX ulimits)
- passes only the minimal, allowlisted environment from `build_minimal_env`

**What is not yet done**: no `protecto-scanner-<tool>:<version>` images have been built
or published, and no orchestration code constructs `ScannerRunner` with a
`ContainerExecutionBackend` instance instead of the default
`LocalProcessExecutionBackend`. Building six version-pinned Dockerfiles (pinned to the
versions in [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md)) and wiring that
construction is required before this runtime should process untrusted, external
repositories in production.

## Network controls

- Every scanner container except pip-audit's should run with `--network none` --
  ruff, bandit, semgrep (offline ruleset), pyright, and gitleaks are fully offline by
  design (see
  [../architecture/milestone-4.md](../architecture/milestone-4.md#no-dynamic-downloads-during-a-scan)).
- pip-audit's container is the one exception: it needs egress to a vulnerability
  database (PyPI/OSV). Prefer a restricted egress policy scoped to just that
  destination over granting it (or any other scanner) unrestricted network access.
- The `api` service itself needs outbound access to the SCM provider (for cloning, per
  Milestone 3) and to PostgreSQL/Redis; it should not need inbound access beyond the
  webhook/health endpoints it serves.

## Health checks and readiness checks

`GET /health/live` always returns `200` -- use it as a liveness probe (process is up).
`GET /health/ready` returns `200` only if Redis responds to `PING`, else `503` -- use it
as a readiness probe, understanding it currently does **not** check PostgreSQL
reachability (see
[../development/PROJECT_ARCHITECTURE.md](../development/PROJECT_ARCHITECTURE.md#fastapi)).
`docker-compose.yml`'s `postgres`/`redis` healthchecks
(`pg_isready`/`redis-cli ping`) are a useful pattern to replicate at whatever
orchestrator level you deploy those services independently.

## Observability

Structured JSON logging is already in place (`src/protecto_prime_agent/logging.py`):
every log line includes `timestamp`, `level`, `message`, and `correlation_id` (echoed
from the `X-Correlation-ID` request header, or generated). Audit events
(`AuditLog` rows -- see
[../development/PROJECT_ARCHITECTURE.md](../development/PROJECT_ARCHITECTURE.md#audit-flow))
are the durable record of workspace and scanner lifecycle activity and are the primary
surface for post-hoc investigation, since scanner output directories are deleted
immediately after each scan (see
[../operations/SCANNER_RUNBOOK.md](../operations/SCANNER_RUNBOOK.md#monitoring-scan-activity-via-audit-events)).
There is no metrics/tracing integration (Prometheus, OpenTelemetry, etc.) in this
repository today -- **not yet implemented**.

## Rollback

There is no automated rollback tooling in this repository. In practice: keep the
previous container image tag deployable (don't overwrite tags), and since the
application auto-creates tables via `init_db()` but does not yet reliably run Alembic
migrations (see "Database migration" above), a rollback that depends on reverting a
schema change needs to be planned and tested manually until the Alembic path is fixed
and adopted as the source of truth.

## Backup

There is no backup automation in this repository. PostgreSQL backup/restore is your
infrastructure's responsibility (e.g. your managed database provider's snapshot
feature, or `pg_dump`/`pg_restore` on a self-hosted instance) -- nothing here is
specific to this application beyond the standard schema in
`alembic/versions/001_initial_schema.py`. Workspace and scanner output directories do
not need backing up -- they are ephemeral by design.

## Cleanup jobs

- **Workspaces** (`WORKSPACE_ROOT`): `RepositoryWorkspaceService.cleanup_stale_workspaces()`
  exists as a method but is not wired to any scheduler in this repository -- if you
  rely on `WORKSPACE_RETENTION_HOURS > 0` (retaining successful workspaces for
  debugging), you must invoke `cleanup_stale_workspaces()` on a recurring schedule
  yourself (e.g. a cron-triggered call, or an orchestrator `CronJob`-equivalent);
  nothing in this repository schedules it today.
- **Scanner output** (`SCANNER_OUTPUT_ROOT`): cleaned up automatically after every scan
  (`try/finally` in `ScannerRunner.run_scan`); only needs manual attention if a process
  was killed hard enough to skip that block (see
  [../operations/SCANNER_RUNBOOK.md](../operations/SCANNER_RUNBOOK.md#scanner-output-directory-and-cleanup)).

## Security hardening checklist

- [ ] Secrets injected via your platform's secret store, never committed or baked into
      an image layer.
- [ ] `ContainerExecutionBackend` (not `LocalProcessExecutionBackend`) used for all
      scanner execution, once scanner images exist.
- [ ] Docker socket never mounted into any scanner container (verified by
      `tests/test_scanner_execution.py`; re-verify against your actual deployment
      manifests, since tests only cover the argv this repository's code constructs).
- [ ] `--network none` for every scanner except pip-audit's restricted-egress
      container.
- [ ] Repository code/dependencies never executed or installed as part of a scan or
      clone -- every git command and every scanner `build_command` is a fixed argument
      list; nothing is templated from repository content, and nothing runs
      `pip install`/`npm install`/`make`/a repository's own tests, setup scripts,
      migrations, or startup commands. Preserve this property in any new adapter or
      orchestration code.
- [ ] Workspace and scanner output quotas enforced at the filesystem/container level,
      not only the application-level checks.
- [ ] `Dockerfile`'s `dev` extra reviewed/trimmed for any image that doesn't need
      test/scanner tooling.
- [ ] Alembic migration path fixed and verified before depending on it (see "Database
      migration" above).

## Health and validation commands

Run these before and after any deployment change:

```bash
ruff check .
pyright
pytest -q
docker compose config
```

See [../operations/SCANNER_RUNBOOK.md](../operations/SCANNER_RUNBOOK.md) for
scanner-specific production health checks (tool availability, version drift, audit-event
monitoring).
