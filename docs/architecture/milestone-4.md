# Milestone 4 architecture notes

## Scope

Milestone 4 introduces a provider-agnostic scanner runtime that runs a fixed set of
static-analysis tools against the exact source commit checked out by the Milestone 3
`RepositoryWorkspaceService`, and normalizes every tool's output into one common finding
schema. It does not implement baseline comparison, merge policy or merge blocking,
GitHub/Bitbucket status publishing, email notifications, or any LLM functionality --
those are later milestones. It also does not persist scan runs or findings to the
database; `ScanRun`/`Finding` are existing Milestone 1 tables reserved for a future
milestone that wires this runtime's output into policy decisions and reporting. This
runtime only produces an in-memory `AggregatedScanResult` and emits `AuditLog` events.

## Enabled scanners

| Scanner   | Purpose                          | Category(ies) produced      |
|-----------|-----------------------------------|------------------------------|
| ruff      | Python lint / style               | style, quality, security     |
| bandit    | Python security linter            | security                     |
| semgrep   | Pattern-based static analysis     | security                     |
| pyright   | Python static type checker         | typing                       |
| gitleaks  | Secret scanner                    | secret                       |
| pip-audit | Dependency vulnerability scanner  | dependency                   |

All six are enabled by default (`SCANNERS_ENABLED`). Disabling one is a configuration
change (or a per-call `ScanRequest.enabled_scanners` override); the registry always
knows about all six regardless of which are enabled.

## Components

- `ScannerAdapter` (`scanners/interface.py`) -- the common interface every tool adapter
  implements: `build_command` (argv only, given a resolved binary path and an isolated
  output directory), `parse_output` (tool-specific text -> `NormalizedFinding` list),
  plus optional hooks `should_run`, `read_output`, `version_args`.
- `ScanRequest` / `ScanResult` / `NormalizedFinding` / `AggregatedScanResult`
  (`scanners/interface.py`) -- the request/response models. `ScanRequest` carries only a
  workspace path, commit sha, workflow run id, repository id, and an optional scanner
  allowlist -- nothing provider-specific.
- `ScannerExecutionStatus` (`enums.py`) -- `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`,
  `TIMEOUT`, `INCONCLUSIVE`, `SKIPPED`.
- `Severity` / `FindingCategory` / `Confidence` (`enums.py`) -- the fixed vocabularies
  below.
- `ScannerRegistry` / `build_default_registry` (`scanners/registry.py`) -- registers all
  six adapters; `resolve_enabled` filters to the configured/requested subset.
- `ScannerRuntimeConfig` (`scanners/config.py`) -- enabled scanners, output root,
  resource limits, and per-tool expected versions, all sourced from `Settings`.
- `ExecutionBackend` (`scanners/execution.py`) -- `LocalProcessExecutionBackend` (used by
  this milestone's tests and suitable for local dev) and `ContainerExecutionBackend`
  (constructs, and can run, fully isolated `docker run` invocations; see below).
- `ScannerRunner` (`scanners/runner.py`) -- orchestrates one scan across every enabled
  adapter, in parallel, each fully isolated from the others' failures; owns the isolated
  output directory lifecycle and all audit events.
- `AuditWriter` / `SqlAuditWriter` (`scanners/audit.py`) -- injectable audit sink,
  mirroring Milestone 3's pattern exactly, kept local to this package so the scanner
  runtime has no dependency on the `services` package.
- Adapters (`scanners/adapters/`) -- one file per tool; each only translates between
  `ScanRequest`/tool-specific argv and tool-specific output/`NormalizedFinding`.
- `scanners/rulesets/semgrep_python.yaml` -- a small, hand-authored, package-local
  ruleset (see "No dynamic downloads" below).

## Normalized finding schema

Every adapter produces `NormalizedFinding` objects with exactly these fields:
`scanner_name`, `rule_id`, `severity`, `category`, `confidence`, `message`, `file_path`,
`line_number`, `column_number`, `fingerprint`, `commit_sha`, `raw_details_json`.

- `file_path` is always normalized to be relative to the workspace root (via
  `to_relative_path`), regardless of whether the underlying tool reported an absolute or
  relative path -- findings never leak the host's absolute temp-directory layout.
- `fingerprint` (`compute_fingerprint`) is a sha256 of
  `scanner_name | rule_id | file_path | line_number | message`. It deliberately excludes
  `commit_sha`, so the same underlying issue keeps the same fingerprint across commits/
  runs -- required groundwork for future baseline comparison (not implemented here).
  Two identical inputs always produce the same fingerprint (verified in
  `test_scanner_normalization.py`).
- `raw_details_json` holds the tool's own (sanitized) result object for forensics, not
  used for anything else in this milestone.

### Severity values

`critical`, `high`, `medium`, `low`, `info`.

### Categories

`security`, `quality`, `typing`, `dependency`, `secret`, `style`.

### Per-tool severity/category/confidence mapping

| Scanner   | Rule/field driving severity                          | Category                | Confidence |
|-----------|-------------------------------------------------------|--------------------------|------------|
| ruff      | rule-code prefix: `S*`→high, `F*`→medium, else low     | `S*`→security, `F*`→quality, else style | medium (fixed) |
| bandit    | native `issue_severity` (low/medium/high)              | security (fixed)         | native `issue_confidence` |
| semgrep   | rule's own `severity` (ERROR→high, WARNING→medium, INFO→info) | security (fixed, this ruleset is security-only) | medium (fixed) |
| pyright   | native `severity` (error→high, warning→medium, information→info) | typing (fixed) | high (fixed; type errors are deterministic) |
| gitleaks  | fixed: critical                                        | secret (fixed)           | high (fixed) |
| pip-audit | fixed: high (tool provides no severity field)          | dependency (fixed)       | high (fixed; database-matched CVE) |

These are explicit, documented design decisions (not tool defaults) because three of the
six tools (semgrep via our own ruleset, gitleaks, pip-audit) don't provide a severity/
confidence axis that maps cleanly onto ours.

## Security model

### No platform secrets reach a scanner

Every scanner subprocess's environment is built by `build_minimal_env` -- an **allowlist**
of `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`, `PYTHONHASHSEED` copied from the parent
process, plus `SEMGREP_SEND_METRICS=off`. It never inherits the full parent environment,
so `DATABASE_PASSWORD`, `REDIS_PASSWORD`, `BITBUCKET_WEBHOOK_SECRET`,
`GITHUB_WEBHOOK_SECRET`, and any SCM access token can never reach a scanner process --
verified directly in `test_scanner_execution.py` and end-to-end through the runner in
`test_scanner_runner.py::test_no_platform_secrets_reach_scanner_environment`.

### Docker socket, privileged mode, capabilities

`ContainerExecutionBackend` never mounts `/var/run/docker.sock`, never sets
`--privileged`, always passes `--cap-drop ALL` and `--security-opt no-new-privileges`,
and runs as a non-root, unprivileged user (`--user 65534:65534`). Verified by
`test_scanner_execution.py`'s `build_docker_argv` tests.

### Filesystem isolation

- The repository workspace is mounted **read-only** (`:ro`) into the container.
- Only a dedicated, per-run output directory is mounted read-write, plus a small
  `noexec,nosuid` tmpfs at `/tmp` for scratch space tools may need despite the
  container's read-only root filesystem.
- `ScannerRunner._build_scan_output_dir` validates the workflow run id against a
  safe-name pattern and double-checks the resolved output path falls under
  `SCANNER_OUTPUT_ROOT` before creating it -- the same defense-in-depth path-escape
  guard used by `RepositoryWorkspaceService` in Milestone 3.
- Every scanner's raw output is also copied into that isolated per-scanner output
  directory (sanitized) for debugging, and the entire directory tree is removed in a
  `try/finally` around the whole scan, so cleanup happens after both success and
  failure (`test_cleanup_after_success`, `test_cleanup_after_scanner_failure`).

### Resource limits

- **Timeout**: enforced by both `asyncio.wait_for` and the subprocess's own `timeout=`
  in `LocalProcessExecutionBackend`, and by `docker run`'s own timeout handling wrapped
  the same way in `ContainerExecutionBackend`. A timed-out scanner is recorded as
  `TIMEOUT`, independently of every other scanner.
- **CPU**: `LocalProcessExecutionBackend` applies `RLIMIT_CPU` via `preexec_fn`.
  `ContainerExecutionBackend` applies `--cpus`.
- **Memory and process count**: enforced by `ContainerExecutionBackend` via docker's
  `--memory` and `--pids-limit` (cgroup-based, RSS/pids accounting). They are
  deliberately **not** applied as POSIX `RLIMIT_AS`/`RLIMIT_NPROC` in the local backend --
  this was empirically verified against the real pyright and semgrep binaries during
  development: pyright wraps a Node.js runtime that reserves large virtual address
  ranges never actually resident (RLIMIT_AS rejects the reservation itself, not real
  usage, so pyright crashes outright under any RLIMIT_AS value), and RLIMIT_NPROC is a
  per-UID system-wide limit on most platforms (including macOS), not a per-process-tree
  one, so a modest value can spuriously break an unrelated tool. cgroup-based limits
  don't have this false-positive problem, which is precisely why they -- not POSIX
  ulimits -- are the production control. See `execution.py`'s `_posix_resource_limiter`
  docstring for the full rationale.

### Never execute repository code or install dependencies

Every adapter's `build_command` is a fixed, hand-written argv template; none of it is
templated from repository content, and no adapter ever invokes `pip install`,
`npm install`, `make`, a repository's own test suite, setup scripts, migrations, or
application startup commands. pip-audit in particular is a dependency **vulnerability**
scanner: it resolves `requirements.txt` entries against a vulnerability database by
name/version metadata only -- it never runs `pip install -r requirements.txt`.

### No dynamic downloads during a scan

- ruff, bandit, gitleaks, and pyright use each tool's own built-in rules/typeshed; none
  of them make network calls to fetch rules or plugins during a scan.
- semgrep uses a small, hand-authored, package-local ruleset
  (`scanners/rulesets/semgrep_python.yaml`) via `--config <local path>`, never a
  registry config (`p/...`, `auto`), so no rules are ever fetched over the network.
  `SEMGREP_SEND_METRICS=off` and `--metrics=off` additionally disable its telemetry
  call.
- **pip-audit is the one exception**, and it is inherent to the tool's function, not
  "downloading a tool or its rules": it queries a public vulnerability database
  (PyPI/OSV) by package name and version. `PipAuditAdapter.requires_network = True`
  documents this explicitly; a production container for this adapter specifically would
  need network egress (ideally restricted to the vulnerability database), unlike the
  other five, which run with `--network none`.

### Secret redaction

- `sanitize_text` (shared by every adapter, and applied to all captured stdout/stderr/
  error text) strips URL-embedded credentials and common token shapes (`ghp_...`,
  `github_pat_...`, `AKIA...`, etc.) from anything logged, stored, or raised.
- gitleaks' own report includes the **literal leaked secret value** under `Secret` and
  `Match`. Generic pattern matching cannot catch an arbitrary secret shape, so
  `GitleaksAdapter` unconditionally strips those two fields (replacing them with
  `[REDACTED]`) before they ever become a `NormalizedFinding` or touch
  `raw_details_json` -- storing the raw value would just create a second, less-guarded
  copy of the very secret the scan exists to flag.
- bandit's hardcoded-secret checks (`B105`/`B106`/`B107`/`B108`) similarly echo the
  literal value in both `issue_text` and the `code` snippet. `BanditAdapter` replaces
  the message with a generic, rule-id-only sentence and redacts the `code` field for
  those specific rule ids.
- ruff's equivalent rule (`S105`, hardcoded-password) was verified empirically to name
  only the *variable*, not the secret value, so no extra redaction is required there --
  covered by a regression assertion in `test_scanner_adapters.py`.

### Argument lists, never shell=True

Every subprocess invocation across the scanner runtime (`LocalProcessExecutionBackend`,
`ContainerExecutionBackend`, and adapter `build_command` implementations) passes an
explicit argument list and never sets `shell=True`. Verified by
`test_all_adapters_use_argument_list_commands` (parametrized over all six adapters) and
the execution-backend tests.

## Failure and inconclusive handling

- **FAILED**: tool binary not found, non-zero exit code outside the tool's documented
  "ran successfully, found reportable issues" set (`{0, 1}` for all six tools here --
  each of these tools uses exit code 1 to mean findings were found, not that the tool
  crashed), or an unexpected exception anywhere in that scanner's execution path (caught
  by a blanket `except Exception` inside `ScannerRunner._run_one` so a bug in one
  adapter can never take down the others).
- **TIMEOUT**: the configured wall-clock timeout elapsed.
- **INCONCLUSIVE**: the tool exited with a "successful" code but its output could not be
  parsed (`adapter.parse_output` raised `ValueError`) -- the scan ran, but its result
  cannot be trusted, which is different from a hard failure.
- **SKIPPED**: reserved for scanners excluded by configuration (not returned as a
  `ScanResult` at all -- `ScannerRegistry.resolve_enabled` simply excludes them, so they
  never appear in `AggregatedScanResult.scan_results`).
- A scanner with nothing to do (`should_run` returns `False`, e.g. pip-audit with no
  `requirements.txt` present) is recorded as `COMPLETED` with zero findings -- it's an
  honest "there was nothing to check", not a failure.

`AggregatedScanResult.has_failures` reports whether any scanner ended `FAILED` or
`TIMEOUT`; `AggregatedScanResult.findings` flattens every scanner's findings (only
scanners that reached `COMPLETED` contribute findings).

## Audit events

`ScannerRunner` emits, via `AuditWriter`/`SqlAuditWriter` (entity_type
`scanner_execution`): `scan_started`, `scanner_started` and one of
`scanner_completed`/`scanner_failed`/`scanner_timeout` per adapter, `scan_completed`, and
`cleanup_completed`. As in Milestone 3, audit writing is injectable and best-effort: a
failure to write an audit event is logged as a sanitized `audit_write_failed` event
(action + entity_type + exception type only -- never the exception's message, which
could otherwise echo the very data being sanitized) and never blocks scanning.

## Provider-agnostic / Milestone 3 integration

`ScanRequest` only needs a `workspace_path`, `commit_sha`, `workflow_run_id`, and
`repository_id` -- exactly what `RepositoryWorkspaceService.prepare_workspace` already
returns (`workspace_path`) plus the same identifiers used to build that workspace. The
scanner runtime has no GitHub/Bitbucket-specific code and no dependency on the
`services` or `integrations` packages; wiring "call `ScannerRunner.run_scan` once a
workspace reaches `READY`" is a caller-side integration left to whichever future
milestone orchestrates the end-to-end PR workflow.

## Testing

- `test_scanner_normalization.py` -- redaction, fingerprint stability/uniqueness/commit-
  independence, path normalization.
- `test_scanner_execution.py` -- minimal-env secret exclusion, local backend timeout/
  non-zero-exit/missing-binary handling, container backend argv safety (no docker
  socket, no privileged mode, dropped capabilities, read-only + isolated mounts,
  resource limits, no secrets in argv).
- `test_scanner_registry.py` -- registration, enabled/disabled resolution, unknown-name
  handling, the default six-adapter registry.
- `test_scanner_runner.py` -- successful execution, non-zero exit, timeout, malformed
  output, missing binary, one-scanner-failure-not-blocking-others, aggregated result,
  disabled scanners, cleanup after success/failure, output-path traversal rejection,
  full audit-event lifecycle, no platform secrets in the scanner environment end-to-end.
- `test_scanner_adapters.py` -- real, local, temporary Python repository fixtures run
  through the actual installed ruff/bandit/semgrep/pyright/gitleaks binaries (severity/
  category mapping, rule-id normalization, secret redaction), pip-audit's `should_run`
  gate and deterministic canned-output parsing (no network dependency in the test
  itself), and malformed/empty-output and argument-list-only checks parametrized across
  all six adapters.

## Tool versions

Configurable via `RUFF_VERSION`, `BANDIT_VERSION`, `SEMGREP_VERSION`, `PYRIGHT_VERSION`,
`GITLEAKS_VERSION`, `PIP_AUDIT_VERSION` (defaults match the versions this milestone was
developed and tested against: ruff 0.15.21, bandit 1.9.4, semgrep 1.169.0, pyright
1.1.411, gitleaks 8.30.1, pip-audit 2.10.1). `ScannerRunner` detects each tool's actual
`--version` output at scan time and logs a non-fatal `scanner_version_mismatch` event if
it differs from the configured expectation -- this is observability, not an enforcement
gate, since the local-process backend runs whatever is on `PATH`. In production, the
container backend's per-scanner, version-pinned images are the actual enforcement point.

## Remaining risks / known limitations

- **Scanner container images are not built in this milestone.**
  `ContainerExecutionBackend` fully constructs (and can execute) the safe `docker run`
  invocation, but no `protecto-scanner-<tool>:<version>` images exist yet. Only
  `LocalProcessExecutionBackend` is exercised end-to-end by tests, exactly as the
  requirements permit ("a local process execution backend may be used for tests, but
  production design must clearly support isolated containers").
- **pip-audit requires network access** to query its vulnerability database. This is
  inherent to the tool, documented via `requires_network = True`, and distinct from
  "downloading a tool or rules during a scan". A hermetic/offline production
  environment would need to point pip-audit at a local vulnerability database mirror --
  not implemented here.
- **gitleaks is not pip-installable** (it's a Go binary); local dev/CI must install it
  separately (documented in the README). The container backend sidesteps this entirely
  since the image would bundle the binary.
- Severity/category/confidence values for semgrep, gitleaks, and pip-audit are fixed,
  documented defaults rather than tool-native signals, because those tools don't expose
  an equivalent axis in a way that maps cleanly onto ours (see the mapping table above).
