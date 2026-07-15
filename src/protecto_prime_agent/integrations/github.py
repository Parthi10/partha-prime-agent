from __future__ import annotations

import hashlib
import hmac

from .scm import PullRequestEvent, SCMProvider, SCMProviderConfig


class GitHubProvider(SCMProvider):
    def __init__(self, config: SCMProviderConfig) -> None:
        self.config = config

    async def validate_webhook(self, body: bytes, signature: str | None) -> bool:
        if not self.config.webhook_secret:
            return False
        if not signature:
            return False

        if signature.startswith("sha1="):
            expected = hmac.new(
                self.config.webhook_secret.encode("utf-8"),
                body,
                hashlib.sha1,
            ).hexdigest()
            return hmac.compare_digest(signature, f"sha1={expected}")

        if signature.startswith("sha256="):
            expected = hmac.new(
                self.config.webhook_secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(signature, f"sha256={expected}")

        return False

    async def parse_pull_request_event(self, payload: dict[str, object]) -> PullRequestEvent | None:
        action = payload.get("action")
        if not isinstance(action, str) or action not in {"opened", "reopened", "synchronize"}:
            return None

        pull_request = payload.get("pull_request")
        if not isinstance(pull_request, dict):
            return None

        pr_id = pull_request.get("id")
        if not isinstance(pr_id, int):
            return None

        head = pull_request.get("head")
        base = pull_request.get("base")
        if not isinstance(head, dict) or not isinstance(base, dict):
            return None

        source_branch = head.get("ref")
        target_branch = base.get("ref")
        source_commit_sha = head.get("sha")
        target_commit_sha = base.get("sha")
        if not isinstance(source_branch, str) or not source_branch:
            return None
        if not isinstance(target_branch, str) or not target_branch:
            return None
        if not isinstance(source_commit_sha, str) or not source_commit_sha:
            return None
        if not isinstance(target_commit_sha, str) or not target_commit_sha:
            return None
        if target_branch not in {"main", "master", "develop"}:
            return None

        repository = payload.get("repository")
        if not isinstance(repository, dict):
            return None

        repository_id = repository.get("id")
        if not isinstance(repository_id, int):
            return None

        return PullRequestEvent(
            event_type="pull_request",
            repository_id=str(repository_id),
            pull_request_id=str(pr_id),
            source_branch=source_branch,
            target_branch=target_branch,
            source_commit_sha=source_commit_sha,
            target_commit_sha=target_commit_sha,
            provider_event_id=action,
        )
