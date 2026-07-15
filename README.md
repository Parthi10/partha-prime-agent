# Protecto Prime Agent

Protecto Prime Agent V1 provides an internal PR review platform foundation using FastAPI, PostgreSQL, Redis, and Docker Compose.

## Local setup

1. Create and activate a Python 3.12 virtual environment.
2. Install dependencies:
   - `make install`
3. Copy the sample environment file:
   - `cp .env.example .env`
4. Start local services:
   - `docker compose up -d postgres redis`
5. Run the API locally:
   - `uvicorn protecto_prime_agent.main:app --reload`

## Docker Compose startup

```bash
docker compose up --build
```

## Test commands

```bash
make test
make lint
make typecheck
```

## Notes

- Milestone 1 focuses on health checks, typed configuration, async database access, schema models, Alembic, and containerized service orchestration.
- Milestone 2 adds Bitbucket webhook ingestion, provider abstraction, webhook validation, idempotency, and persistence for PR events without running scanners or imposing merge decisions.
- Milestone 3 adds a provider-agnostic repository workspace service: it clones the exact source commit of a pull request into an isolated, path-validated workspace, fetches and verifies the target commit, and generates a unified diff for downstream review. See [docs/architecture/milestone-3.md](docs/architecture/milestone-3.md) for details.
- Integration tests skip only when SKIP_INTEGRATION_TESTS=true. When the variable is not set to true, missing PostgreSQL or Redis causes the integration tests to fail so CI surfaces infrastructure issues.
- Bitbucket webhook authentication uses the BITBUCKET_WEBHOOK_SECRET environment variable. GitHub webhook authentication uses the GITHUB_WEBHOOK_SECRET environment variable.
- Repository workspace behavior is controlled by WORKSPACE_ROOT, GIT_CLONE_TIMEOUT_SECONDS, GIT_FETCH_TIMEOUT_SECONDS, MAX_WORKSPACE_SIZE_MB, WORKSPACE_RETENTION_HOURS, GIT_NETWORK_MAX_RETRIES, and GIT_NETWORK_RETRY_BACKOFF_SECONDS.
- The workspace service never executes repository code, never installs repository dependencies, and never persists access tokens; credentials are redacted from any logged or stored git output.
- Private-repository access tokens are never embedded in a clone URL or written to `.git/config`; they are passed to git only through a short-lived, per-fetch `GIT_ASKPASS` helper (see [docs/architecture/milestone-3.md](docs/architecture/milestone-3.md)).
- `WORKSPACE_RETENTION_HOURS=0` cleans up a successful workspace immediately once the caller marks processing complete; a value greater than 0 retains it on disk for debugging until stale-workspace cleanup reaps it. Failed workspaces are always cleaned up immediately regardless of retention.
- Workspace size is checked both before fetching (available disk space) and after fetching (`MAX_WORKSPACE_SIZE_MB`); these are best-effort application checks, and production deployments should also apply a filesystem or container quota on `WORKSPACE_ROOT`.
- Audit event writing is injectable (`AuditWriter`/`SqlAuditWriter`) so unit tests never open a real database connection; audit-write failures are logged as a sanitized, structured event and never include raw SQL, bind parameters, or credentials.
