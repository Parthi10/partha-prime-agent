from __future__ import annotations

import hashlib
import hmac

from .scm import CloneInfo, PullRequestEvent, SCMProvider, SCMProviderConfig


class BitbucketProvider(SCMProvider):
    def __init__(self, config: SCMProviderConfig) -> None:
        self.config = config

    async def validate_webhook(self, body: bytes, signature: str | None) -> bool:
        if not self.config.webhook_secret:
            return False
        if not signature:
            return False
        expected = hmac.new(
            self.config.webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    async def parse_pull_request_event(self, payload: dict[str, object]) -> PullRequestEvent | None:
        event_key = payload.get("eventKey")
        if not isinstance(event_key, str):
            return None

        if event_key not in {"pr:created", "pr:updated", "pr:reopened", "pr:changed"}:
            return None

        pull_request = payload.get("pullrequest")
        if not isinstance(pull_request, dict):
            return None

        destination = pull_request.get("destination")
        if not isinstance(destination, dict):
            return None

        branch = destination.get("branch")
        if not isinstance(branch, dict):
            return None

        target_branch = branch.get("name")
        if not isinstance(target_branch, str):
            return None
        if target_branch not in {"main", "master", "develop"}:
            return None

        source = pull_request.get("source")
        if not isinstance(source, dict):
            return None

        source_branch = source.get("branch")
        if not isinstance(source_branch, dict):
            return None

        source_branch_name = source_branch.get("name")
        if not isinstance(source_branch_name, str) or not source_branch_name:
            return None

        source_commit = source.get("commit")
        if not isinstance(source_commit, dict):
            return None

        target_commit = destination.get("commit")
        if not isinstance(target_commit, dict):
            return None

        source_commit_sha = source_commit.get("hash")
        target_commit_sha = target_commit.get("hash")
        if not isinstance(source_commit_sha, str) or not isinstance(target_commit_sha, str):
            return None

        repository = payload.get("repository")
        if not isinstance(repository, dict):
            return None

        repository_uuid = repository.get("uuid")
        if not isinstance(repository_uuid, str) or not repository_uuid:
            return None

        full_name = repository.get("full_name")
        if not isinstance(full_name, str) or not full_name:
            return None

        pr_id = pull_request.get("id")
        if not isinstance(pr_id, int):
            return None

        return PullRequestEvent(
            event_type="pull_request",
            repository_id=repository_uuid,
            pull_request_id=str(pr_id),
            source_branch=source_branch_name,
            target_branch=target_branch,
            source_commit_sha=source_commit_sha,
            target_commit_sha=target_commit_sha,
            repository_full_name=full_name,
            provider_event_id=event_key,
        )

    async def get_clone_info(self, event: PullRequestEvent) -> CloneInfo | None:
        return CloneInfo(
            clone_url=f"https://bitbucket.org/{event.repository_full_name}.git",
            repository_name=event.repository_full_name,
        )
