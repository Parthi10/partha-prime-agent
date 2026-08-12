from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import BackgroundTasks

from protecto_prime_agent.services.webhook_service import WebhookService


def _make_result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


def _bitbucket_payload() -> bytes:
    payload = {
        "eventKey": "pr:created",
        "pullrequest": {
            "id": 777,
            "source": {
                "branch": {"name": "feature/orchestration"},
                "commit": {"hash": "source-hash-2"},
            },
            "destination": {
                "branch": {"name": "develop"},
                "commit": {"hash": "target-hash-2"},
            },
        },
        "repository": {"uuid": "repo-777", "full_name": "acme/demo-repo"},
    }
    return json.dumps(payload).encode("utf-8")


@pytest.mark.asyncio
async def test_persists_repository_pull_request_and_workflow_run() -> None:
    payload = {
        "eventKey": "pr:created",
        "pullrequest": {
            "id": 555,
            "source": {
                "branch": {"name": "feature/integration"},
                "commit": {"hash": "source-hash"},
            },
            "destination": {
                "branch": {"name": "develop"},
                "commit": {"hash": "target-hash"},
            },
        },
        "repository": {"uuid": "repo-999", "full_name": "acme/demo-repo"},
    }
    body = json.dumps(payload).encode("utf-8")

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=True)):
            service = WebhookService()
            session = Mock()
            session.execute = AsyncMock(side_effect=[
                _make_result(None),
                _make_result(None),
                _make_result(None),
            ])
            session.flush = AsyncMock()
            session.commit = AsyncMock()
            session.add = Mock()
            with patch("protecto_prime_agent.services.webhook_service.SessionLocal") as session_factory:
                session_factory.return_value.__aenter__.return_value = session
                result = await service.handle_webhook(body, "signature", "corr-3")

    assert result["status"] == "accepted"


@pytest.mark.asyncio
async def test_schedules_orchestration_when_background_tasks_provided() -> None:
    body = _bitbucket_payload()

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=True)):
            orchestrator = Mock()
            orchestrator.run = AsyncMock()
            service = WebhookService(orchestrator=orchestrator)
            session = Mock()
            session.execute = AsyncMock(side_effect=[_make_result(None), _make_result(None), _make_result(None)])
            session.flush = AsyncMock()
            session.commit = AsyncMock()
            session.add = Mock()
            with patch("protecto_prime_agent.services.webhook_service.SessionLocal") as session_factory:
                session_factory.return_value.__aenter__.return_value = session
                background_tasks = BackgroundTasks()
                result = await service.handle_webhook(body, "signature", "corr-orch", background_tasks=background_tasks)
                await background_tasks()

    assert result["status"] == "accepted"
    orchestrator.run.assert_awaited_once()
    assert orchestrator.run.call_args.kwargs["correlation_id"] == "corr-orch"


@pytest.mark.asyncio
async def test_does_not_schedule_orchestration_without_background_tasks() -> None:
    body = _bitbucket_payload()

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=True)):
            orchestrator = Mock()
            orchestrator.run = AsyncMock()
            service = WebhookService(orchestrator=orchestrator)
            session = Mock()
            session.execute = AsyncMock(side_effect=[_make_result(None), _make_result(None), _make_result(None)])
            session.flush = AsyncMock()
            session.commit = AsyncMock()
            session.add = Mock()
            with patch("protecto_prime_agent.services.webhook_service.SessionLocal") as session_factory:
                session_factory.return_value.__aenter__.return_value = session
                result = await service.handle_webhook(body, "signature", "corr-no-orch")

    assert result["status"] == "accepted"
    orchestrator.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_orchestration_trigger_failure_is_swallowed() -> None:
    """A crash scheduling/running orchestration must never surface as a webhook failure."""
    body = _bitbucket_payload()

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=True)):
            orchestrator = Mock()
            orchestrator.run = AsyncMock(side_effect=RuntimeError("boom"))
            service = WebhookService(orchestrator=orchestrator)
            session = Mock()
            session.execute = AsyncMock(side_effect=[_make_result(None), _make_result(None), _make_result(None)])
            session.flush = AsyncMock()
            session.commit = AsyncMock()
            session.add = Mock()
            with patch("protecto_prime_agent.services.webhook_service.SessionLocal") as session_factory:
                session_factory.return_value.__aenter__.return_value = session
                background_tasks = BackgroundTasks()
                result = await service.handle_webhook(body, "signature", "corr-fail", background_tasks=background_tasks)
                await background_tasks()

    assert result["status"] == "accepted"
