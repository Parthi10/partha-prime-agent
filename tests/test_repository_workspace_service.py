from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from protecto_prime_agent.integrations.scm import CloneInfo, PullRequestEvent, SCMProvider
from protecto_prime_agent.services.repository_workspace_service import (
    AuditWriter,
    GitCommandError,
    RepositoryWorkspaceService,
    SqlAuditWriter,
    redact_secrets,
)


class DummyProvider(SCMProvider):
    def __init__(self, clone_url: str, access_token: str | None = None, access_username: str = "x-access-token") -> None:
        self.clone_url = clone_url
        self.access_token = access_token
        self.access_username = access_username

    async def validate_webhook(self, body: bytes, signature: str | None) -> bool:
        return True

    async def parse_pull_request_event(self, payload: dict[str, object]) -> PullRequestEvent | None:
        raise NotImplementedError

    async def get_clone_info(self, event: PullRequestEvent) -> CloneInfo | None:
        return CloneInfo(
            clone_url=self.clone_url,
            repository_name="demo",
            access_token=self.access_token,
            access_username=self.access_username,
        )


class RecordingAuditWriter(AuditWriter):
    """Test double: records events in memory instead of touching the database."""

    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    async def record(self, *, entity_type: str, entity_id: str, action: str, actor: str, metadata_json: str) -> None:
        self.events.append(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "actor": actor,
                "metadata_json": metadata_json,
            }
        )


def _build_bare_repo_with_pr(tmp_path: Path) -> tuple[Path, str, str]:
    repo_dir = tmp_path / "remote.git"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "--bare", str(repo_dir)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "clone", str(repo_dir), str(tmp_path / "source")], check=True, capture_output=True, text=True)
    source_dir = tmp_path / "source"
    subprocess.run(["git", "-C", str(source_dir), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(source_dir), "config", "user.name", "Test User"], check=True)
    (source_dir / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source_dir), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(source_dir), "commit", "-m", "init"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(source_dir), "push", "origin", "HEAD:main"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(source_dir), "checkout", "-b", "feature/test"], check=True, capture_output=True, text=True)
    (source_dir / "README.md").write_text("updated\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source_dir), "commit", "-am", "update"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(source_dir), "push", "origin", "HEAD:feature/test"], check=True, capture_output=True, text=True)

    source_commit = subprocess.check_output(["git", "-C", str(source_dir), "rev-parse", "HEAD"], text=True).strip()
    target_commit = subprocess.check_output(["git", "-C", str(source_dir), "rev-parse", "main"], text=True).strip()
    return repo_dir, source_commit, target_commit


def _make_event(source_commit: str, target_commit: str) -> PullRequestEvent:
    return PullRequestEvent(
        event_type="pull_request",
        repository_id="repo-123",
        pull_request_id="pr-456",
        source_branch="feature/test",
        target_branch="main",
        source_commit_sha=source_commit,
        target_commit_sha=target_commit,
        repository_full_name="acme/demo-repo",
        provider_event_id="opened",
    )


async def _prepare(
    tmp_path: Path,
    repo_dir: Path,
    source_commit: str,
    target_commit: str,
    audit_writer: AuditWriter | None = None,
    access_token: str | None = None,
) -> tuple[dict, RepositoryWorkspaceService, PullRequestEvent, RecordingAuditWriter]:
    writer = audit_writer or RecordingAuditWriter()
    provider = DummyProvider(f"file://{repo_dir}", access_token=access_token)
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=writer)
    event = _make_event(source_commit, target_commit)
    result = await service.prepare_workspace(provider, event, workflow_run_id="wf-001")
    return result, service, event, writer  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_valid_workspace_creation(tmp_path: Path) -> None:
    repo_dir, source_commit, target_commit = _build_bare_repo_with_pr(tmp_path)
    result, _service, _event, _writer = await _prepare(tmp_path, repo_dir, source_commit, target_commit)

    assert result["status"] == "READY"
    assert Path(result["workspace_path"]).exists()
    assert Path(result["diff_path"]).exists()


@pytest.mark.asyncio
async def test_exact_source_checkout(tmp_path: Path) -> None:
    repo_dir, source_commit, target_commit = _build_bare_repo_with_pr(tmp_path)
    result, _service, _event, _writer = await _prepare(tmp_path, repo_dir, source_commit, target_commit)

    workspace_path = Path(result["workspace_path"])
    checked_out_head = subprocess.check_output(
        ["git", "-C", str(workspace_path), "rev-parse", "HEAD"], text=True
    ).strip()
    assert checked_out_head == source_commit
    assert (workspace_path / "README.md").read_text(encoding="utf-8") == "updated\n"


@pytest.mark.asyncio
async def test_target_commit_available(tmp_path: Path) -> None:
    repo_dir, source_commit, target_commit = _build_bare_repo_with_pr(tmp_path)
    result, _service, _event, _writer = await _prepare(tmp_path, repo_dir, source_commit, target_commit)

    workspace_path = Path(result["workspace_path"])
    verify = subprocess.run(
        ["git", "-C", str(workspace_path), "rev-parse", "--verify", target_commit],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0
    assert verify.stdout.strip() == target_commit


@pytest.mark.asyncio
async def test_detached_head(tmp_path: Path) -> None:
    repo_dir, source_commit, target_commit = _build_bare_repo_with_pr(tmp_path)
    result, _service, _event, _writer = await _prepare(tmp_path, repo_dir, source_commit, target_commit)

    workspace_path = Path(result["workspace_path"])
    symbolic_ref = subprocess.run(
        ["git", "-C", str(workspace_path), "symbolic-ref", "-q", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert symbolic_ref.returncode != 0


@pytest.mark.asyncio
async def test_diff_contents(tmp_path: Path) -> None:
    repo_dir, source_commit, target_commit = _build_bare_repo_with_pr(tmp_path)
    result, _service, _event, _writer = await _prepare(tmp_path, repo_dir, source_commit, target_commit)

    diff_text = Path(result["diff_path"]).read_text(encoding="utf-8")
    assert "README.md" in diff_text
    assert "-hello" in diff_text
    assert "+updated" in diff_text


@pytest.mark.asyncio
async def test_audit_events_recorded_on_success(tmp_path: Path) -> None:
    repo_dir, source_commit, target_commit = _build_bare_repo_with_pr(tmp_path)
    _result, _service, _event, writer = await _prepare(tmp_path, repo_dir, source_commit, target_commit)

    recorded_actions = [e["action"] for e in writer.events]
    assert recorded_actions == [
        "workspace_created",
        "clone_started",
        "clone_completed",
        "diff_generated",
    ]


@pytest.mark.asyncio
async def test_audit_event_recorded_on_failure(tmp_path: Path) -> None:
    provider = DummyProvider("https://user@example.com/repo.git")
    writer = RecordingAuditWriter()
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=writer)
    event = PullRequestEvent(
        event_type="pull_request",
        repository_id="repo-1",
        pull_request_id="pr-1",
        source_branch="feature/test",
        target_branch="main",
        source_commit_sha="a" * 40,
        target_commit_sha="b" * 40,
        repository_full_name="acme/demo-repo",
        provider_event_id="opened",
    )

    with pytest.raises(ValueError):
        await service.prepare_workspace(provider, event, workflow_run_id="wf-err")

    recorded_actions = [e["action"] for e in writer.events]
    assert "failure" in recorded_actions
    assert "cleanup_completed" in recorded_actions


@pytest.mark.asyncio
async def test_path_traversal_rejection(tmp_path: Path) -> None:
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())
    event = PullRequestEvent(
        event_type="pull_request",
        repository_id="../evil",
        pull_request_id="pr-1",
        source_branch="feature/test",
        target_branch="main",
        source_commit_sha="a" * 40,
        target_commit_sha="b" * 40,
        repository_full_name="acme/demo-repo",
        provider_event_id="opened",
    )

    with pytest.raises(ValueError):
        service.build_workspace_path(event, workflow_run_id="wf-1")


@pytest.mark.asyncio
async def test_malformed_sha_rejection() -> None:
    service = RepositoryWorkspaceService(workspace_root=Path("/tmp/workspaces"), audit_writer=RecordingAuditWriter())
    event = PullRequestEvent(
        event_type="pull_request",
        repository_id="repo-1",
        pull_request_id="pr-1",
        source_branch="feature/test",
        target_branch="main",
        source_commit_sha="invalid-sha",
        target_commit_sha="b" * 40,
        repository_full_name="acme/demo-repo",
        provider_event_id="opened",
    )

    with pytest.raises(ValueError):
        service.validate_commit_sha(event.source_commit_sha)


@pytest.mark.asyncio
async def test_timeout_handling(tmp_path: Path) -> None:
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())

    with patch("protecto_prime_agent.services.repository_workspace_service.asyncio.to_thread", side_effect=TimeoutError("timeout")):
        with pytest.raises(TimeoutError):
            await service._run_git_command(["git", "clone"], cwd=tmp_path)


@pytest.mark.asyncio
async def test_subprocess_failure(tmp_path: Path) -> None:
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())

    with patch("protecto_prime_agent.services.repository_workspace_service.asyncio.to_thread", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            await service._run_git_command(["git", "clone"], cwd=tmp_path)


@pytest.mark.asyncio
async def test_bounded_retry_recovers_from_transient_failure(tmp_path: Path) -> None:
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())
    service.network_retry_backoff_seconds = 0.01
    service.max_network_retries = 2

    call_count = 0

    async def flaky(_command: list[str], cwd: Path | None = None, timeout: int | None = None, extra_env: dict | None = None) -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise GitCommandError("git_command_failed: could not resolve host")
        return "ok"

    with patch.object(service, "_run_git_command", side_effect=flaky):
        result = await service._run_network_git_command(["git", "fetch"], cwd=tmp_path, timeout=1)

    assert result == "ok"
    assert call_count == 3


@pytest.mark.asyncio
async def test_bounded_retry_gives_up_after_max_attempts(tmp_path: Path) -> None:
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())
    service.network_retry_backoff_seconds = 0.01
    service.max_network_retries = 1

    call_count = 0

    async def always_fails(_command: list[str], cwd: Path | None = None, timeout: int | None = None, extra_env: dict | None = None) -> str:
        nonlocal call_count
        call_count += 1
        raise GitCommandError("git_command_failed: connection reset")

    with patch.object(service, "_run_git_command", side_effect=always_fails):
        with pytest.raises(GitCommandError):
            await service._run_network_git_command(["git", "fetch"], cwd=tmp_path, timeout=1)

    assert call_count == 2  # initial attempt + 1 retry


def test_redact_secrets_strips_url_credentials_and_tokens() -> None:
    text = (
        "fatal: unable to access 'https://user:s3cr3t@example.com/repo.git/': "
        "Authorization: Bearer abcdef123456 token=ghp_abcdefghijklmnopqrstuvwx"
    )
    redacted = redact_secrets(text)

    assert "s3cr3t" not in redacted
    assert "abcdef123456" not in redacted
    assert "ghp_abcdefghijklmnopqrstuvwx" not in redacted
    assert "[REDACTED]" in redacted


@pytest.mark.asyncio
async def test_workspace_size_enforcement(tmp_path: Path) -> None:
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())
    service.max_workspace_size_mb = 1

    workspace = tmp_path / "oversized"
    workspace.mkdir()
    (workspace / "big.bin").write_bytes(b"0" * 2_000_000)  # ~2 MB, exceeds the 1 MB limit

    with pytest.raises(ValueError):
        service._ensure_workspace_size_limit(workspace)


@pytest.mark.asyncio
async def test_disk_space_check_rejects_when_insufficient(tmp_path: Path) -> None:
    repo_dir, source_commit, target_commit = _build_bare_repo_with_pr(tmp_path)
    writer = RecordingAuditWriter()
    provider = DummyProvider(f"file://{repo_dir}")
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=writer)
    service.max_workspace_size_mb = 1
    event = _make_event(source_commit, target_commit)

    fake_usage = type("usage", (), {"total": 10_000_000, "used": 9_999_999, "free": 1})()
    with patch("protecto_prime_agent.services.repository_workspace_service.shutil.disk_usage", return_value=fake_usage):
        with pytest.raises(ValueError, match="insufficient_disk_space"):
            await service.prepare_workspace(provider, event, workflow_run_id="wf-disk")

    workspace_path = service.build_workspace_path(event, "wf-disk")
    assert not workspace_path.exists()
    recorded_actions = [e["action"] for e in writer.events]
    assert "failure" in recorded_actions
    assert "cleanup_completed" in recorded_actions


@pytest.mark.asyncio
async def test_cleanup_behavior(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "artifact.txt").write_text("data", encoding="utf-8")

    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())
    await service.cleanup_workspace(workspace)

    assert not workspace.exists()


@pytest.mark.asyncio
async def test_stale_workspace_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    old_workspace = root / "repo" / "pr" / "sha" / "wf"
    old_workspace.mkdir(parents=True)
    (old_workspace / "old.txt").write_text("old", encoding="utf-8")
    old_workspace.touch()

    service = RepositoryWorkspaceService(workspace_root=root, audit_writer=RecordingAuditWriter())
    cleaned = await service.cleanup_stale_workspaces(retention_hours=0)

    assert cleaned == [old_workspace]
    assert not old_workspace.exists()
    assert not (root / "repo").exists()  # empty ancestor directories are pruned
    assert root.exists()  # the workspace root itself is preserved


@pytest.mark.asyncio
async def test_stale_workspace_cleanup_ignores_fresh_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    fresh_workspace = root / "repo" / "pr" / "sha" / "wf"
    fresh_workspace.mkdir(parents=True)
    (fresh_workspace / "recent.txt").write_text("recent", encoding="utf-8")

    service = RepositoryWorkspaceService(workspace_root=root, audit_writer=RecordingAuditWriter())
    cleaned = await service.cleanup_stale_workspaces(retention_hours=24)

    assert cleaned == []
    assert fresh_workspace.exists()


@pytest.mark.asyncio
async def test_mark_processing_complete_zero_retention_cleans_immediately(tmp_path: Path) -> None:
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())
    service.retention_hours = 0
    workspace = tmp_path / "workspaces" / "repo" / "pr" / "sha" / "wf"
    workspace.mkdir(parents=True)
    (workspace / "f.txt").write_text("data", encoding="utf-8")

    cleaned_immediately = await service.mark_processing_complete(workspace)

    assert cleaned_immediately is True
    assert not workspace.exists()


@pytest.mark.asyncio
async def test_mark_processing_complete_positive_retention_retains_workspace(tmp_path: Path) -> None:
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())
    service.retention_hours = 24
    workspace = tmp_path / "workspaces" / "repo" / "pr" / "sha" / "wf"
    workspace.mkdir(parents=True)
    (workspace / "f.txt").write_text("data", encoding="utf-8")

    cleaned_immediately = await service.mark_processing_complete(workspace)

    assert cleaned_immediately is False
    assert workspace.exists()


def test_ephemeral_askpass_env_creates_and_removes_script(tmp_path: Path) -> None:
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())

    with service._ephemeral_askpass_env("tok-123", "x-access-token") as env:
        assert env is not None
        assert env["GIT_ASKPASS_TOKEN"] == "tok-123"
        askpass_path = Path(env["GIT_ASKPASS"])
        assert askpass_path.exists()
        script_content = askpass_path.read_text(encoding="utf-8")
        assert "tok-123" not in script_content

    assert not askpass_path.exists()
    assert not askpass_path.parent.exists()


def test_ephemeral_askpass_env_noop_without_token(tmp_path: Path) -> None:
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=RecordingAuditWriter())

    with service._ephemeral_askpass_env(None, "x-access-token") as env:
        assert env is None


@pytest.mark.asyncio
async def test_access_token_never_in_argv_stdout_or_git_config(tmp_path: Path) -> None:
    repo_dir, source_commit, target_commit = _build_bare_repo_with_pr(tmp_path)
    token = "super-secret-token-value"
    recorded_calls: list[tuple[list[str], dict[str, str]]] = []
    real_run = subprocess.run

    def spy_run(argv, **kwargs):
        recorded_calls.append((list(argv), dict(kwargs.get("env") or {})))
        return real_run(argv, **kwargs)

    with patch("protecto_prime_agent.services.repository_workspace_service.subprocess.run", side_effect=spy_run):
        result, _service, _event, writer = await _prepare(
            tmp_path, repo_dir, source_commit, target_commit, access_token=token
        )

    assert result["status"] == "READY"

    for argv, _env in recorded_calls:
        assert token not in argv
        assert token not in " ".join(argv)

    fetch_envs = [env for argv, env in recorded_calls if "fetch" in argv]
    assert fetch_envs, "expected at least one fetch invocation"
    assert all(env.get("GIT_ASKPASS_TOKEN") == token for env in fetch_envs)

    workspace_path = Path(result["workspace_path"])
    git_config_text = (workspace_path / ".git" / "config").read_text(encoding="utf-8")
    assert token not in git_config_text

    for recorded in writer.events:
        assert token not in recorded["metadata_json"]

    leftover_askpass_dirs = list(Path(tempfile.gettempdir()).glob("ppa-askpass-*"))
    assert leftover_askpass_dirs == []


@pytest.mark.asyncio
async def test_access_token_absent_from_errors_and_audit_on_failure(tmp_path: Path) -> None:
    token = "another-secret-token"  # noqa: S105 - test fixture value, not a real credential
    provider = DummyProvider("file:///nonexistent/repo.git", access_token=token)
    writer = RecordingAuditWriter()
    service = RepositoryWorkspaceService(workspace_root=tmp_path / "workspaces", audit_writer=writer)
    event = PullRequestEvent(
        event_type="pull_request",
        repository_id="repo-err",
        pull_request_id="pr-err",
        source_branch="feature/test",
        target_branch="main",
        source_commit_sha="a" * 40,
        target_commit_sha="b" * 40,
        repository_full_name="acme/demo-repo",
        provider_event_id="opened",
    )

    with pytest.raises(Exception) as excinfo:
        await service.prepare_workspace(provider, event, workflow_run_id="wf-err-token")

    assert token not in str(excinfo.value)
    for recorded in writer.events:
        assert token not in recorded["metadata_json"]


@pytest.mark.asyncio
async def test_sql_audit_writer_sanitizes_failure() -> None:
    sensitive = "password=super-secret-value SQL: INSERT INTO audit_logs VALUES ($1, $2)"

    with patch(
        "protecto_prime_agent.services.repository_workspace_service.SessionLocal",
        side_effect=RuntimeError(sensitive),
    ):
        with patch("protecto_prime_agent.services.repository_workspace_service.log_contextual") as mock_log:
            writer = SqlAuditWriter()
            await writer.record(
                entity_type="repository_workspace",
                entity_id="entity-1",
                action="clone_started",
                actor="system",
                metadata_json="{}",
            )

    mock_log.assert_called_once()
    args, kwargs = mock_log.call_args
    assert args[0] == "audit_write_failed"
    assert kwargs["error_type"] == "RuntimeError"
    logged_values = " ".join(str(value) for value in kwargs.values())
    assert "super-secret-value" not in logged_values
    assert "INSERT INTO" not in logged_values


@pytest.mark.asyncio
async def test_sql_audit_writer_writes_via_session() -> None:
    session = Mock()
    session.add = Mock()
    session.commit = Mock()

    async def _commit() -> None:
        return None

    session.commit = _commit
    session_factory = Mock()

    class _AsyncSessionContext:
        async def __aenter__(self) -> Mock:
            return session

        async def __aexit__(self, *exc_info: object) -> bool:
            return False

    session_factory.return_value = _AsyncSessionContext()

    with patch("protecto_prime_agent.services.repository_workspace_service.SessionLocal", session_factory):
        writer = SqlAuditWriter()
        await writer.record(
            entity_type="repository_workspace",
            entity_id="entity-2",
            action="clone_completed",
            actor="system",
            metadata_json="{}",
        )

    session.add.assert_called_once()
    added_log = session.add.call_args[0][0]
    assert added_log.action == "clone_completed"
