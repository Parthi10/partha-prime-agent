from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class SCMProviderType(str, Enum):
    BITBUCKET = "bitbucket"
    GITHUB = "github"
    GITLAB = "gitlab"


@dataclass(slots=True)
class SCMProviderConfig:
    provider_type: SCMProviderType
    webhook_secret: str | None = None


@dataclass(slots=True)
class PullRequestEvent:
    event_type: str
    repository_id: str
    pull_request_id: str
    source_branch: str
    target_branch: str
    source_commit_sha: str
    target_commit_sha: str
    provider_event_id: str | None = None


class SCMProvider(Protocol):
    async def validate_webhook(self, body: bytes, signature: str | None) -> bool:
        """Validate a webhook request."""
        raise NotImplementedError

    async def parse_pull_request_event(self, payload: dict[str, object]) -> PullRequestEvent | None:
        """Parse supported pull request payloads into a normalized event object."""
        raise NotImplementedError
