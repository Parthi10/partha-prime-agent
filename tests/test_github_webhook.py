from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from protecto_prime_agent.integrations.bitbucket import BitbucketProvider
from protecto_prime_agent.integrations.github import GitHubProvider
from protecto_prime_agent.integrations.scm import SCMProviderConfig, SCMProviderType
from protecto_prime_agent.services.webhook_service import WebhookService


def _make_result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


def _sign_body(body: bytes, secret: str) -> str:
    return f"sha1={hmac.new(secret.encode('utf-8'), body, hashlib.sha1).hexdigest()}"


def _github_payload() -> dict[str, object]:
    return {
        "action": "opened",
        "pull_request": {
            "id": 456,
            "head": {"ref": "feature/github", "sha": "abc123"},
            "base": {"ref": "main", "sha": "def456"},
        },
        "repository": {"id": 789, "name": "demo-repo"},
    }


@pytest.mark.asyncio
async def test_github_valid_webhook() -> None:
    body = json.dumps(_github_payload()).encode("utf-8")

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        settings_mock.return_value.github_webhook_secret = "github-secret"
        service = WebhookService(provider=GitHubProvider(SCMProviderConfig(provider_type=SCMProviderType.GITHUB, webhook_secret="github-secret")))
        with patch("protecto_prime_agent.services.webhook_service.SessionLocal") as session_factory:
            session = Mock()
            session.execute = AsyncMock(return_value=_make_result(None))
            session.flush = AsyncMock()
            session.commit = AsyncMock()
            session.add = Mock()
            session_factory.return_value.__aenter__.return_value = session
            result = await service.handle_webhook(body, _sign_body(body, "github-secret"), "corr-github")

    assert result["status"] == "accepted"


@pytest.mark.asyncio
async def test_github_invalid_signature() -> None:
    body = json.dumps(_github_payload()).encode("utf-8")
    service = WebhookService(provider=GitHubProvider(SCMProviderConfig(provider_type=SCMProviderType.GITHUB, webhook_secret="github-secret")))

    with patch.object(service.provider, "validate_webhook", AsyncMock(return_value=False)):
        with pytest.raises(PermissionError):
            await service.handle_webhook(body, _sign_body(body, "github-secret"), "corr-github")


@pytest.mark.asyncio
async def test_github_duplicate_delivery() -> None:
    body = json.dumps(_github_payload()).encode("utf-8")

    with patch("protecto_prime_agent.services.webhook_service.get_settings") as settings_mock:
        settings_mock.return_value.bitbucket_webhook_secret = "secret"
        settings_mock.return_value.github_webhook_secret = "github-secret"
        service = WebhookService(provider=GitHubProvider(SCMProviderConfig(provider_type=SCMProviderType.GITHUB, webhook_secret="github-secret")))
        session = Mock()
        session.execute = AsyncMock(return_value=_make_result(object()))
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.add = Mock()
        with patch("protecto_prime_agent.services.webhook_service.SessionLocal") as session_factory:
            session_factory.return_value.__aenter__.return_value = session
            result = await service.handle_webhook(body, _sign_body(body, "github-secret"), "corr-github")

    assert result["status"] == "duplicate"


@pytest.mark.asyncio
async def test_github_unsupported_event() -> None:
    payload = _github_payload()
    payload["action"] = "closed"
    body = json.dumps(payload).encode("utf-8")

    service = WebhookService(provider=GitHubProvider(SCMProviderConfig(provider_type=SCMProviderType.GITHUB, webhook_secret="github-secret")))
    result = await service.handle_webhook(body, _sign_body(body, "github-secret"), "corr-github")

    assert result["status"] == "ignored"


@pytest.mark.asyncio
async def test_github_unsupported_target_branch() -> None:
    payload = _github_payload()
    payload["pull_request"] = {
        "id": 456,
        "head": {"ref": "feature/github", "sha": "abc123"},
        "base": {"ref": "release", "sha": "def456"},
    }
    body = json.dumps(payload).encode("utf-8")

    service = WebhookService(provider=GitHubProvider(SCMProviderConfig(provider_type=SCMProviderType.GITHUB, webhook_secret="github-secret")))
    result = await service.handle_webhook(body, _sign_body(body, "github-secret"), "corr-github")

    assert result["status"] == "ignored"


@pytest.mark.asyncio
async def test_github_missing_required_fields() -> None:
    payload = _github_payload()
    payload["pull_request"] = {"id": 456, "head": {"ref": "feature/github", "sha": "abc123"}}
    body = json.dumps(payload).encode("utf-8")

    service = WebhookService(provider=GitHubProvider(SCMProviderConfig(provider_type=SCMProviderType.GITHUB, webhook_secret="github-secret")))
    result = await service.handle_webhook(body, _sign_body(body, "github-secret"), "corr-github")

    assert result["status"] == "ignored"


@pytest.mark.asyncio
async def test_provider_contract_normalizes_to_identical_pull_request_event() -> None:
    bitbucket_payload = {
        "eventKey": "pr:created",
        "pullrequest": {
            "id": 123,
            "source": {"branch": {"name": "feature/test"}, "commit": {"hash": "abc123"}},
            "destination": {"branch": {"name": "main"}, "commit": {"hash": "def456"}},
        },
        "repository": {"uuid": "repo-123"},
    }
    github_payload = {
        "action": "opened",
        "pull_request": {
            "id": 123,
            "head": {"ref": "feature/test", "sha": "abc123"},
            "base": {"ref": "main", "sha": "def456"},
        },
        "repository": {"id": 456, "name": "demo"},
    }

    bitbucket_provider = BitbucketProvider(SCMProviderConfig(provider_type=SCMProviderType.BITBUCKET, webhook_secret="secret"))
    github_provider = GitHubProvider(SCMProviderConfig(provider_type=SCMProviderType.GITHUB, webhook_secret="secret"))

    bitbucket_event = await bitbucket_provider.parse_pull_request_event(bitbucket_payload)
    github_event = await github_provider.parse_pull_request_event(github_payload)

    assert bitbucket_event is not None
    assert github_event is not None
    assert bitbucket_event.event_type == github_event.event_type
    assert bitbucket_event.pull_request_id == github_event.pull_request_id
    assert bitbucket_event.source_branch == github_event.source_branch
    assert bitbucket_event.target_branch == github_event.target_branch
    assert bitbucket_event.source_commit_sha == github_event.source_commit_sha
    assert bitbucket_event.target_commit_sha == github_event.target_commit_sha
