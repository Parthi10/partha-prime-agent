# Local setup

Setting up Protecto Prime Agent, including the Milestone 4 scanner runtime, for local
development on macOS or Linux.

See also: [DOCKER_SETUP.md](DOCKER_SETUP.md), [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md),
[../operations/TROUBLESHOOTING.md](../operations/TROUBLESHOOTING.md),
[../development/PROJECT_ARCHITECTURE.md](../development/PROJECT_ARCHITECTURE.md).

## Prerequisites

| Requirement | macOS | Linux |
|---|---|---|
| Python 3.12+ | `brew install python@3.12` | your distro's package manager, or [pyenv](https://github.com/pyenv/pyenv) |
| Docker | Docker Desktop (includes the Compose plugin) | Docker Engine + the `docker-compose-plugin` package (so `docker compose`, not the legacy standalone `docker-compose`, is available) |
| gitleaks (for scanner tests) | `brew install gitleaks` | download a release binary -- see step 3 below |
| Homebrew (macOS only) | required for the gitleaks install above | n/a |

`requires-python = ">=3.12"` in `pyproject.toml` is enforced by pip at install time.

## 1. Create and activate a virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

## 2. Editable install: application and scanner dependencies

```bash
make install
```

This runs `pip install -e ".[dev]"` (editable install), which installs:

- Application dependencies (FastAPI, SQLAlchemy, asyncpg, alembic, redis, etc. -- see
  `[project.dependencies]` in `pyproject.toml`)
- Dev/test tooling: `pytest`, `pytest-asyncio`, `httpx`, `ruff`, `pyright`
- **Scanner dependencies that are pip-installable**: `bandit`, `semgrep`, `pip-audit`

`ruff` and `pyright` double as both project lint/typecheck tools and two of the six
scanner adapters, so no separate install step is needed for them.

> **Editable-install note**: in some environments, the editable install's path hook
> resolves correctly for tools that set `pythonpath` themselves (this project's
> `pytest` config does, via `pythonpath = ["src"]` in `pyproject.toml`), but a plain
> `python -c "import protecto_prime_agent"` or `uvicorn protecto_prime_agent.main:app`
> invocation can still raise `ModuleNotFoundError` if the venv's editable-install path
> hook isn't being picked up. If you hit that, run with `PYTHONPATH=src` explicitly
> (see step 8) -- see [../operations/TROUBLESHOOTING.md](../operations/TROUBLESHOOTING.md#wrong-python-interpreter--module-not-found).

## 3. Install gitleaks (external dependency, not pip-installable)

gitleaks is a Go binary distributed as a standalone executable, not a Python package,
so it is **not** part of `pyproject.toml`'s dependencies and `make install` does not
install it. Install it separately:

```bash
# macOS
brew install gitleaks

# Linux: download a release binary directly
# https://github.com/gitleaks/gitleaks/releases
```

Verify it's on `PATH`:

```bash
gitleaks version
```

If gitleaks is not installed, `GitleaksAdapter` reports that scanner as `FAILED` with
`error_message="tool_not_available"` -- every other scanner still runs normally (see
[../operations/SCANNER_RUNBOOK.md](../operations/SCANNER_RUNBOOK.md)).

## 4. Confirm the bundled semgrep ruleset is present

The semgrep adapter never fetches rules from semgrep's registry over the network (see
[../architecture/milestone-4.md](../architecture/milestone-4.md#no-dynamic-downloads-during-a-scan)).
It always points `--config` at a ruleset file that ships inside the package:

```
src/protecto_prime_agent/scanners/rulesets/semgrep_python.yaml
```

This file is required for the semgrep adapter to run at all. It's committed to the
repository and (via `[tool.setuptools.package-data]` in `pyproject.toml`) packaged with
any build of `protecto_prime_agent`. Nothing needs to be downloaded or generated -- if
this file is ever missing or moved, semgrep will exit non-zero and the runner will
record it as `FAILED`.

## 5. Copy the sample environment file

```bash
cp .env.example .env
```

`.env.example` contains every setting this application reads, with safe (non-secret)
defaults -- including scanner runtime defaults (`SCANNERS_ENABLED`,
`SCANNER_OUTPUT_ROOT`, timeouts, resource limits, per-tool `*_VERSION` values). See
[ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) for the full reference.

## 6. Start PostgreSQL and Redis

```bash
docker compose up -d postgres redis
```

Confirm both are healthy:

```bash
docker compose ps
```

Both services define a `healthcheck` in `docker-compose.yml`; `docker compose ps`
shows `healthy` once they pass (`pg_isready` for PostgreSQL, `redis-cli ping` for
Redis).

## 7. Database migrations

Tables are defined both as SQLAlchemy models (`src/protecto_prime_agent/models/`) and
as an Alembic migration (`alembic/versions/001_initial_schema.py`). In practice, this
application creates its tables automatically at startup:
`init_db()` (`src/protecto_prime_agent/database.py`, called from `main.py`'s FastAPI
`lifespan`) runs `Base.metadata.create_all` against whatever database
`DATABASE_URL`/`DATABASE_*` points at -- so simply starting the app (step 8) against an
empty database is sufficient for local development.

The Alembic migration exists for explicit, versioned schema management. The intended
command is:

```bash
alembic upgrade head
```

**Known issue, verified in this environment**: as committed, `alembic.ini` does not
contain the `[loggers]`/`[handlers]`/`[formatters]` sections that
`alembic/env.py`'s `fileConfig(config.config_file_name)` call expects, so both
`alembic current` and `alembic upgrade head` currently fail with
`KeyError: 'formatters'` before touching the database at all. There is no `make`
target wired to Alembic. Until `alembic.ini` is fixed (out of scope for documentation-
only changes), rely on `init_db()`'s automatic `create_all` at application startup for
local development; see
[../operations/TROUBLESHOOTING.md](../operations/TROUBLESHOOTING.md#alembic-migration-commands-fail-with-keyerror-formatters).

## 8. Run the API locally

```bash
uvicorn protecto_prime_agent.main:app --reload
```

If this raises `ModuleNotFoundError: No module named 'protecto_prime_agent'` (see the
editable-install note in step 2):

```bash
PYTHONPATH=src uvicorn protecto_prime_agent.main:app --reload
```

## 9. Health endpoint verification

With the app running (step 8) and PostgreSQL/Redis up (step 6):

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health/live    # expect 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health/ready   # expect 200 if Redis is reachable, else 503
```

`/health/live` (`main.py`) always returns `200`. `/health/ready` calls
`check_redis_health()` and returns `503` with `{"status": "degraded"}` if Redis is
unreachable -- it does not check PostgreSQL (see
[../development/PROJECT_ARCHITECTURE.md](../development/PROJECT_ARCHITECTURE.md#fastapi)).

## LocalProcessExecutionBackend for scanner development

`ScannerRunner` defaults to `LocalProcessExecutionBackend` when no execution backend is
passed explicitly. This backend runs each scanner as a plain subprocess on the host
(via `subprocess.run` with an explicit argument list and `shell=False`), applying a
wall-clock timeout (`SCANNER_TIMEOUT_SECONDS`), a CPU-time limit (POSIX `RLIMIT_CPU`),
and a minimal, allowlisted environment (`build_minimal_env`) -- never the app's own
`os.environ`. It does **not** provide filesystem or network isolation and does not
enforce memory/process-count limits (see
[../architecture/milestone-4.md](../architecture/milestone-4.md#resource-limits)). This
is intentional and sufficient for local development and tests; it is not the
production isolation mechanism -- see
[PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) for `ContainerExecutionBackend`.

## Running the test suite

```bash
make test      # pytest
make lint       # ruff check .
make typecheck  # pyright
```

`tests/test_scanner_adapters.py` runs the real installed ruff/bandit/semgrep/pyright/
gitleaks binaries against small, local, temporary Python repository fixtures created at
test time (no network access needed for these five). pip-audit's live-parsing
correctness is tested against a canned, offline JSON fixture; only its `should_run` gate
is exercised live -- see [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md#pip-audits-network-access-requirement).

`tests/test_integration_health.py` exercises real PostgreSQL/Redis connections; it
fails (rather than skips) if they're unreachable unless `SKIP_INTEGRATION_TESTS=true`.

## Health and validation commands

```bash
ruff check .
pyright
pytest -q
docker compose config
```

See [../operations/SCANNER_RUNBOOK.md](../operations/SCANNER_RUNBOOK.md) for
scanner-specific health checks (confirming each tool binary is on `PATH` and reports
the expected version).

## Common local setup issues

See [../operations/TROUBLESHOOTING.md](../operations/TROUBLESHOOTING.md) for the full
list (wrong interpreter, venv not active, Docker daemon unavailable, PostgreSQL/Redis
unavailable, pytest event-loop errors, Git auth problems, workspace/scanner failures,
permission errors, generated files accidentally staged). The two issues most specific
to a fresh local setup are the editable-install `PYTHONPATH` nuance (step 2/8 above) and
the Alembic `KeyError: 'formatters'` issue (step 7 above).
