# Docker setup

`docker-compose.yml`/`Dockerfile` as they exist today, the commands to operate them,
and what they do and do not currently provide for the Milestone 4 scanner runtime.

See also: [LOCAL_SETUP.md](LOCAL_SETUP.md), [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md),
[ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md).

## Prerequisites

- Docker Desktop (macOS/Windows) or Docker Engine (Linux)
- Docker Compose plugin (`docker compose`, not the legacy standalone `docker-compose`)

### Apple Silicon (arm64) notes

- `python:3.12-slim` (the `Dockerfile` base image), `postgres:16-alpine`, and
  `redis:7-alpine` all publish native `linux/arm64` images, so `docker compose up
  --build` works without emulation on Apple Silicon.
- If you ever need to force a specific platform (e.g. testing an `amd64`-only image),
  pass `--platform linux/amd64` to the relevant `docker build`/`docker compose build`
  invocation; none of the three services in this repository currently require it.
- Ensure Docker Desktop's "Use Rosetta for x86/amd64 emulation" setting is enabled only
  if you actually need `amd64` emulation -- it is not required for this project's
  current images.

## Services defined in `docker-compose.yml`

| Service    | Image / build | Ports | Healthcheck |
|------------|----------------|-------|--------------|
| `api`      | built from `Dockerfile` (context `.`) | `8000:8000` | none defined; depends on `postgres` and `redis` being healthy before starting |
| `postgres` | `postgres:16-alpine` | `5432:5432` | `pg_isready -U protecto -d protecto_prime_agent` (10s interval, 5s timeout, 5 retries) |
| `redis`    | `redis:7-alpine` | `6379:6379` | `redis-cli ping` (10s interval, 5s timeout, 5 retries) |

### Volumes

`docker-compose.yml` defines **no named volumes** -- `postgres` and `redis` data is
ephemeral (container filesystem only) and is lost when the container is removed. There
is no persistent-storage configuration for local Compose use today; see
[PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md#persistent-workspace-storage) for
what a production deployment needs that this local setup does not provide.

### Ports

`8000` (API), `5432` (PostgreSQL), `6379` (Redis) are all published to the host
(`host:container` mappings shown above), so local tools (`psql`, `redis-cli`, browser)
can reach them directly at `localhost:<port>`.

### Environment variables

`docker-compose.yml`'s `api` service hardcodes its environment block (host names
`postgres`/`redis` instead of `localhost`, matching Compose's internal DNS) rather than
reading from `.env`. See [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) for what
each variable does; if you add new required variables to `Settings`, add them to this
`environment:` block too, or the containerized `api` service won't see them (only your
shell's `.env`/exported variables apply to processes you run directly on the host).

## Commands

```bash
# Build images (no cache use beyond Docker's normal layer cache)
docker compose build

# Build and start all services in the foreground (Ctrl-C to stop)
docker compose up --build

# Start specific services in the background
docker compose up -d postgres redis

# Check status / health
docker compose ps

# Follow logs (all services, or a specific one)
docker compose logs -f
docker compose logs -f api

# Stop services (containers remain, can be restarted with `docker compose start`)
docker compose stop

# Stop and remove containers/networks (add -v to also remove any volumes)
docker compose down

# Rebuild the api image after a dependency/code change, then restart it
docker compose build api
docker compose up -d --force-recreate api

# Full cleanup: stop everything and remove containers, networks, and volumes
docker compose down -v
```

`docker compose config` validates and renders the fully resolved configuration without
needing anything running -- this is the command used in this project's standard
verification set (see
[../development/DEVELOPMENT_WORKFLOW.md](../development/DEVELOPMENT_WORKFLOW.md#standard-verification-commands)).

## What's inside the `api` image

`Dockerfile` installs the application with its `dev` extra:

```dockerfile
RUN pip install --upgrade pip && pip install .[dev]
```

Because `bandit`, `semgrep`, and `pip-audit` are part of the `dev` extra (see
[LOCAL_SETUP.md](LOCAL_SETUP.md)), the `api` image also contains those three scanners,
plus `ruff` and `pyright` (already `dev` dependencies). **gitleaks is not included** in
this image -- it is a Go binary, not a pip package, and `Dockerfile` does not currently
install it. If `ScannerRunner` runs inside the `api` container using the default
`LocalProcessExecutionBackend`, the gitleaks adapter reports
`FAILED`/`tool_not_available` there -- every other scanner is unaffected (see
[../development/PROJECT_ARCHITECTURE.md](../development/PROJECT_ARCHITECTURE.md#scanner-runtime-milestone-4)).
This is a known gap (see
[../operations/TROUBLESHOOTING.md](../operations/TROUBLESHOOTING.md)); adding a
gitleaks binary install step to `Dockerfile` is an infrastructure change outside a
documentation-only update's scope.

The bundled semgrep ruleset
(`src/protecto_prime_agent/scanners/rulesets/semgrep_python.yaml`) is copied into the
image automatically, since `Dockerfile` does `COPY src ./src` before installing the
package.

## Scanner runtime container considerations

There is currently **no** `docker-compose.yml` service, and **no** pre-built
`protecto-scanner-<tool>:<version>` image, for running scanners via
`ContainerExecutionBackend`. That backend exists in code
(`src/protecto_prime_agent/scanners/execution.py`) and is unit-tested for the safety of
the `docker run` invocation it constructs, but no scanner-specific Dockerfiles or images
have been built yet. Building and wiring those images is intentionally out of scope
here; see [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) for the invocation
contract any such image must satisfy.

## The Docker socket must never be mounted into scanner containers

Neither `docker-compose.yml` nor `ContainerExecutionBackend.build_docker_argv` ever
binds `/var/run/docker.sock` into any container, and no scanner image, base image, or
sidecar should ever require it. A container that can reach the Docker socket can
trivially escape its own isolation (e.g. by asking the host daemon to start a new,
unrestricted container), defeating every other control (read-only mounts, network
isolation, dropped capabilities, resource limits). This is asserted directly in
`tests/test_scanner_execution.py::test_container_backend_never_mounts_docker_socket`.
If you are ever tempted to add
`-v /var/run/docker.sock:/var/run/docker.sock` to make a "scanner that needs Docker"
work -- don't; redesign that scanner's execution path instead.

## Verifying the Compose configuration

```bash
docker compose config
```

This should always succeed and print the fully resolved configuration (image names,
environment, healthchecks, port mappings) without needing the containers to actually
be running.
