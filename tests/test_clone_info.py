from __future__ import annotations

import pytest

from protecto_prime_agent.integrations.bitbucket import BitbucketProvider
from protecto_prime_agent.integrations.github import GitHubProvider
from protecto_prime_agent.integrations.scm import SCMProviderConfig, SCMProviderType


def _github_payload(full_name: str = "acme/demo-repo") -> dict[str, object]:
    return {
        "action": "opened",
        "pull_request": {
            "id": 456,
            "head": {"ref": "feature/github", "sha": "abc123"},
            "base": {"ref": "main", "sha": "def456"},
        },
        "repository": {"id": 789, "name": "demo-repo", "full_name": full_name},
    }


def _bitbucket_payload(full_name: str = "acme-workspace/demo-repo") -> dict[str, object]:
    return {
        "eventKey": "pr:created",
        "pullrequest": {
            "id": 123,
            "source": {"branch": {"name": "feature/test"}, "commit": {"hash": "abc123"}},
            "destination": {"branch": {"name": "main"}, "commit": {"hash": "def456"}},
        },
        "repository": {"uuid": "repo-123", "full_name": full_name},
    }


@pytest.mark.asyncio
async def test_github_clone_info_uses_repository_full_name() -> None:
    provider = GitHubProvider(SCMProviderConfig(provider_type=SCMProviderType.GITHUB, webhook_secret="secret"))
    event = await provider.parse_pull_request_event(_github_payload("acme/demo-repo"))
    assert event is not None
    assert event.repository_full_name == "acme/demo-repo"

    clone_info = await provider.get_clone_info(event)

    assert clone_info is not None
    assert clone_info.clone_url == "https://github.com/acme/demo-repo.git"
    assert clone_info.repository_name == "acme/demo-repo"
    assert "github.example" not in clone_info.clone_url
    assert "@" not in clone_info.clone_url


@pytest.mark.asyncio
async def test_github_missing_full_name_is_ignored() -> None:
    provider = GitHubProvider(SCMProviderConfig(provider_type=SCMProviderType.GITHUB, webhook_secret="secret"))
    payload = _github_payload()
    del payload["repository"]["full_name"]  # type: ignore[index]

    event = await provider.parse_pull_request_event(payload)

    assert event is None


@pytest.mark.asyncio
async def test_bitbucket_clone_info_uses_workspace_repository_metadata() -> None:
    provider = BitbucketProvider(SCMProviderConfig(provider_type=SCMProviderType.BITBUCKET, webhook_secret="secret"))
    event = await provider.parse_pull_request_event(_bitbucket_payload("acme-workspace/demo-repo"))
    assert event is not None
    assert event.repository_full_name == "acme-workspace/demo-repo"

    clone_info = await provider.get_clone_info(event)

    assert clone_info is not None
    assert clone_info.clone_url == "https://bitbucket.org/acme-workspace/demo-repo.git"
    assert clone_info.repository_name == "acme-workspace/demo-repo"
    assert "bitbucket.example" not in clone_info.clone_url
    assert "@" not in clone_info.clone_url


@pytest.mark.asyncio
async def test_bitbucket_missing_full_name_is_ignored() -> None:
    provider = BitbucketProvider(SCMProviderConfig(provider_type=SCMProviderType.BITBUCKET, webhook_secret="secret"))
    payload = _bitbucket_payload()
    del payload["repository"]["full_name"]  # type: ignore[index]

    event = await provider.parse_pull_request_event(payload)

    assert event is None
