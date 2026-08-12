from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import SessionLocal
from ..enums import ExecutionStatus, MergeDecision
from ..integrations.bitbucket import BitbucketProvider
from ..integrations.scm import PullRequestEvent, SCMProvider
from ..logging import log_contextual
from ..models import AuditLog, PullRequest, Repository, WebhookEvent, WorkflowRun
from .scan_orchestration_service import ScanOrchestrationService

settings = get_settings()


class WebhookService:
    def __init__(
        self,
        provider: SCMProvider | None = None,
        session: AsyncSession | None = None,
        orchestrator: ScanOrchestrationService | None = None,
    ) -> None:
        self.session = session
        self.provider = provider or self._default_provider()
        self.orchestrator = orchestrator

    def _default_provider(self) -> SCMProvider:
        from ..integrations.scm import SCMProviderConfig, SCMProviderType

        return BitbucketProvider(
            SCMProviderConfig(
                provider_type=SCMProviderType.BITBUCKET,
                webhook_secret=settings.bitbucket_webhook_secret,
            )
        )

    async def handle_webhook(
        self,
        body: bytes,
        signature: str | None,
        correlation_id: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> dict[str, Any]:
        if not body:
            raise ValueError("empty_body")

        if not await self.provider.validate_webhook(body, signature):
            raise PermissionError("invalid_signature")

        payload = json.loads(body.decode("utf-8"))
        parsed = await self.provider.parse_pull_request_event(payload)
        if parsed is None:
            return {"status": "ignored", "message": "unsupported_event"}

        payload_hash = hashlib.sha256(body).hexdigest()
        event_id_for_lookup = parsed.provider_event_id or payload_hash

        async with SessionLocal() as session:
            existing_event = await self._get_existing_webhook_event(session, event_id_for_lookup, payload_hash)
            if existing_event is not None:
                return {"status": "duplicate", "message": "duplicate_webhook"}

            repository = await self._get_or_create_repository(session, parsed)
            pull_request = await self._get_or_create_pull_request(session, repository, parsed)
            await self._create_webhook_event(session, repository, parsed, payload_hash)
            workflow_run = await self._create_workflow_run(session, pull_request, correlation_id)
            await self._create_audit_log(session, pull_request, workflow_run, correlation_id)
            await session.commit()

            if background_tasks is not None:
                background_tasks.add_task(
                    self._trigger_orchestration,
                    event=parsed,
                    repository_id=repository.id,
                    pull_request_id=pull_request.id,
                    workflow_run_id=workflow_run.id,
                    correlation_id=correlation_id,
                )

        return {"status": "accepted", "message": "workflow_queued"}

    async def _trigger_orchestration(
        self,
        *,
        event: PullRequestEvent,
        repository_id: uuid.UUID,
        pull_request_id: uuid.UUID,
        workflow_run_id: uuid.UUID,
        correlation_id: str,
    ) -> None:
        orchestrator = self.orchestrator or ScanOrchestrationService()
        try:
            await orchestrator.run(
                provider=self.provider,
                event=event,
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                workflow_run_id=workflow_run_id,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # pragma: no cover - defensive; orchestrator.run already guards internally
            log_contextual(
                "orchestration_trigger_failed", workflow_run_id=str(workflow_run_id), error_type=type(exc).__name__
            )

    async def _get_existing_webhook_event(self, session: AsyncSession, provider_event_id: str, payload_hash: str) -> WebhookEvent | None:
        stmt = select(WebhookEvent).where(
            (WebhookEvent.provider_event_id == provider_event_id)
            | (WebhookEvent.payload_hash == payload_hash)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create_repository(self, session: AsyncSession, parsed: PullRequestEvent) -> Repository:
        repository_id = parsed.repository_id
        stmt = select(Repository).where(Repository.provider_repo_id == repository_id)
        result = await session.execute(stmt)
        repository = result.scalar_one_or_none()
        if repository is not None:
            return repository

        repository = Repository(
            provider="scm",
            provider_repo_id=repository_id,
            name=repository_id,
            default_branch="main",
            is_active=True,
        )
        session.add(repository)
        await session.flush()
        return repository

    async def _get_or_create_pull_request(self, session: AsyncSession, repository: Repository, parsed: PullRequestEvent) -> PullRequest:
        pull_request_id = parsed.pull_request_id
        stmt = select(PullRequest).where(PullRequest.provider_pr_id == pull_request_id)
        result = await session.execute(stmt)
        pull_request = result.scalar_one_or_none()
        if pull_request is not None:
            pull_request.source_branch = parsed.source_branch
            pull_request.target_branch = parsed.target_branch
            pull_request.source_commit_sha = parsed.source_commit_sha
            pull_request.target_commit_sha = parsed.target_commit_sha
            pull_request.execution_status = ExecutionStatus.PENDING.value
            pull_request.merge_decision = MergeDecision.PENDING.value
            pull_request.updated_at = datetime.now(timezone.utc)
            await session.flush()
            return pull_request

        pull_request = PullRequest(
            repository_id=repository.id,
            provider_pr_id=pull_request_id,
            source_branch=parsed.source_branch,
            target_branch=parsed.target_branch,
            source_commit_sha=parsed.source_commit_sha,
            target_commit_sha=parsed.target_commit_sha,
            execution_status=ExecutionStatus.PENDING.value,
            merge_decision=MergeDecision.PENDING.value,
        )
        session.add(pull_request)
        await session.flush()
        return pull_request

    async def _create_webhook_event(self, session: AsyncSession, repository: Repository, parsed: PullRequestEvent, payload_hash: str) -> WebhookEvent:
        event_type = parsed.event_type
        webhook_event = WebhookEvent(
            repository_id=repository.id,
            provider_event_id=parsed.provider_event_id or event_type,
            event_type=event_type,
            payload_hash=payload_hash,
            processed=True,
            payload_excerpt="webhook received",
            processed_at=datetime.now(timezone.utc),
        )
        session.add(webhook_event)
        await session.flush()
        return webhook_event

    async def _create_workflow_run(self, session: AsyncSession, pull_request: PullRequest, correlation_id: str) -> WorkflowRun:
        workflow_run = WorkflowRun(
            pull_request_id=pull_request.id,
            workflow_type="code_review",
            execution_status=ExecutionStatus.QUEUED.value,
            correlation_id=correlation_id,
            trigger_source="webhook",
        )
        session.add(workflow_run)
        await session.flush()
        return workflow_run

    async def _create_audit_log(self, session: AsyncSession, pull_request: PullRequest, workflow_run: WorkflowRun, correlation_id: str) -> AuditLog:
        audit_log = AuditLog(
            entity_type="pull_request",
            entity_id=str(pull_request.id),
            action="webhook_ingested",
            actor="system",
            metadata_json=json.dumps({"correlation_id": correlation_id, "workflow_run_id": str(workflow_run.id)}),
        )
        session.add(audit_log)
        return audit_log
