from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..config import get_settings
from ..database import SessionLocal
from ..enums import ExecutionStatus
from ..integrations.scm import PullRequestEvent, SCMProvider
from ..logging import log_contextual
from ..models import Finding, PullRequest, ScanRun, WorkflowRun
from ..scanners.config import ScannerRuntimeConfig
from ..scanners.execution import LocalProcessExecutionBackend
from ..scanners.interface import AggregatedScanResult, ScanRequest
from ..scanners.registry import build_default_registry
from ..scanners.runner import ScannerRunner
from .repository_workspace_service import (
    AuditWriter,
    RepositoryWorkspaceService,
    SqlAuditWriter,
    redact_secrets,
)


class WorkspacePreparer(Protocol):
    """Structural interface satisfied by RepositoryWorkspaceService (and test doubles)."""

    async def prepare_workspace(
        self, provider: SCMProvider, event: PullRequestEvent, workflow_run_id: str
    ) -> dict[str, Any]: ...

    async def mark_processing_complete(self, workspace_path: Path) -> bool: ...


class ScanExecutor(Protocol):
    """Structural interface satisfied by ScannerRunner (and test doubles)."""

    async def run_scan(self, request: ScanRequest) -> AggregatedScanResult: ...


class ScanOrchestrationService:
    """Wires a webhook-triggered workflow run through workspace preparation and scanning.

    Calls `RepositoryWorkspaceService.prepare_workspace` (Milestone 3) to check out the
    pull request's exact source commit, then `ScannerRunner.run_scan` (Milestone 4)
    against that workspace, and persists the resulting findings to `ScanRun`/`Finding`.
    It performs no baseline comparison, merge policy decision, status publishing, or
    notification -- those remain later-milestone work. This service only ever updates
    `execution_status` and completion timestamps on `WorkflowRun`/`PullRequest`; it never
    sets `merge_decision` or `policy_blocking` beyond their existing defaults.
    """

    def __init__(
        self,
        workspace_service: WorkspacePreparer | None = None,
        scanner_runner: ScanExecutor | None = None,
        audit_writer: AuditWriter | None = None,
    ) -> None:
        self.workspace_service: WorkspacePreparer = workspace_service or RepositoryWorkspaceService()
        self.scanner_runner: ScanExecutor = scanner_runner or self._default_scanner_runner()
        self.audit_writer = audit_writer or SqlAuditWriter()

    def _default_scanner_runner(self) -> ScannerRunner:
        settings = get_settings()
        return ScannerRunner(
            registry=build_default_registry(),
            config=ScannerRuntimeConfig.from_settings(settings),
            execution_backend=LocalProcessExecutionBackend(),
        )

    async def run(
        self,
        *,
        provider: SCMProvider,
        event: PullRequestEvent,
        repository_id: uuid.UUID,
        pull_request_id: uuid.UUID,
        workflow_run_id: uuid.UUID,
        correlation_id: str,
    ) -> None:
        entity_id = f"{repository_id}:{pull_request_id}:{workflow_run_id}"
        try:
            await self._transition(
                workflow_run_id,
                pull_request_id,
                ExecutionStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
            )
            await self._audit("orchestration_started", entity_id, {"correlation_id": correlation_id})

            try:
                workspace_result = await self.workspace_service.prepare_workspace(
                    provider, event, str(workflow_run_id)
                )
            except Exception as exc:
                await self._fail(workflow_run_id, pull_request_id, entity_id, "workspace_preparation_failed", exc)
                return

            workspace_path = Path(workspace_result["workspace_path"])
            scan_request = ScanRequest(
                workspace_path=workspace_path,
                commit_sha=event.source_commit_sha,
                workflow_run_id=str(workflow_run_id),
                repository_id=str(repository_id),
            )

            try:
                aggregated = await self.scanner_runner.run_scan(scan_request)
            except Exception as exc:
                await self._fail(workflow_run_id, pull_request_id, entity_id, "scan_execution_failed", exc)
                await self.workspace_service.mark_processing_complete(workspace_path)
                return

            await self._persist_results(workflow_run_id, aggregated)
            await self.workspace_service.mark_processing_complete(workspace_path)

            await self._transition(
                workflow_run_id,
                pull_request_id,
                ExecutionStatus.SUCCEEDED,
                completed_at=datetime.now(timezone.utc),
            )
            await self._audit(
                "orchestration_completed",
                entity_id,
                {
                    "finding_count": len(aggregated.findings),
                    "scanner_count": len(aggregated.scan_results),
                    "has_scanner_failures": aggregated.has_failures,
                },
            )
        except Exception as exc:  # pragma: no cover - last-resort guard for a fire-and-forget background task
            log_contextual("orchestration_unhandled_error", entity_id=entity_id, error_type=type(exc).__name__)

    async def _fail(
        self,
        workflow_run_id: uuid.UUID,
        pull_request_id: uuid.UUID,
        entity_id: str,
        reason: str,
        exc: Exception,
    ) -> None:
        message = redact_secrets(str(exc))[:2000]
        await self._transition(
            workflow_run_id,
            pull_request_id,
            ExecutionStatus.FAILED,
            completed_at=datetime.now(timezone.utc),
            error_message=message,
        )
        await self._audit("orchestration_failed", entity_id, {"reason": reason, "error": message})

    async def _transition(
        self,
        workflow_run_id: uuid.UUID,
        pull_request_id: uuid.UUID,
        status: ExecutionStatus,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        async with SessionLocal() as session:
            now = datetime.now(timezone.utc)
            workflow_run = await session.get(WorkflowRun, workflow_run_id)
            if workflow_run is not None:
                workflow_run.execution_status = status.value
                workflow_run.updated_at = now
                if started_at is not None:
                    workflow_run.started_at = started_at
                if completed_at is not None:
                    workflow_run.completed_at = completed_at
                if error_message is not None:
                    workflow_run.error_message = error_message

            pull_request = await session.get(PullRequest, pull_request_id)
            if pull_request is not None:
                pull_request.execution_status = status.value
                pull_request.updated_at = now

            await session.commit()

    async def _persist_results(self, workflow_run_id: uuid.UUID, aggregated: AggregatedScanResult) -> None:
        async with SessionLocal() as session:
            for scan_result in aggregated.scan_results:
                scan_run = ScanRun(
                    workflow_run_id=workflow_run_id,
                    scanner_name=scan_result.scanner_name,
                    commit_sha=aggregated.commit_sha,
                    execution_status=scan_result.status.value,
                    exit_code=scan_result.exit_code,
                    log_reference=scan_result.error_message,
                    started_at=scan_result.started_at,
                    completed_at=scan_result.completed_at,
                )
                session.add(scan_run)
                await session.flush()

                for finding in scan_result.findings:
                    session.add(
                        Finding(
                            workflow_run_id=workflow_run_id,
                            scan_run_id=scan_run.id,
                            scanner_name=finding.scanner_name,
                            rule_id=finding.rule_id,
                            severity=finding.severity,
                            category=finding.category,
                            confidence=finding.confidence,
                            message=finding.message,
                            file_path=finding.file_path,
                            line_number=finding.line_number,
                            column_number=finding.column_number,
                            fingerprint=finding.fingerprint,
                        )
                    )

            await session.commit()

    async def _audit(self, action: str, entity_id: str, extra: dict[str, object]) -> None:
        metadata_json = redact_secrets(json.dumps(extra, default=str))
        try:
            await self.audit_writer.record(
                entity_type="scan_orchestration",
                entity_id=entity_id,
                action=action,
                actor="system",
                metadata_json=metadata_json,
            )
        except Exception as exc:  # pragma: no cover - defensive; injected writers should not raise
            log_contextual(
                "audit_write_failed", action=action, entity_type="scan_orchestration", error_type=type(exc).__name__
            )
