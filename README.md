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

- The initial milestone focuses on health checks, typed configuration, async database access, schema models, Alembic, and containerized service orchestration.
- Bitbucket integrations, scanners, merge blocking, notifications, and LLM features are intentionally out of scope for this milestone.
- Integration tests skip only when SKIP_INTEGRATION_TESTS=true. When the variable is not set to true, missing PostgreSQL or Redis causes the integration tests to fail so CI surfaces infrastructure issues.
