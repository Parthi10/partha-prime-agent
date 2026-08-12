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
    repository_full_name: str
    provider_event_id: str | None = None


@dataclass(slots=True)
class CloneInfo:
    clone_url: str
    repository_name: str
    # Ephemeral credential for private-repository access. Never embedded in clone_url,
    # never persisted (DB or .git/config); consumed only via a short-lived GIT_ASKPASS
    # helper for the duration of a single fetch operation.
    access_token: str | None = None
    access_username: str = "x-access-token"


class SCMProvider(Protocol):
    async def validate_webhook(self, body: bytes, signature: str | None) -> bool:
        """Validate a webhook request."""
        raise NotImplementedError

    async def parse_pull_request_event(self, payload: dict[str, object]) -> PullRequestEvent | None:
        """Parse supported pull request payloads into a normalized event object."""
        raise NotImplementedError

    async def get_clone_info(self, event: PullRequestEvent) -> CloneInfo | None:
        """Return provider-specific clone information for a normalized pull request event."""
        raise NotImplementedError
