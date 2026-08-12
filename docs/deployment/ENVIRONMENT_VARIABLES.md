# Environment variables

Every variable in the sections below **except one** is a field on `Settings`
(`src/protecto_prime_agent/config.py`), loaded from `.env` (see `.env.example` for a
ready-to-copy, secret-free template) or the process environment. Every `Settings` field
has a code-level default, so none are strictly required for the application to start --
"Required" below means "must be overridden away from its default for a real/production
deployment," not "the app crashes without it."

**The one exception is `SKIP_INTEGRATION_TESTS`**, which is not a `Settings` field at
all -- it is read directly via `os.getenv(...)` by test code only, and has no effect on
the running application. It is documented in its own section,
["Test-only variable"](#test-only-variable-not-a-settings-field), clearly separated from
the `Settings`-backed tables below, so it isn't mistaken for application configuration.

**No real credential appears anywhere in this document or in `.env.example` --
every example value is a placeholder.**

See also: [../development/PROJECT_ARCHITECTURE.md](../development/PROJECT_ARCHITECTURE.md),
[PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md#secrets-management).

## Application

| Variable | Purpose | Required/Optional | Default | Secret? | Example |
|---|---|---|---|---|---|
| `APP_ENV` | Selects `development`/`testing`/`production` mode | Optional | `development` | No | `production` |
| `API_HOST` | Bind address for uvicorn | Optional | `0.0.0.0` | No | `0.0.0.0` |
| `API_PORT` | Bind port for uvicorn | Optional | `8000` | No | `8000` |

## Database (PostgreSQL)

| Variable | Purpose | Required/Optional | Default | Secret? | Example |
|---|---|---|---|---|---|
| `DATABASE_HOST` | PostgreSQL hostname | Required in production | `localhost` | No | `postgres.internal` |
| `DATABASE_PORT` | PostgreSQL port | Optional | `5432` | No | `5432` |
| `DATABASE_NAME` | Database name | Optional | `protecto_prime_agent` | No | `protecto_prime_agent` |
| `DATABASE_USER` | Database user | Required in production | `protecto` | No | `protecto_app` |
| `DATABASE_PASSWORD` | Database password | **Required in production** | `protecto` | **Yes** | `<injected-by-secret-store>` |

## Redis

| Variable | Purpose | Required/Optional | Default | Secret? | Example |
|---|---|---|---|---|---|
| `REDIS_HOST` | Redis hostname | Required in production | `localhost` | No | `redis.internal` |
| `REDIS_PORT` | Redis port | Optional | `6379` | No | `6379` |
| `REDIS_DB` | Redis logical DB index | Optional | `0` | No | `0` |
| `REDIS_PASSWORD` | Redis password (if the instance requires one) | Required in production if Redis requires auth | (empty) | **Yes** | `<injected-by-secret-store>` |

## Webhooks / SCM

| Variable | Purpose | Required/Optional | Default | Secret? | Example |
|---|---|---|---|---|---|
| `BITBUCKET_WEBHOOK_SECRET` | HMAC secret used to validate incoming Bitbucket webhook signatures | **Required to accept Bitbucket webhooks** (without it, `validate_webhook` always returns `False`) | (empty) | **Yes** | `<injected-by-secret-store>` |
| `GITHUB_WEBHOOK_SECRET` | HMAC secret used to validate incoming GitHub webhook signatures | **Required to accept GitHub webhooks** | (empty) | **Yes** | `<injected-by-secret-store>` |

## Repository workspace (Milestone 3)

| Variable | Purpose | Required/Optional | Default | Secret? | Example |
|---|---|---|---|---|---|
| `WORKSPACE_ROOT` | Root directory for per-workflow-run checked-out workspaces | Optional | `/tmp/protecto-workspaces` | No | `/var/lib/protecto/workspaces` |
| `GIT_CLONE_TIMEOUT_SECONDS` | Timeout for the initial source-commit fetch | Optional | `300` | No | `300` |
| `GIT_FETCH_TIMEOUT_SECONDS` | Timeout for the target-commit fetch | Optional | `300` | No | `300` |
| `MAX_WORKSPACE_SIZE_MB` | Size ceiling checked before and after fetch | Optional | `1024` | No | `2048` |
| `WORKSPACE_RETENTION_HOURS` | How long a successful workspace is retained after `mark_processing_complete`; `0` cleans up immediately | Optional | `24` | No | `0` |
| `GIT_NETWORK_MAX_RETRIES` | Bounded retry count for transient fetch failures | Optional | `3` | No | `3` |
| `GIT_NETWORK_RETRY_BACKOFF_SECONDS` | Backoff base between retries | Optional | `0.5` | No | `0.5` |

See [../architecture/milestone-3.md](../architecture/milestone-3.md) for behavior
details.

## Scanner runtime (Milestone 4)

| Variable | Purpose | Required/Optional | Default | Secret? | Example |
|---|---|---|---|---|---|
| `SCANNERS_ENABLED` | Comma-separated list of scanners to run | Optional | `ruff,bandit,semgrep,pyright,gitleaks,pip-audit` | No | `ruff,bandit,pyright` |
| `SCANNER_OUTPUT_ROOT` | Root directory for each scan's isolated, per-scanner output directory | Optional | `/tmp/protecto-scanner-output` | No | `/var/lib/protecto/scanner-output` |
| `SCANNER_TIMEOUT_SECONDS` | Wall-clock timeout per scanner invocation | Optional | `120` | No | `180` |
| `SCANNER_CPU_SECONDS` | CPU-time budget (`RLIMIT_CPU` locally, informs `--cpus` sizing in containers) | Optional | `90` | No | `120` |
| `SCANNER_MEMORY_MB` | Memory limit -- only enforced by `ContainerExecutionBackend` (`--memory`) | Optional | `512` | No | `1024` |
| `SCANNER_MAX_PROCESSES` | Process-count limit -- only enforced by `ContainerExecutionBackend` (`--pids-limit`) | Optional | `32` | No | `64` |
| `RUFF_VERSION` | Expected ruff version (observability only, not enforced locally) | Optional | `0.15.21` | No | `0.15.21` |
| `BANDIT_VERSION` | Expected bandit version | Optional | `1.9.4` | No | `1.9.4` |
| `SEMGREP_VERSION` | Expected semgrep version | Optional | `1.169.0` | No | `1.169.0` |
| `PYRIGHT_VERSION` | Expected pyright version | Optional | `1.1.411` | No | `1.1.411` |
| `GITLEAKS_VERSION` | Expected gitleaks version | Optional | `8.30.1` | No | `8.30.1` |
| `PIP_AUDIT_VERSION` | Expected pip-audit version | Optional | `2.10.1` | No | `2.10.1` |

See [../operations/SCANNER_RUNBOOK.md](../operations/SCANNER_RUNBOOK.md) for how to
enable/disable individual scanners and interpret version-mismatch logging.

## Test-only variable (not a `Settings` field)

Every table above documents a `Settings` field, sourced from `config.py` via
`pydantic-settings` (`.env` file or process environment, either way). The variable
below is different in kind, not just in purpose: it is **not** part of `Settings` at
all, is never loaded from `.env`, and has zero effect on the running application --
only on `pytest`.

| Variable | Purpose | Required/Optional | Default | Secret? | Example | Read by |
|---|---|---|---|---|---|---|
| `SKIP_INTEGRATION_TESTS` | When not `true`, missing PostgreSQL/Redis makes integration tests fail (surfacing infra issues) instead of skipping | Optional | `false` (unset) | No | `true` | `tests/test_integration_health.py`, directly via `os.getenv("SKIP_INTEGRATION_TESTS", ...)` -- **not** read through `Settings`/`config.py` |

## What is never read from the environment by a scanner

`build_minimal_env` (`src/protecto_prime_agent/scanners/execution.py`) constructs an
**explicit allowlist** environment for every scanner subprocess -- `PATH`, `HOME`,
`LANG`, `LC_ALL`, `TMPDIR`, `PYTHONHASHSEED`, plus `SEMGREP_SEND_METRICS=off`. It never
passes through the application's own `os.environ`. Concretely, none of the following
ever reach a scanner process, regardless of what's set for the API/worker process:

- `DATABASE_HOST` / `DATABASE_PORT` / `DATABASE_NAME` / `DATABASE_USER` / `DATABASE_PASSWORD`
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` / `REDIS_PASSWORD`
- `BITBUCKET_WEBHOOK_SECRET` / `GITHUB_WEBHOOK_SECRET`
- Any SCM access token (handled entirely within `RepositoryWorkspaceService`'s
  ephemeral `GIT_ASKPASS` mechanism -- see
  [../architecture/milestone-3.md](../architecture/milestone-3.md) -- and never flows
  into the scanner runtime at all)

Verified directly
(`tests/test_scanner_execution.py::test_build_minimal_env_excludes_platform_secrets`)
and end-to-end through the full runner
(`tests/test_scanner_runner.py::test_no_platform_secrets_reach_scanner_environment`).
