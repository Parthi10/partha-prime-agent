from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from protecto_prime_agent.main import app
from protecto_prime_agent.services.webhook_service import WebhookService


def _make_result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_valid_webhook() -> None:
    payload = {
        "eventKey": "pr:created",
        "pullrequest": {
            "id": 123,
            "source": {
                "branch": {"name": "feature/test"},
                "commit": {"hash": "abc123"},
            },
            "destination": {
                "branch": {"name": "main"},
                "commit": {"hash": "def456"},
            },
        },
        "repository": {"uuid": "repo-123", "full_name": "acme/demo-repo"},
    }
    body = json.dumps(payload).encode("utf-8")

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=True)):
            service = WebhookService()
            with patch("protecto_prime_agent.services.webhook_service.SessionLocal") as session_factory:
                session = Mock()
                session.execute = AsyncMock(return_value=_make_result(None))
                session.flush = AsyncMock()
                session.commit = AsyncMock()
                session.add = Mock()
                session_factory.return_value.__aenter__.return_value = session
                result = await service.handle_webhook(body, "signature", "corr-1")

    assert result["status"] == "accepted"


@pytest.mark.asyncio
async def test_invalid_webhook_authentication() -> None:
    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        service = WebhookService()
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=False)):
            with pytest.raises(PermissionError):
                await service.handle_webhook(b"{}", "bad-signature", "corr-1")


@pytest.mark.asyncio
async def test_duplicate_webhook() -> None:
    payload = {"eventKey": "pr:created", "pullrequest": {"id": 123, "source": {"branch": {"name": "feature/test"}, "commit": {"hash": "abc123"}}, "destination": {"branch": {"name": "main"}, "commit": {"hash": "def456"}}}, "repository": {"uuid": "repo-123", "full_name": "acme/demo-repo"}}
    body = json.dumps(payload).encode("utf-8")

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=True)):
            service = WebhookService()
            session = Mock()
            session.execute = AsyncMock(return_value=_make_result(object()))
            session.flush = AsyncMock()
            session.commit = AsyncMock()
            session.add = Mock()
            with patch("protecto_prime_agent.services.webhook_service.SessionLocal") as session_factory:
                session_factory.return_value.__aenter__.return_value = session
                result = await service.handle_webhook(body, "signature", "corr-1")

    assert result["status"] == "duplicate"


@pytest.mark.asyncio
async def test_unsupported_event() -> None:
    payload = {"eventKey": "repo:push", "pullrequest": {"id": 123, "source": {"branch": {"name": "feature/test"}, "commit": {"hash": "abc123"}}, "destination": {"branch": {"name": "main"}, "commit": {"hash": "def456"}}}, "repository": {"uuid": "repo-123", "full_name": "acme/demo-repo"}}
    body = json.dumps(payload).encode("utf-8")

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        service = WebhookService()
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=True)):
            with patch("protecto_prime_agent.services.webhook_service.SessionLocal"):
                result = await service.handle_webhook(body, "signature", "corr-1")

    assert result["status"] == "ignored"


@pytest.mark.asyncio
async def test_unsupported_target_branch() -> None:
    payload = {"eventKey": "pr:created", "pullrequest": {"id": 123, "source": {"branch": {"name": "feature/test"}, "commit": {"hash": "abc123"}}, "destination": {"branch": {"name": "release"}, "commit": {"hash": "def456"}}}, "repository": {"uuid": "repo-123", "full_name": "acme/demo-repo"}}
    body = json.dumps(payload).encode("utf-8")

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        service = WebhookService()
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=True)):
            with patch("protecto_prime_agent.services.webhook_service.SessionLocal"):
                result = await service.handle_webhook(body, "signature", "corr-1")

    assert result["status"] == "ignored"


@pytest.mark.asyncio
async def test_missing_required_fields() -> None:
    payload = {"eventKey": "pr:created", "pullrequest": {"source": {"branch": {"name": "feature/test"}, "commit": {"hash": "abc123"}}, "destination": {"branch": {"name": "main"}, "commit": {"hash": "def456"}}}, "repository": {"uuid": "repo-123", "full_name": "acme/demo-repo"}}
    body = json.dumps(payload).encode("utf-8")

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        service = WebhookService()
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=True)):
            with patch("protecto_prime_agent.services.webhook_service.SessionLocal"):
                result = await service.handle_webhook(body, "signature", "corr-1")

    assert result["status"] == "ignored"


@pytest.mark.asyncio
async def test_endpoint_accepts_valid_webhook() -> None:
    payload = {
        "eventKey": "pr:created",
        "pullrequest": {
            "id": 123,
            "source": {
                "branch": {"name": "feature/test"},
                "commit": {"hash": "abc123"},
            },
            "destination": {
                "branch": {"name": "main"},
                "commit": {"hash": "def456"},
            },
        },
        "repository": {"uuid": "repo-123", "full_name": "acme/demo-repo"},
    }
    body = json.dumps(payload).encode("utf-8")

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        with patch("protecto_prime_agent.services.webhook_service.BitbucketProvider.validate_webhook", new=AsyncMock(return_value=True)):
            with patch("protecto_prime_agent.services.webhook_service.SessionLocal") as session_factory:
                session = Mock()
                session.execute = AsyncMock(return_value=_make_result(None))
                session.flush = AsyncMock()
                session.commit = AsyncMock()
                session.add = Mock()
                session_factory.return_value.__aenter__.return_value = session
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/v1/webhooks/bitbucket",
                        content=body,
                        headers={"X-Correlation-ID": "corr-2", "X-Hub-Signature": "signature"},
                    )

    assert response.status_code == 200
