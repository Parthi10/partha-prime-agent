# Scanner runbook

Operational reference for running and maintaining the Milestone 4 scanner runtime. For
design rationale, see [docs/architecture/milestone-4.md](../architecture/milestone-4.md).
For environment variables, see
[docs/deployment/ENVIRONMENT_VARIABLES.md](../deployment/ENVIRONMENT_VARIABLES.md).
For the surrounding system, see
[docs/development/PROJECT_ARCHITECTURE.md](../development/PROJECT_ARCHITECTURE.md).

## How the scanner runtime works

`ScannerRunner.run_scan(request)` (`scanners/runner.py`) takes a `ScanRequest`
(workspace path, commit sha, workflow run id, repository id, optional per-call scanner
allowlist) and:

1. Creates an isolated, path-escape-checked output directory under
   `SCANNER_OUTPUT_ROOT`.
2. Resolves which adapters to run via `ScannerRegistry.resolve_enabled` (see "How
   scanners are selected" below).
3. Runs every resolved adapter **concurrently** (`asyncio.gather`), each wrapped in its
   own error handling so one adapter's crash, timeout, or malformed output never
   affects the others.
4. For each adapter: locates its binary (`shutil.which`), builds a fixed argument-list
   command (`adapter.build_command`), executes it through an `ExecutionBackend` with a
   minimal environment and resource limits, then parses its output
   (`adapter.parse_output`) into `NormalizedFinding` objects.
5. Cleans up the entire output directory in a `try/finally`, regardless of outcome.
6. Returns an `AggregatedScanResult` (in-memory only -- see
   [docs/development/PROJECT_ARCHITECTURE.md](../development/PROJECT_ARCHITECTURE.md#postgresql)
   for why findings are not yet persisted).

### The six enabled scanners

| Scanner | Tool purpose | Category produced | Notes |
|---------|---------------|---------------------|-------|
| **Ruff** | Python lint/style, plus flake8-bandit-style security rules (`S*` codes) | style, quality, security | Runs `--isolated` so a scanned repository's own ruff config never changes behavior |
| **Bandit** | Python security linter | security | Hardcoded-secret findings (`B105`/`B106`/`B107`/`B108`) are redacted -- see below |
| **Semgrep** | Pattern-based static analysis | security | Uses a bundled, offline ruleset (`scanners/rulesets/semgrep_python.yaml`) -- never semgrep's online registry |
| **Pyright** | Python static type checker | typing | |
| **Gitleaks** | Secret scanner | secret | Its own `Secret`/`Match` fields are redacted unconditionally -- see below |
| **pip-audit** | Dependency vulnerability scanner | dependency | The one scanner requiring network access (queries a vulnerability database); only runs if `requirements.txt` is present |

Full per-tool severity/category/confidence mapping is in
[docs/architecture/milestone-4.md](../architecture/milestone-4.md#per-tool-severitycategoryconfidence-mapping).

### Output normalization

Every adapter's `parse_output` produces `NormalizedFinding` objects with the same
fields regardless of tool: `scanner_name`, `rule_id`, `severity`, `category`,
`confidence`, `message`, `file_path` (always relative to the workspace root),
`line_number`, `column_number`, `fingerprint` (a stable, commit-independent sha256 of
scanner+rule+file+line+message), `commit_sha`, `raw_details_json` (the tool's own
result, sanitized).

### Repository code, dependencies, and scripts are never executed

Every adapter's `build_command` is a fixed, hand-written argument list -- **never**
templated from repository content. The scanner runtime never runs a scanned
repository's own test suite, setup scripts, `Makefile` targets, database migrations,
or application startup commands, and never installs that repository's dependencies
(pip-audit specifically reads `requirements.txt` version pins to query a vulnerability
database -- it never runs `pip install`). This is a hard invariant of every existing
adapter; preserve it in any new one.

## Local versus container execution

- **`LocalProcessExecutionBackend`** (the default, used in this repository's tests and
  for local development): runs each scanner as a plain host subprocess with an explicit
  argument list and `shell=False`, a wall-clock timeout, a `RLIMIT_CPU` CPU-time limit,
  and a minimal allowlisted environment. No filesystem/network isolation; memory and
  process-count limits are not enforced here (see
  [docs/architecture/milestone-4.md](../architecture/milestone-4.md#resource-limits)
  for why). See [docs/deployment/LOCAL_SETUP.md](../deployment/LOCAL_SETUP.md).
- **`ContainerExecutionBackend`** (the production-recommended backend, not yet wired to
  built images): constructs a hardened `docker run` invocation -- no Docker socket, no
  privileged mode, read-only workspace mount, dropped capabilities, `--network none`
  (except pip-audit), and cgroup-based memory/CPU/pids limits. See
  [docs/deployment/PRODUCTION_DEPLOYMENT.md](../deployment/PRODUCTION_DEPLOYMENT.md#scanner-images).

## Health and validation commands

Run before deploying any change that touches the scanner runtime, and periodically in
CI:

```bash
ruff check .
pyright
pytest -q
docker compose config
```

### Confirm each scanner binary is available and reports a version

```bash
ruff --version
bandit --version
semgrep --version
pyright --version
gitleaks version        # note: subcommand, not --version
pip-audit --version
```

If any of these fail with "command not found", that scanner will report `FAILED` /
`tool_not_available` at scan time -- every other scanner still runs normally (see
"One scanner failing never blocks the others" in
[docs/architecture/milestone-4.md](../architecture/milestone-4.md)). See
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### Confirm the semgrep ruleset is present

```bash
test -f src/protecto_prime_agent/scanners/rulesets/semgrep_python.yaml && echo OK
```

### Quick end-to-end smoke test

Run the scanner runtime against a throwaway directory to confirm the whole pipeline
works (this mirrors what `tests/test_scanner_adapters.py` does, without pytest):

```bash
python3 - <<'EOF'
import asyncio
from pathlib import Path
from protecto_prime_agent.config import get_settings
from protecto_prime_agent.scanners import ScanRequest, ScannerRuntimeConfig, ScannerRunner, build_default_registry
from protecto_prime_agent.scanners.audit import AuditWriter

class NullAuditWriter(AuditWriter):
    async def record(self, **kwargs) -> None:
        pass

async def main() -> None:
    workspace = Path("/tmp/scanner-smoke-test")
    workspace.mkdir(exist_ok=True)
    (workspace / "app.py").write_text("import os\n")  # unused import -> ruff F401

    registry = build_default_registry()
    config = ScannerRuntimeConfig.from_settings(get_settings())
    runner = ScannerRunner(registry, config, audit_writer=NullAuditWriter())
    request = ScanRequest(
        workspace_path=workspace,
        commit_sha="0" * 40,
        workflow_run_id="smoke-test",
        repository_id="smoke-test-repo",
    )
    result = await runner.run_scan(request)
    for scan_result in result.scan_results:
        print(scan_result.scanner_name, scan_result.status.value, len(scan_result.findings))

asyncio.run(main())
EOF
```

Expect `ruff COMPLETED 1` (the unused import) and every other scanner `COMPLETED 0`
(unless gitleaks isn't installed, in which case it prints `FAILED 0`).

## How scanners are selected: enabling and disabling individual scanners

Set `SCANNERS_ENABLED` to a comma-separated list of the scanners that should run:

```bash
# Disable semgrep only
SCANNERS_ENABLED=ruff,bandit,pyright,gitleaks,pip-audit

# Run only the secret scanner
SCANNERS_ENABLED=gitleaks
```

This is read once at `ScannerRuntimeConfig.from_settings` construction time. Restart
the process (or reconstruct `ScannerRuntimeConfig`) after changing it. A caller can also
override the enabled set for a single scan without touching the environment, by passing
`enabled_scanners=(...)` on `ScanRequest` directly.

A scanner that is disabled this way never runs and never appears in the aggregated
result -- it is not reported as `SKIPPED`, it is simply absent from
`AggregatedScanResult.scan_results`.

## Monitoring scan activity via audit events

Every scan emits `AuditLog` rows (entity_type `scanner_execution`) for:
`scan_started`, `scanner_started` (per scanner), one of
`scanner_completed`/`scanner_failed`/`scanner_timeout` (per scanner), `scan_completed`,
and `cleanup_completed`. Querying these gives a full timeline of any scan without
needing to inspect scanner output on disk (which is cleaned up immediately after each
scan -- see below).

```sql
SELECT action, entity_id, created_at, metadata_json
FROM audit_logs
WHERE entity_type = 'scanner_execution'
ORDER BY created_at DESC
LIMIT 50;
```

`entity_id` is `<repository_id>:<workflow_run_id>` for scan-level events and
`<repository_id>:<workflow_run_id>:<scanner_name>` for per-scanner events.

## Scanner output directory and cleanup

Each scan gets an isolated directory at
`<SCANNER_OUTPUT_ROOT>/<workflow_run_id>/<scanner_name>/`, containing that scanner's
raw (sanitized) output as `raw_output.txt` (or, for gitleaks, its native
`gitleaks-report.json`, read by the adapter and then also copied to `raw_output.txt`).
This directory tree is removed automatically in a `try/finally` around the whole scan --
**after both success and failure** -- so under normal operation there is nothing to
clean up manually.

If a process is killed hard enough to skip the `finally` block (e.g. `SIGKILL`, host
crash), orphaned directories can accumulate under `SCANNER_OUTPUT_ROOT`. To reclaim
them:

```bash
# Inspect what's there first
ls -la "$SCANNER_OUTPUT_ROOT"

# Remove everything (safe: this directory only ever holds ephemeral scan artifacts)
rm -rf "$SCANNER_OUTPUT_ROOT"/*
```

There is currently no automated stale-output reaper for the scanner runtime (unlike
Milestone 3's `RepositoryWorkspaceService.cleanup_stale_workspaces` for workspaces) --
the try/finally cleanup is expected to be sufficient in normal operation. If orphaned
scanner output directories become a recurring problem, that's worth tracking as a
follow-up.

## Troubleshooting individual scanner failures

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for a full walkthrough of every
`ScanResult` status and the specific failure modes of each of the six scanners
(missing binary, unexpected exit code, malformed output, timeout, resource-limit
artifacts, pip-audit network issues).

## Routine maintenance checklist

- [ ] Confirm all six tool versions are current and match `ENVIRONMENT_VARIABLES.md`'s
      `*_VERSION` defaults (or your deployment's overrides).
- [ ] Confirm `SCANNER_OUTPUT_ROOT` isn't accumulating orphaned directories.
- [ ] Spot-check recent `scanner_version_mismatch` log lines -- a persistent mismatch
      usually means a tool was upgraded without updating the corresponding `*_VERSION`
      variable (or vice versa).
- [ ] In a container deployment, confirm scanner images are still pinned to the
      versions you intend (see [PRODUCTION_DEPLOYMENT.md](../deployment/PRODUCTION_DEPLOYMENT.md)).
