# Troubleshooting

Common problems across local setup, development workflow, the repository workspace
service (Milestone 3), and the scanner runtime (Milestone 4), with safe diagnostic
commands. Destructive commands are marked with an explicit warning and are never the
first thing to try.

See also: [../deployment/LOCAL_SETUP.md](../deployment/LOCAL_SETUP.md),
[../deployment/DOCKER_SETUP.md](../deployment/DOCKER_SETUP.md),
[SCANNER_RUNBOOK.md](SCANNER_RUNBOOK.md),
[../development/DEVELOPMENT_WORKFLOW.md](../development/DEVELOPMENT_WORKFLOW.md).

## General environment issues

### Wrong Python interpreter / `ModuleNotFoundError: No module named 'protecto_prime_agent'`

Diagnose:

```bash
which python
python --version                 # expect 3.12.x
python -c "import protecto_prime_agent" 2>&1
```

- If `which python` doesn't point inside `.venv/bin/`, the virtual environment isn't
  active (see next item).
- If the venv *is* active but the import still fails, this is a known editable-install
  quirk observed in this repository: `pip show protecto-prime-agent` can report the
  package as installed while a direct `python -c "import ..."` (or `uvicorn
  protecto_prime_agent.main:app`) still raises `ModuleNotFoundError`, because the venv's
  editable-install path hook isn't being picked up in that invocation context. `pytest`
  is unaffected because `pyproject.toml` sets `pythonpath = ["src"]` directly. Fix by
  running with `PYTHONPATH=src` explicitly:

  ```bash
  PYTHONPATH=src python -c "import protecto_prime_agent; print(protecto_prime_agent.__file__)"
  PYTHONPATH=src uvicorn protecto_prime_agent.main:app --reload
  ```

### Virtual environment not active

```bash
echo "$VIRTUAL_ENV"    # empty if no venv is active
```

Fix:

```bash
source .venv/bin/activate
```

If `.venv/` doesn't exist yet, see
[../deployment/LOCAL_SETUP.md](../deployment/LOCAL_SETUP.md#1-create-and-activate-a-virtual-environment).

### Docker daemon unavailable

```bash
docker info >/dev/null 2>&1 && echo "docker daemon reachable" || echo "docker daemon NOT reachable"
```

If unreachable: start Docker Desktop (macOS) or the `docker`/`containerd` service
(Linux, e.g. `sudo systemctl status docker`). `docker compose config` (validation only)
does **not** require the daemon to be running; `docker compose up`/`ps`/`logs` do.

### PostgreSQL unavailable

```bash
docker compose ps postgres
docker compose logs postgres --tail 50
```

If the container isn't `healthy`, start it (`docker compose up -d postgres`) and wait
for the healthcheck (`pg_isready`) to pass. `tests/test_integration_health.py` and the
app's `/health/ready`-adjacent DB path will fail, not silently degrade, unless
`SKIP_INTEGRATION_TESTS=true` is set for the test run (see
[../deployment/ENVIRONMENT_VARIABLES.md](../deployment/ENVIRONMENT_VARIABLES.md)).

### Redis unavailable

```bash
docker compose ps redis
docker compose logs redis --tail 50
```

If unreachable, `GET /health/ready` returns `503` with `{"status": "degraded"}` (see
`check_redis_health()` in `redis_client.py`), and `tests/test_integration_health.py`'s
Redis test fails unless `SKIP_INTEGRATION_TESTS=true`.

### pytest event-loop errors

If you see `RuntimeError: ... attached to a different loop`,
`coroutine '...' was never awaited`, or stray `ResourceWarning: unclosed transport`
warnings when running `pytest -q`, this almost always means a test opened a **real**
database connection (via the real `SessionLocal`/`SqlAuditWriter`) instead of an
injected in-memory test double, and that connection was later garbage-collected under
a *different* test's event loop (`pytest-asyncio` creates a new loop per test function
by default in this project's configuration).

This exact class of bug occurred during this repository's own development and was
fixed by making audit writing **injectable**: `RepositoryWorkspaceService` and
`ScannerRunner` both accept an `audit_writer` parameter, and their test suites inject an
in-memory `RecordingAuditWriter` everywhere instead of touching `SessionLocal`/
`SqlAuditWriter`. If you add a new test that constructs `RepositoryWorkspaceService(...)`
or `ScannerRunner(...)` without passing `audit_writer=...`, it will default to the real
`SqlAuditWriter` and can reintroduce this warning class -- always inject a recording
writer in unit tests (see `tests/test_repository_workspace_service.py` and
`tests/test_scanner_runner.py` for the pattern).

## Git and GitHub/Bitbucket

### Git authentication problems (pushing to `origin`)

```bash
git remote -v
ssh -T git@github.com          # if using SSH
git ls-remote origin            # exercises whatever auth is configured, read-only
```

- HTTPS remotes: confirm a credential helper is configured
  (`git config --get credential.helper`) and that your GitHub personal access
  token/credentials haven't expired.
- SSH remotes: confirm your key is loaded (`ssh-add -l`) and registered with GitHub.

### GitHub 403 push errors

A `403` on `git push` (as opposed to a `401`) usually means the credentials are valid
but lack permission -- common causes: pushing to a branch protected against direct
pushes (push a feature branch and open a PR instead, per
[../development/DEVELOPMENT_WORKFLOW.md](../development/DEVELOPMENT_WORKFLOW.md)),
using a token that doesn't have the `repo` scope, or pushing to a fork/remote you don't
have write access to. Confirm the target remote and branch:

```bash
git remote get-url origin
git branch --show-current
```

Per [CLAUDE_CODE_RULES.md](../development/CLAUDE_CODE_RULES.md), an agent session
should not be pushing at all unless the user has explicitly asked for it in that
session -- if you hit a 403 during an agent-driven push, stop and confirm with the user
rather than trying alternate credentials or force-pushing.

## Repository workspace (Milestone 3)

### Clone timeout

The initial source-commit fetch exceeded `GIT_CLONE_TIMEOUT_SECONDS` (default 300s).
`RepositoryWorkspaceService` records this as a `TimeoutError`, retries up to
`GIT_NETWORK_MAX_RETRIES` times with backoff, and if still failing, cleans up the
workspace and raises. Diagnose by checking `AuditLog` for a `failure` event on that
workflow run, and confirm network reachability to the SCM host independently:

```bash
git ls-remote <clone_url>
```

If large repositories routinely exceed the timeout, raise
`GIT_CLONE_TIMEOUT_SECONDS` (see
[../deployment/ENVIRONMENT_VARIABLES.md](../deployment/ENVIRONMENT_VARIABLES.md)).

### Fetch timeout

Same as above, but for the separate target-commit fetch
(`GIT_FETCH_TIMEOUT_SECONDS`) -- independently configurable since the target commit
fetch happens after the source commit is already available.

### Workspace size exceeded

`_ensure_disk_space_available` (pre-fetch) and `_ensure_workspace_size_limit`
(post-fetch) both raise `ValueError` if `MAX_WORKSPACE_SIZE_MB` would be/was exceeded.
The workspace is cleaned up immediately (failure always cleans up regardless of
`WORKSPACE_RETENTION_HOURS`). If this happens routinely for legitimately large
repositories, raise `MAX_WORKSPACE_SIZE_MB` -- but also apply a real filesystem/
container quota on `WORKSPACE_ROOT` (see
[../deployment/PRODUCTION_DEPLOYMENT.md](../deployment/PRODUCTION_DEPLOYMENT.md#workspace-quotas)),
since this check is application-level, not a hard sandbox.

### Stale workspaces

If `WORKSPACE_RETENTION_HOURS > 0`, successful workspaces are retained on disk until
`RepositoryWorkspaceService.cleanup_stale_workspaces()` reaps them -- and nothing in
this repository schedules that call automatically (see
[../deployment/PRODUCTION_DEPLOYMENT.md](../deployment/PRODUCTION_DEPLOYMENT.md#cleanup-jobs)).
To inspect and manually reclaim:

```bash
# Inspect first
find "$WORKSPACE_ROOT" -maxdepth 4 -type d

# Remove everything (safe: WORKSPACE_ROOT only ever holds re-creatable clone artifacts)
rm -rf "$WORKSPACE_ROOT"/*
```

Prefer invoking `cleanup_stale_workspaces()` (respects `WORKSPACE_RETENTION_HOURS` and
prunes empty ancestor directories correctly) over the blunt `rm -rf` above when
possible; use the manual command only when you specifically want to clear everything
regardless of age.

## Scanner runtime (Milestone 4)

### How to read a `ScanResult`

Every scanner produces exactly one `ScanResult` with a `status`
(`ScannerExecutionStatus`), and one scanner's outcome never affects another's. Start
here:

| `status`        | Meaning | Where to look next |
|------------------|---------|----------------------|
| `COMPLETED`      | Ran successfully; `findings` may be empty (nothing found, or nothing applicable to scan). | Nothing to do. |
| `FAILED`         | Tool binary missing, unexpected exit code, or an unhandled exception during execution. | `error_message`, then the sections below. |
| `TIMEOUT`        | Exceeded `SCANNER_TIMEOUT_SECONDS`. | "Scanner times out" below. |
| `INCONCLUSIVE`   | Tool exited "successfully" but its output couldn't be parsed. | "Malformed / unparseable scanner output" below. |

`AggregatedScanResult.has_failures` is `True` if any scanner is `FAILED` or `TIMEOUT`.
Audit events (`scanner_failed`, `scanner_timeout`, etc. -- see
[SCANNER_RUNBOOK.md](SCANNER_RUNBOOK.md#monitoring-scan-activity-via-audit-events))
record the same information durably, since the per-scan output directory is deleted
immediately after each scan.

### Scanner missing ("tool_not_available", `FAILED`)

The scanner's binary (`shutil.which(adapter.binary_name())`) could not be found on
`PATH` for the process running the scan.

- **gitleaks** is the most common case: it's a Go binary, not pip-installable, and is
  not currently included in the `api` Docker image (see
  [../deployment/DOCKER_SETUP.md](../deployment/DOCKER_SETUP.md)). Install it (see
  [../deployment/LOCAL_SETUP.md](../deployment/LOCAL_SETUP.md#3-install-gitleaks-external-dependency-not-pip-installable))
  or confirm it's present in whatever environment is actually running the scan.
- For any other scanner, confirm `pip install -e ".[dev]"` (or the equivalent
  production install) actually completed, and that the process's `PATH` includes the
  virtualenv's `bin/` directory.
- Run the health check commands in
  [SCANNER_RUNBOOK.md](SCANNER_RUNBOOK.md#confirm-each-scanner-binary-is-available-and-reports-a-version)
  to confirm which binaries are actually resolvable in the current environment.

This never affects other scanners -- `ScannerRunner._run_one` isolates each adapter
independently.

### Scanner exits with an unexpected non-zero code (`FAILED`, `exit_code` set)

All six adapters treat exit codes `{0, 1}` as "ran successfully" (these tools use `1`
to mean "findings were found", not "the tool crashed"). Anything else is `FAILED`.
Common causes, per tool:

- **ruff**: exit code `2` usually means an invocation error (e.g. an invalid
  `--select` value, or a syntax so broken ruff itself errors rather than reports a
  lint finding). Check `error_message` (sanitized `stderr`, truncated to 2000 chars).
- **bandit**: non-{0,1} exit is rare; check for a Python version mismatch between the
  bandit install and the scanned code, or a totally unreadable file tree.
- **semgrep**: a low-level runtime crash (see "semgrep crashes with an OCaml/runtime
  error" below) or a genuinely invalid `--config` path (confirm the ruleset file
  described in
  [../deployment/LOCAL_SETUP.md](../deployment/LOCAL_SETUP.md#4-confirm-the-bundled-semgrep-ruleset-is-present)
  actually exists at the expected location).
- **pyright**: exit code `2`/`3` typically means a fatal configuration error (e.g. an
  unreadable `pyrightconfig.json` somewhere pyright picked up, though the adapter does
  not pass one intentionally) or a usage error.
- **gitleaks**: a non-{0,1} exit usually means gitleaks itself couldn't start (bad
  flags, unreadable source path) rather than a normal "leaks found" result.
- **pip-audit**: see "pip-audit fails or hangs" below -- most non-{0,1} failures here
  are network-related.

### Malformed / unparseable scanner output (`INCONCLUSIVE`)

The tool exited with a code in `{0, 1}` (i.e. it believes it ran fine), but
`adapter.parse_output` raised `ValueError` trying to read its stdout (or, for gitleaks,
its report file). This usually means:

- The installed tool version's output schema has drifted from what the adapter expects
  (compare the installed version against `*_VERSION` in
  [../deployment/ENVIRONMENT_VARIABLES.md](../deployment/ENVIRONMENT_VARIABLES.md); a
  `scanner_version_mismatch` log entry around the same time is a strong hint).
- stderr/stdout got mixed in a way that put non-JSON text where JSON was expected --
  check that no wrapper script or shell profile is injecting extra output onto stdout
  for the scanner binary.

To reproduce, run the same command the adapter builds directly. For example, for ruff:

```bash
cd <workspace-path>
ruff check --isolated --select=E,F,W,S --output-format=json .
echo "exit: $?"
```

(See each adapter's `build_command` in `src/protecto_prime_agent/scanners/adapters/`
for the exact argv used, per tool.)

### Scanner times out (`TIMEOUT`)

Exceeded `SCANNER_TIMEOUT_SECONDS` (default 120s). Independent per scanner -- one slow
scanner never blocks or delays the others (they run concurrently via `asyncio.gather`).

- For a large repository, consider raising `SCANNER_TIMEOUT_SECONDS` (and, if you're
  also hitting real CPU exhaustion, `SCANNER_CPU_SECONDS`).
- semgrep is typically the slowest of the six on large trees; if only semgrep times out
  consistently, that's the first variable to tune, or consider narrowing its ruleset
  (`src/protecto_prime_agent/scanners/rulesets/semgrep_python.yaml`).
- If a scanner *consistently* times out on ordinary-sized input, treat that as a bug
  report against that adapter's command construction, not just a config problem.

### semgrep crashes with an OCaml/runtime error

If semgrep fails with something like:

```
Fatal error: exception Failure("Failed to create system store X509 authenticator: ...")
```

this is almost always a resource-limit artifact, **not a real semgrep bug**. During
Milestone 4 development, applying `RLIMIT_NPROC` (process-count ulimit) locally caused
exactly this failure, because semgrep's OCaml runtime forks helper processes and
`RLIMIT_NPROC` is a per-UID, system-wide limit on most platforms (not per-process-tree),
so a modest value can be exhausted by unrelated processes on the same host/user. This is
why `LocalProcessExecutionBackend` deliberately does **not** apply `RLIMIT_NPROC` (or
`RLIMIT_AS`) -- see
[../architecture/milestone-4.md](../architecture/milestone-4.md#resource-limits). If
you see this error, check whether something *else* in your deployment (a wrapper
script, a container `ulimit` setting, systemd `LimitNPROC=`) is imposing a process-count
ulimit on the scanner process tree, and remove it -- enforce process-count limits via
the container backend's `--pids-limit` (cgroups) instead.

### pyright reports zero findings, or crashes outright, under a resource limit

Similarly, pyright wraps a Node.js runtime that reserves large virtual address ranges
that are never actually resident. Applying `RLIMIT_AS` (address-space ulimit) --
even at generous values like several GB -- causes pyright to crash immediately with a
Python traceback from its wrapper script, because the *reservation* is rejected, not
real memory usage. If you see pyright failing only in one specific environment, check
for an externally-imposed address-space ulimit (`ulimit -v`, a container's memory
cgroup being misapplied as a ulimit, etc.) and prefer cgroup-based memory limits
(`--memory` in the container backend) instead.

### pip-audit fails or hangs

pip-audit is the one scanner that requires network access (see
[../deployment/PRODUCTION_DEPLOYMENT.md](../deployment/PRODUCTION_DEPLOYMENT.md#pip-audits-network-access-requirement)).
If it fails or times out:

- Confirm the environment running the scan actually has egress to reach the
  vulnerability database (PyPI/OSV). In a container deployment, confirm the pip-audit
  scanner container is the intended exception to `--network none`.
- If there's no `requirements.txt` in the scanned workspace, pip-audit's `should_run`
  hook returns `False` and the scanner is recorded `COMPLETED` with zero findings --
  that is expected behavior, not a failure, and does not indicate a network problem.
- pip-audit never installs the audited packages; if you see anything resembling a
  `pip install` happening as part of a scan, that is a bug, not expected pip-audit
  behavior -- stop and investigate immediately (see
  [../deployment/PRODUCTION_DEPLOYMENT.md](../deployment/PRODUCTION_DEPLOYMENT.md#security-hardening-checklist)).

### Secret-shaped values are missing from a gitleaks or bandit finding's message

This is intentional, not a bug. gitleaks' `Secret`/`Match` fields and bandit's
hardcoded-secret checks (`B105`/`B106`/`B107`/`B108`) are redacted before a
`NormalizedFinding` is ever created -- see
[../architecture/milestone-4.md](../architecture/milestone-4.md#secret-redaction).
The finding still identifies the rule, file, and line; it deliberately never carries the
literal secret value.

### Nothing shows up in `SCANNER_OUTPUT_ROOT` after a scan

Expected -- the scanner runtime deletes each scan's output directory as soon as the scan
finishes, success or failure (see
[SCANNER_RUNBOOK.md](SCANNER_RUNBOOK.md#scanner-output-directory-and-cleanup)). Use the
`AuditLog` events for post-hoc investigation instead of scanner output files on disk.

## Database migrations

### Alembic migration commands fail with `KeyError: 'formatters'`

Verified in this repository's checked-in state: `alembic current` and
`alembic upgrade head` both raise:

```
KeyError: 'formatters'
```

from inside `logging.config.fileConfig(...)`, called by `alembic/env.py` because
`alembic.ini`'s `[alembic]` section exists but the file has no
`[loggers]`/`[handlers]`/`[formatters]` sections that `fileConfig` requires. This
happens before any database connection is attempted -- it is unrelated to database
reachability. Workaround: rely on `init_db()`'s automatic `Base.metadata.create_all` at
application startup for local development (see
[../deployment/LOCAL_SETUP.md](../deployment/LOCAL_SETUP.md#7-database-migrations));
fix `alembic.ini` before depending on Alembic as your production migration path (see
[../deployment/PRODUCTION_DEPLOYMENT.md](../deployment/PRODUCTION_DEPLOYMENT.md#database-migration)).

## Permission errors and generated-file hygiene

### Permission errors writing to `WORKSPACE_ROOT` / `SCANNER_OUTPUT_ROOT`

```bash
ls -ld "$WORKSPACE_ROOT" "$SCANNER_OUTPUT_ROOT"
id
```

Confirm the user running the application/tests owns (or has write access to) both
directories. Both default to paths under `/tmp`, which is normally world-writable with
the sticky bit set -- a permission error there usually means a previous run created the
directory as a different user (e.g. root inside a container, then a non-root process
locally). Fix by removing the offending directory (safe -- both only ever hold
re-creatable, ephemeral artifacts) and letting the application recreate it:

```bash
rm -rf "$WORKSPACE_ROOT" "$SCANNER_OUTPUT_ROOT"
```

### Generated files accidentally staged

Before committing (and this repository's standard verification always includes a
`git status` check -- see
[../development/DEVELOPMENT_WORKFLOW.md](../development/DEVELOPMENT_WORKFLOW.md#standard-verification-commands)):

```bash
git status --porcelain | grep -E "__pycache__|\.pyc$|\.egg-info|\.pytest_cache|\.ruff_cache|\.DS_Store"
```

This should print nothing. If it doesn't:

```bash
# Unstage the specific generated paths (safe -- does not delete anything)
git restore --staged <path>
```

If a generated path is tracked in git history already (shouldn't happen given
`.gitignore`, but if it does), remove it from tracking without deleting the local file:

```bash
git rm --cached <path>
```

Never run `git clean -fd` or `git reset --hard` to "clean up" without first running
`git status` and confirming exactly what would be removed -- both can destroy
uncommitted work that isn't actually generated output (see
[../development/CLAUDE_CODE_RULES.md](../development/CLAUDE_CODE_RULES.md#2-never-reset-restore-overwrite-or-delete-without-explicit-approval)).
