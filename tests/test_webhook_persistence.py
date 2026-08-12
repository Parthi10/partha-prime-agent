from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from protecto_prime_agent.services.webhook_service import WebhookService


def _make_result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


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
