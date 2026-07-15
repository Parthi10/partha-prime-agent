# Milestone 3 architecture notes

## Scope

Milestone 3 introduces a provider-agnostic repository workspace service. Given a normalized
pull request event and a workflow run id, the service validates the source and target commit
SHAs, obtains provider-specific clone information (including a real repository full name —
never a placeholder host), clones the exact source commit into an isolated on-disk workspace,
fetches and verifies the target commit, checks out the source commit in detached HEAD mode,
and generates a unified diff between the target and source commits for downstream review.
This milestone does not implement scanning, policy enforcement, or LLM-driven review
(Milestone 4).

## Components

- `RepositoryWorkspaceService` (`src/protecto_prime_agent/services/repository_workspace_service.py`)
  — provider-agnostic workspace lifecycle: path validation, cloning, verification, diff
  generation, cleanup, and stale-workspace reaping.
- `AuditWriter` / `SqlAuditWriter` (same module) — an injectable sink for lifecycle audit
  events. Production code uses `SqlAuditWriter`, which writes to the database and never
  raises; unit tests inject an in-memory recording writer so git-focused tests never open a
  real database connection.
- `CloneInfo` on the `SCMProvider` protocol (`src/protecto_prime_agent/integrations/scm.py`)
  — the only provider-specific surface the workspace service depends on. GitHub and
  Bitbucket providers each implement `get_clone_info` independently, deriving the clone URL
  from the real `repository_full_name` captured off the webhook payload (e.g.
  `https://github.com/octo-org/demo-repo.git`, `https://bitbucket.org/octo-workspace/demo-repo.git`)
  — never a placeholder host such as `github.example`. The workspace service has no
  GitHub- or Bitbucket-specific code.

## Workspace lifecycle

1. **CREATED** — the workspace directory path is validated and created; a `workspace_created`
   audit event is recorded.
2. **CLONING** — clone information is fetched from the provider and validated, and available
   disk space is checked before any fetch begins; a `clone_started` audit event is recorded.
   The source commit is fetched with the clone timeout, the target commit is fetched with the
   separate fetch timeout, both fetches are retried a bounded number of times on transient
   network failures, both commits are verified to exist, and the workspace size is checked
   against `MAX_WORKSPACE_SIZE_MB` before anything is checked out.
3. **READY** — the source commit is checked out in detached HEAD mode, a `clone_completed`
   audit event is recorded, `git diff --unified=20 <target_sha> <source_sha>` is generated
   and written to `diff.patch`, and a `diff_generated` audit event is recorded.
4. **FAILED** — any exception during the above steps records a `failure` audit event
   (with the error message credential-redacted) and triggers workspace cleanup **immediately**,
   regardless of the configured retention.
5. **CLEANED** — `cleanup_workspace` removes the workspace directory and records a
   `cleanup_completed` audit event. It is used on the failure path, and can be called
   directly by a caller that is done with a workspace.

## Successful-workflow retention

A `READY` workspace is *not* deleted automatically — later processing (e.g. Milestone 4
scanning) needs the checked-out source tree and generated diff. Once the workflow
orchestrator has finished with a workspace, it calls
`RepositoryWorkspaceService.mark_processing_complete(workspace_path)`:

- `WORKSPACE_RETENTION_HOURS=0` — clean up immediately when processing completes.
- `WORKSPACE_RETENTION_HOURS>0` — retain the workspace on disk for debugging; it is later
  reaped by `cleanup_stale_workspaces` once it is older than the configured retention window.
  `cleanup_stale_workspaces` targets the exact known workspace depth
  (`repository_id/pull_request_id/source_sha/workflow_run_id`) and prunes now-empty ancestor
  directories, but never removes `WORKSPACE_ROOT` itself.

Failure always cleans up immediately (see step 4 above) irrespective of
`WORKSPACE_RETENTION_HOURS` — retention only applies to workspaces that reached `READY`.

## Private-repository authentication

Tokens for private-repository access are never embedded in a clone URL and never written to
`.git/config` or the database:

- `_validate_clone_url` rejects any clone URL containing `user:pass@` or `user@` outright.
- `credential.helper` is disabled (`-c credential.helper=`) on every git invocation, so git
  never reads or writes a cached credential to disk, and `GIT_TERMINAL_PROMPT=0` prevents a
  blocking interactive prompt if no credential is available.
- When `CloneInfo.access_token` is supplied, the service wraps only the fetch step in an
  **ephemeral `GIT_ASKPASS` helper** (`_ephemeral_askpass_env`): a small, secret-free shell
  script is written to a fresh, owner-only-permission temp directory; the actual token is
  passed to the git subprocess only through its in-memory environment
  (`GIT_ASKPASS_TOKEN`/`GIT_ASKPASS_USERNAME`), never as a command-line argument and never
  written into the script file itself. The script directory is removed as soon as the fetch
  operation (including any of its bounded retries) completes, whether it succeeded or failed.
- Git command stdout, stderr, and error messages are passed through a redaction filter
  (`redact_secrets`) that strips embedded URL credentials and common token formats before
  they are logged, stored in an audit event, or raised as an exception — an additional,
  defense-in-depth layer on top of the fact that the token is never part of any command
  output in the first place.
- GitHub and Bitbucket providers do not yet source a real token from an external secret
  store or OAuth/App flow (that wiring is Milestone 4 scope); the mechanism above is the
  secure path any future token source must use.

## Disk and workspace size protection

- **Pre-fetch check**: before any clone/fetch begins, `_ensure_disk_space_available` checks
  that the filesystem backing `WORKSPACE_ROOT` has at least `MAX_WORKSPACE_SIZE_MB` of free
  space, and aborts (cleaning up immediately) if not.
- **Post-fetch check**: `_ensure_workspace_size_limit` sums actual on-disk workspace size
  after both commits are fetched and rejects (cleaning up immediately) if it exceeds
  `MAX_WORKSPACE_SIZE_MB`, before checkout doubles the footprint in the working tree.
- Both checks are application-level, best-effort guards, not a hard sandbox. **Production
  deployments should additionally apply an OS-level quota** — a dedicated filesystem/volume
  quota, or a container ephemeral-storage/cgroup limit — on `WORKSPACE_ROOT`, so that a
  single runaway workspace cannot exhaust the host regardless of an application-level bug.

## Other security notes

- Every git invocation uses an explicit argument list and `shell=False`; `shell=True` is
  never used anywhere in the service.
- Source and target commit SHAs are validated against a strict 40-character hex pattern
  before any git command runs.
- Workspace path components (repository id, pull request id, source commit SHA, workflow
  run id) are each validated against a safe-name pattern, and the resolved final path is
  double-checked to fall under `WORKSPACE_ROOT` before any directory is created.
- The service only ever executes a fixed set of `git` subcommands (`init`, `remote add`,
  `fetch`, `checkout --detach`, `diff`, `rev-parse`). It never executes code from the
  cloned repository and never installs repository dependencies. A freshly `git init`'d
  workspace has no executable hook scripts, and git hooks are never transferred by `fetch`,
  so no repository-controlled code runs as a side effect of cloning or checkout.
- Clone and fetch operations enforce independent timeouts (`GIT_CLONE_TIMEOUT_SECONDS`,
  `GIT_FETCH_TIMEOUT_SECONDS`) and bounded retries with backoff
  (`GIT_NETWORK_MAX_RETRIES`, `GIT_NETWORK_RETRY_BACKOFF_SECONDS`) for transient network
  failures. Local, non-network operations (init, checkout, diff, rev-parse) are not retried.
- Audit-write failures never log raw SQL, bind parameters, or full exception text — only a
  sanitized, structured `audit_write_failed` event naming the action and the exception type.

## Testing

`tests/test_repository_workspace_service.py` injects an in-memory `RecordingAuditWriter` (or
a mocked `SessionLocal` when testing `SqlAuditWriter` directly) into every test, so no test
opens a real database connection. It exercises the service against local, temporary bare git
repositories (no network access, no external SCM dependency) and covers: exact source commit
checkout, target commit availability, detached HEAD state, diff contents, malformed SHA
rejection, path traversal rejection, timeout handling, subprocess failure, bounded retry
recovery and exhaustion, secret redaction, workspace size enforcement, pre-fetch disk-space
enforcement, cleanup after success and failure, stale workspace cleanup (including ignoring
recently-used workspaces and pruning empty ancestor directories), both zero- and
positive-retention `mark_processing_complete` behavior, the ephemeral GIT_ASKPASS helper's
creation/removal, and that an access token never appears in subprocess argv, git output,
raised exceptions, audit metadata, or `.git/config`.

`tests/test_clone_info.py` verifies that GitHub and Bitbucket clone URLs are derived from
real repository full-name metadata and never fall back to a placeholder host.
