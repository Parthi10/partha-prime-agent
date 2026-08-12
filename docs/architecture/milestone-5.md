# Milestone 5 architecture notes

## Scope

Milestone 5 wires the previously independent Milestone 2 (webhook ingestion), Milestone 3
(repository workspace), and Milestone 4 (scanner runtime) components together end-to-end: when
a webhook is accepted and a `WorkflowRun` is created, the platform now actually prepares a
workspace for the pull request's exact source commit and runs the scanner runtime against it,
then persists the resulting findings. It does not implement baseline comparison, merge
policy/merge blocking, GitHub/Bitbucket status/check publishing, email notifications, or any
LLM-driven review -- those remain later-milestone work. `PullRequest.merge_decision` and
`Finding.policy_blocking` are never touched by this milestone; they keep their existing
defaults (`pending` / `False`).

## Components

- `ScanOrchestrationService` (`src/protecto_prime_agent/services/scan_orchestration_service.py`)
  -- the new provider-agnostic orchestrator. Given the same `SCMProvider` and
  `PullRequestEvent` the webhook layer already parsed, plus the `WorkflowRun`/`PullRequest`/
  `Repository` ids created for that event, it:
  1. Marks `WorkflowRun`/`PullRequest.execution_status` `running`.
  2. Calls `RepositoryWorkspaceService.prepare_workspace` (Milestone 3) to clone/checkout the
     source commit.
  3. Calls `ScannerRunner.run_scan` (Milestone 4) against the prepared workspace.
  4. Persists the `AggregatedScanResult` to `ScanRun` (one row per scanner) and `Finding` (one
     row per normalized finding), correlated via `workflow_run_id` and `scan_run_id`.
  5. Calls `RepositoryWorkspaceService.mark_processing_complete` to clean up (or retain, per
     `WORKSPACE_RETENTION_HOURS`) the workspace.
  6. Marks `WorkflowRun`/`PullRequest.execution_status` `succeeded` (workspace preparation or
     scanner-runtime *crashes* mark it `failed`; an individual scanner adapter reporting
     `FAILED`/`TIMEOUT` does not -- that is recorded on its own `ScanRun` row and left for a
     later milestone's merge-policy logic to interpret).
  - `WorkspacePreparer` / `ScanExecutor` (same module) -- minimal `Protocol` interfaces
    describing exactly the two calls this service needs from the workspace and scanner
    components. `RepositoryWorkspaceService` and `ScannerRunner` already satisfy them
    structurally, so neither Milestone 3 nor Milestone 4 code changed; tests inject lightweight
    fakes instead of running real git/scanner subprocesses.
  - Reuses `AuditWriter`/`SqlAuditWriter` from the Milestone 3 workspace service module (both
    already live in the `services` package) rather than defining a third copy; audit events
    are written under `entity_type="scan_orchestration"`.
- `WebhookService` (`src/protecto_prime_agent/services/webhook_service.py`) -- now accepts an
  optional `background_tasks: BackgroundTasks` parameter on `handle_webhook` and an optional
  injectable `orchestrator: ScanOrchestrationService`. After a webhook is accepted (a new
  event, not a duplicate or an unsupported/ignored one) and its `WorkflowRun` row is committed,
  it schedules `ScanOrchestrationService.run` as a FastAPI background task -- the webhook
  response is returned to the SCM immediately; orchestration runs after the response is sent,
  never blocking or delaying the webhook acknowledgement. If `background_tasks` is omitted
  (e.g. existing unit tests that call `handle_webhook` directly), no orchestration is
  scheduled, so Milestone 2's webhook-only behavior is unchanged for those callers.
- `api/v1/webhooks.py` -- both webhook endpoints now take FastAPI's injected
  `BackgroundTasks` and pass it through to `WebhookService.handle_webhook`.

## Why background tasks, not a message queue

This project has no message broker or task queue (no Celery/RQ/arq dependency). Adding one is
out of scope for this milestone -- it would be new infrastructure, not "wiring together what
already exists." FastAPI's `BackgroundTasks` runs the orchestration coroutine in-process, after
the HTTP response is sent, using the same event loop as the request. This is adequate for this
milestone's scope (one orchestration per accepted webhook) but does not survive an application
restart mid-scan and provides no retry/backoff or cross-process work distribution -- see
"Remaining risks" below.

## Status transitions

`WorkflowRun.execution_status` / `PullRequest.execution_status` (the existing `ExecutionStatus`
enum from Milestone 1/2) now flow: `queued` (webhook accepted) -> `running` (orchestration
started) -> `succeeded` (workspace + scan completed and results persisted) or `failed`
(workspace preparation raised, or the scanner runtime itself raised -- not an individual
scanner reporting `FAILED`/`TIMEOUT`). `error_message` on `WorkflowRun` is set to a
secret-redacted, truncated (2000 char) string on failure, reusing
`repository_workspace_service.redact_secrets`.

## Persistence

- One `ScanRun` row per scanner adapter that ran (`scanner_name`, `commit_sha`,
  `execution_status` set to the scanner's own `ScannerExecutionStatus` value -- `COMPLETED`,
  `FAILED`, `TIMEOUT`, or `INCONCLUSIVE` -- `exit_code`, `log_reference` holding the sanitized
  error message when present, `started_at`/`completed_at`).
- One `Finding` row per `NormalizedFinding` produced by a `COMPLETED` scanner, linked to both
  its `scan_run_id` and the parent `workflow_run_id`. `policy_blocking` is left at its default
  (`False`); no milestone before the merge-policy milestone decides that.
- Both writes happen in a single transaction per stage (status transition, then results) via
  the same `SessionLocal` pattern already used by `WebhookService` and
  `RepositoryWorkspaceService` -- no new database session abstraction was introduced.

## Failure handling

- **Workspace preparation fails** (network error, invalid clone info, path escape, etc.):
  `RepositoryWorkspaceService.prepare_workspace` already cleans up and re-raises (Milestone 3
  behavior, unchanged). `ScanOrchestrationService` catches the exception, marks the workflow
  `failed` with a redacted error message, records an `orchestration_failed` audit event, and
  never calls the scanner runtime.
- **Scanner runtime crashes** (an exception escaping `ScannerRunner.run_scan` itself, not an
  individual adapter failure -- those are already caught inside `ScannerRunner` per Milestone
  4): marked `failed` the same way, but the workspace is still explicitly cleaned up
  afterward, since `ScannerRunner`'s own cleanup only covers its scanner output directory, not
  the Milestone 3 workspace.
- **A bug anywhere else in orchestration**: `ScanOrchestrationService.run` has an outer
  catch-all that logs a sanitized `orchestration_unhandled_error` event rather than letting an
  exception escape a fire-and-forget background task silently or crash the process.
- **Scheduling/running orchestration itself throws** (e.g. the background task callable
  raises): `WebhookService._trigger_orchestration` wraps the call in its own guard and logs
  `orchestration_trigger_failed`; this can never turn an already-sent 200 webhook response into
  an error.

## Testing

- `tests/test_scan_orchestration_service.py` -- successful end-to-end orchestration (status
  transitions, `ScanRun`/`Finding` persistence, workspace cleanup, audit events); workspace
  preparation failure (marks failed, scanner never invoked); scanner runtime crash (marks
  failed, workspace still cleaned up); a per-scanner failure that does not fail the overall
  orchestration; an unhandled exception with no live database that still does not propagate.
- `tests/test_webhook_persistence.py` -- orchestration is scheduled when `background_tasks` is
  provided (and receives the correct correlation id); orchestration is *not* scheduled when it
  is omitted (existing direct-call tests keep working unchanged); a crash inside the scheduled
  orchestration task is swallowed and never surfaces as a webhook failure.
- `tests/test_bitbucket_webhook.py::test_endpoint_accepts_valid_webhook` -- updated to patch
  `ScanOrchestrationService` so the existing end-to-end HTTP-router test does not attempt a
  real database connection or git clone when its background task runs.

## Remaining risks / known limitations

- **In-process background tasks, not a durable queue.** If the application process restarts or
  crashes between a webhook being accepted and its background task completing, that
  orchestration is lost -- there is no persisted queue to resume from. `WorkflowRun` would be
  left in `queued` or `running` with no automatic recovery. A future milestone introducing a
  real task queue (or a reconciliation job that re-queues stuck `WorkflowRun` rows) would
  address this.
- **No concurrency limit on simultaneous orchestrations.** Every accepted webhook schedules its
  own background task immediately; there is no bound on how many workspace clones or scanner
  runs can execute concurrently under a burst of webhooks. Milestone 3/4's own per-operation
  resource limits (timeouts, CPU/memory limits) still apply per scan, but nothing throttles the
  number of concurrent scans.
- **No retry on transient orchestration failure.** A workspace clone that fails due to a
  transient network error (beyond `RepositoryWorkspaceService`'s own bounded fetch retries) or
  a scanner runtime crash simply marks the workflow `failed`; nothing re-queues it.
- **`ScanOrchestrationService`'s default scanner runner uses `LocalProcessExecutionBackend`**,
  the same choice Milestone 4 made for its own tests -- `ContainerExecutionBackend` is still
  unused end-to-end in production, per Milestone 4's own known limitation (no scanner container
  images exist yet).
- **No status/check publishing back to GitHub/Bitbucket and no notification of any kind.** A PR
  author currently has no way to see that a scan ran or what it found other than querying the
  database directly -- publishing results is explicitly later-milestone scope.
