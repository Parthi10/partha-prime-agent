from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from protecto_prime_agent.enums import ExecutionStatus, ScannerExecutionStatus
from protecto_prime_agent.integrations.scm import CloneInfo, PullRequestEvent, SCMProvider
from protecto_prime_agent.models import PullRequest, WorkflowRun
from protecto_prime_agent.scanners.interface import (
    AggregatedScanResult,
    NormalizedFinding,
    ScanRequest,
    ScanResult,
)
from protecto_prime_agent.services.repository_workspace_service import AuditWriter
from protecto_prime_agent.services.scan_orchestration_service import ScanOrchestrationService


class DummyProvider(SCMProvider):
    async def validate_webhook(self, body: bytes, signature: str | None) -> bool:
        return True

    async def parse_pull_request_event(self, payload: dict[str, object]) -> PullRequestEvent | None:
        raise NotImplementedError

    async def get_clone_info(self, event: PullRequestEvent) -> CloneInfo | None:
        return CloneInfo(clone_url="https://example.invalid/repo.git", repository_name="demo")


class RecordingAuditWriter(AuditWriter):
    """Test double: records events in memory instead of touching the database."""

    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    async def record(self, *, entity_type: str, entity_id: str, action: str, actor: str, metadata_json: str) -> None:
        self.events.append({"entity_type": entity_type, "entity_id": entity_id, "action": action})


class FakeWorkspaceService:
    """Stub replacing RepositoryWorkspaceService so no real git commands run."""

    def __init__(self, workspace_path: Path, fail: bool = False) -> None:
        self.workspace_path = workspace_path
        self.fail = fail
        self.cleaned_up: list[Path] = []

    async def prepare_workspace(
        self, provider: SCMProvider, event: PullRequestEvent, workflow_run_id: str
    ) -> dict[str, str]:
        if self.fail:
            raise ValueError("clone_failed")
        return {
            "status": "READY",
            "workspace_path": str(self.workspace_path),
            "diff_path": str(self.workspace_path / "diff.patch"),
        }

    async def mark_processing_complete(self, workspace_path: Path) -> bool:
        self.cleaned_up.append(workspace_path)
        return True


class FakeScannerRunner:
    """Stub replacing ScannerRunner so no real scanner binaries run."""

    def __init__(self, result: AggregatedScanResult | None = None, fail: bool = False) -> None:
        self.result = result
        self.fail = fail
        self.received_request: ScanRequest | None = None

    async def run_scan(self, request: ScanRequest) -> AggregatedScanResult:
        self.received_request = request
        if self.fail:
            raise RuntimeError("scan_crashed")
        assert self.result is not None
        return self.result


class FakeSession:
    """Stub replacing an AsyncSession so no real database connection is opened."""

    def __init__(self, workflow_run: WorkflowRun, pull_request: PullRequest) -> None:
        self._workflow_run = workflow_run
        self._pull_request = pull_request
        self.added: list[Any] = []
        self.commits = 0

    async def get(self, model: type, obj_id: uuid.UUID) -> Any | None:
        if model is WorkflowRun:
            return self._workflow_run
        if model is PullRequest:
            return self._pull_request
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()  # simulate the id SQLAlchemy assigns on a real flush

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def _event() -> PullRequestEvent:
    return PullRequestEvent(
        event_type="pull_request",
        repository_id="repo-123",
        pull_request_id="pr-456",
        source_branch="feature/test",
        target_branch="main",
        source_commit_sha="a" * 40,
        target_commit_sha="b" * 40,
        repository_full_name="acme/demo-repo",
    )


def _workflow_run_and_pull_request(
    workflow_run_id: uuid.UUID, pull_request_id: uuid.UUID, repository_id: uuid.UUID, correlation_id: str
) -> tuple[WorkflowRun, PullRequest]:
    workflow_run = WorkflowRun(
        id=workflow_run_id,
        pull_request_id=pull_request_id,
        workflow_type="code_review",
        execution_status=ExecutionStatus.QUEUED.value,
        correlation_id=correlation_id,
    )
    pull_request = PullRequest(
        id=pull_request_id,
        repository_id=repository_id,
        provider_pr_id="pr-456",
        source_branch="feature/test",
        target_branch="main",
        source_commit_sha="a" * 40,
        target_commit_sha="b" * 40,
    )
    return workflow_run, pull_request


def _aggregated_result(workflow_run_id: str) -> AggregatedScanResult:
    now = datetime.now(timezone.utc)
    finding = NormalizedFinding(
        scanner_name="ruff",
        rule_id="F401",
        severity="low",
        category="quality",
        confidence="medium",
        message="unused import",
        file_path="app.py",
        line_number=1,
        column_number=1,
        fingerprint="fp-1",
        commit_sha="a" * 40,
        raw_details_json="{}",
    )
    scan_result = ScanResult(
        scanner_name="ruff",
        status=ScannerExecutionStatus.COMPLETED,
        findings=[finding],
        exit_code=1,
        started_at=now,
        completed_at=now,
        duration_seconds=0.1,
    )
    return AggregatedScanResult(
        workflow_run_id=workflow_run_id,
        commit_sha="a" * 40,
        scan_results=[scan_result],
        started_at=now,
        completed_at=now,
    )


@pytest.mark.asyncio
async def test_successful_orchestration_persists_results_and_marks_succeeded(tmp_path: Path) -> None:
    workflow_run_id, pull_request_id, repository_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    workflow_run, pull_request = _workflow_run_and_pull_request(
        workflow_run_id, pull_request_id, repository_id, "corr-1"
    )
    session = FakeSession(workflow_run, pull_request)

    workspace_service = FakeWorkspaceService(tmp_path)
    scanner_runner = FakeScannerRunner(result=_aggregated_result(str(workflow_run_id)))
    audit_writer = RecordingAuditWriter()
    service = ScanOrchestrationService(
        workspace_service=workspace_service, scanner_runner=scanner_runner, audit_writer=audit_writer
    )

    with patch("protecto_prime_agent.services.scan_orchestration_service.SessionLocal", return_value=session):
        await service.run(
            provider=DummyProvider(),
            event=_event(),
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            workflow_run_id=workflow_run_id,
            correlation_id="corr-1",
        )

    assert workflow_run.execution_status == ExecutionStatus.SUCCEEDED.value
    assert pull_request.execution_status == ExecutionStatus.SUCCEEDED.value
    assert workflow_run.started_at is not None
    assert workflow_run.completed_at is not None

    scan_runs = [obj for obj in session.added if type(obj).__name__ == "ScanRun"]
    findings = [obj for obj in session.added if type(obj).__name__ == "Finding"]
    assert len(scan_runs) == 1
    assert scan_runs[0].scanner_name == "ruff"
    assert scan_runs[0].execution_status == ScannerExecutionStatus.COMPLETED.value
    assert len(findings) == 1
    assert findings[0].rule_id == "F401"
    assert findings[0].scan_run_id == scan_runs[0].id
    assert findings[0].workflow_run_id == workflow_run_id

    assert workspace_service.cleaned_up == [tmp_path]
    assert scanner_runner.received_request is not None
    assert scanner_runner.received_request.commit_sha == "a" * 40

    actions = [event["action"] for event in audit_writer.events]
    assert actions == ["orchestration_started", "orchestration_completed"]


@pytest.mark.asyncio
async def test_workspace_preparation_failure_marks_failed_and_skips_scanning(tmp_path: Path) -> None:
    workflow_run_id, pull_request_id, repository_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    workflow_run, pull_request = _workflow_run_and_pull_request(
        workflow_run_id, pull_request_id, repository_id, "corr-2"
    )
    session = FakeSession(workflow_run, pull_request)

    workspace_service = FakeWorkspaceService(tmp_path, fail=True)
    scanner_runner = FakeScannerRunner()
    audit_writer = RecordingAuditWriter()
    service = ScanOrchestrationService(
        workspace_service=workspace_service, scanner_runner=scanner_runner, audit_writer=audit_writer
    )

    with patch("protecto_prime_agent.services.scan_orchestration_service.SessionLocal", return_value=session):
        await service.run(
            provider=DummyProvider(),
            event=_event(),
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            workflow_run_id=workflow_run_id,
            correlation_id="corr-2",
        )

    assert workflow_run.execution_status == ExecutionStatus.FAILED.value
    assert pull_request.execution_status == ExecutionStatus.FAILED.value
    assert workflow_run.error_message == "clone_failed"
    assert scanner_runner.received_request is None
    assert not any(type(obj).__name__ == "ScanRun" for obj in session.added)

    actions = [event["action"] for event in audit_writer.events]
    assert actions == ["orchestration_started", "orchestration_failed"]


@pytest.mark.asyncio
async def test_scanner_crash_marks_failed_but_still_cleans_up_workspace(tmp_path: Path) -> None:
    workflow_run_id, pull_request_id, repository_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    workflow_run, pull_request = _workflow_run_and_pull_request(
        workflow_run_id, pull_request_id, repository_id, "corr-3"
    )
    session = FakeSession(workflow_run, pull_request)

    workspace_service = FakeWorkspaceService(tmp_path)
    scanner_runner = FakeScannerRunner(fail=True)
    audit_writer = RecordingAuditWriter()
    service = ScanOrchestrationService(
        workspace_service=workspace_service, scanner_runner=scanner_runner, audit_writer=audit_writer
    )

    with patch("protecto_prime_agent.services.scan_orchestration_service.SessionLocal", return_value=session):
        await service.run(
            provider=DummyProvider(),
            event=_event(),
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            workflow_run_id=workflow_run_id,
            correlation_id="corr-3",
        )

    assert workflow_run.execution_status == ExecutionStatus.FAILED.value
    assert workflow_run.error_message == "scan_crashed"
    # Cleanup must still happen even though the scan crashed.
    assert workspace_service.cleaned_up == [tmp_path]


@pytest.mark.asyncio
async def test_partial_scanner_failure_still_marks_orchestration_succeeded(tmp_path: Path) -> None:
    workflow_run_id, pull_request_id, repository_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    workflow_run, pull_request = _workflow_run_and_pull_request(
        workflow_run_id, pull_request_id, repository_id, "corr-4"
    )
    session = FakeSession(workflow_run, pull_request)

    now = datetime.now(timezone.utc)
    failed_scan = ScanResult(
        scanner_name="bandit",
        status=ScannerExecutionStatus.FAILED,
        findings=[],
        started_at=now,
        completed_at=now,
        error_message="tool_not_available",
    )
    aggregated = AggregatedScanResult(
        workflow_run_id=str(workflow_run_id),
        commit_sha="a" * 40,
        scan_results=[failed_scan],
        started_at=now,
        completed_at=now,
    )

    workspace_service = FakeWorkspaceService(tmp_path)
    scanner_runner = FakeScannerRunner(result=aggregated)
    audit_writer = RecordingAuditWriter()
    service = ScanOrchestrationService(
        workspace_service=workspace_service, scanner_runner=scanner_runner, audit_writer=audit_writer
    )

    with patch("protecto_prime_agent.services.scan_orchestration_service.SessionLocal", return_value=session):
        await service.run(
            provider=DummyProvider(),
            event=_event(),
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            workflow_run_id=workflow_run_id,
            correlation_id="corr-4",
        )

    # A per-scanner failure is recorded on its own ScanRun row, but does not fail the
    # orchestration itself -- merge/policy decisions are a later milestone's job.
    assert workflow_run.execution_status == ExecutionStatus.SUCCEEDED.value
    scan_runs = [obj for obj in session.added if type(obj).__name__ == "ScanRun"]
    assert len(scan_runs) == 1
    assert scan_runs[0].execution_status == ScannerExecutionStatus.FAILED.value
    assert not any(type(obj).__name__ == "Finding" for obj in session.added)


@pytest.mark.asyncio
async def test_unhandled_exception_never_propagates(tmp_path: Path) -> None:
    """A bug anywhere in orchestration must never escape run() -- it executes fire-and-forget."""
    workflow_run_id, pull_request_id, repository_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    class ExplodingWorkspaceService:
        async def prepare_workspace(self, *args: object, **kwargs: object) -> dict[str, str]:
            raise RuntimeError("boom")

        async def mark_processing_complete(self, workspace_path: Path) -> bool:
            return True

    service = ScanOrchestrationService(
        workspace_service=ExplodingWorkspaceService(),  # type: ignore[arg-type]
        scanner_runner=FakeScannerRunner(),
        audit_writer=RecordingAuditWriter(),
    )

    with patch(
        "protecto_prime_agent.services.scan_orchestration_service.SessionLocal",
        side_effect=RuntimeError("db_unavailable"),
    ):
        await service.run(
            provider=DummyProvider(),
            event=_event(),
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            workflow_run_id=workflow_run_id,
            correlation_id="corr-5",
        )
