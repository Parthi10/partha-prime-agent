from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..database import SessionLocal
from ..enums import WorkspaceStatus
from ..integrations.scm import PullRequestEvent, SCMProvider
from ..logging import log_contextual
from ..models import AuditLog

settings = get_settings()

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Git global options applied to every invocation. credential.helper is disabled so
# git never reads or writes cached credentials to disk.
_GIT_SAFETY_ARGS = ["-c", "credential.helper="]

# A GIT_ASKPASS helper invoked by git for username/password prompts. It carries no
# secret of its own: it reads the token from an environment variable that lives only
# in the short-lived subprocess environment, never on disk.
_ASKPASS_SCRIPT = """#!/bin/sh
case "$1" in
    Username*) printf '%s' "${GIT_ASKPASS_USERNAME:-x-access-token}" ;;
    *) printf '%s' "$GIT_ASKPASS_TOKEN" ;;
esac
"""

_URL_CREDENTIAL_RE = re.compile(r"(https?://)[^/\s@]+@")
_PREFIXED_SECRET_PATTERNS = [
    re.compile(r"(?i)(x-access-token:)\S+"),
    re.compile(r"(?i)(authorization:\s*(?:basic|bearer)\s+)\S+"),
]
_BARE_SECRET_PATTERNS = [
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bATBB[A-Za-z0-9]{20,}\b"),
]


def redact_secrets(text: str) -> str:
    """Strip embedded credentials/tokens from git output before it is logged, stored, or raised."""
    if not text:
        return text
    redacted = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", text)
    for pattern in _PREFIXED_SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    for pattern in _BARE_SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class GitCommandError(RuntimeError):
    """Raised when a git subprocess exits non-zero. Message text is credential-redacted."""


class AuditWriter:
    """Injectable sink for workspace lifecycle audit events.

    Production code uses SqlAuditWriter. Unit tests inject a stub/recording writer so
    that git-focused tests never open a real database connection.
    """

    async def record(self, *, entity_type: str, entity_id: str, action: str, actor: str, metadata_json: str) -> None:
        raise NotImplementedError


class SqlAuditWriter(AuditWriter):
    """Writes audit events to the database. Never raises: failures are sanitized and logged."""

    async def record(self, *, entity_type: str, entity_id: str, action: str, actor: str, metadata_json: str) -> None:
        try:
            async with SessionLocal() as session:
                session.add(
                    AuditLog(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        action=action,
                        actor=actor,
                        metadata_json=metadata_json,
                    )
                )
                await session.commit()
        except Exception as exc:  # pragma: no cover - audit logging must never block workspace operations
            # Sanitized, structured failure event only: never log raw SQL, bind
            # parameters, or full exception text, any of which could echo credentials.
            log_contextual("audit_write_failed", action=action, entity_type=entity_type, error_type=type(exc).__name__)


class RepositoryWorkspaceService:
    """Provider-agnostic workspace lifecycle: clone, verify, diff, and clean up a PR's commits.

    This service only ever shells out to a fixed set of `git` subcommands with argument
    lists (never `shell=True`, never repository-controlled input as a command). It never
    executes repository code, installs repository dependencies, or runs post-checkout
    hooks (a freshly `git init`'d workspace has no hook scripts, and hooks are never
    transferred by fetch).

    Private-repository authentication never embeds a token in the clone URL or in
    `.git/config`; a token supplied via `CloneInfo.access_token` is passed to git only
    through a per-fetch, ephemeral GIT_ASKPASS helper (see `_ephemeral_askpass_env`) and
    is never logged or persisted.

    `MAX_WORKSPACE_SIZE_MB` and the pre-fetch disk-space check are best-effort
    application-level guards, not a hard sandbox. Production deployments should also
    apply an OS-level quota (a dedicated filesystem/volume quota, or a container
    ephemeral-storage/cgroup limit) on WORKSPACE_ROOT so a single runaway workspace
    cannot exhaust the host regardless of an application-level bug.
    """

    def __init__(
        self,
        workspace_root: str | os.PathLike[str] | None = None,
        audit_writer: AuditWriter | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root or settings.workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.clone_timeout = settings.git_clone_timeout_seconds
        self.fetch_timeout = settings.git_fetch_timeout_seconds
        self.max_workspace_size_mb = settings.max_workspace_size_mb
        self.retention_hours = settings.workspace_retention_hours
        self.max_network_retries = settings.git_network_max_retries
        self.network_retry_backoff_seconds = settings.git_network_retry_backoff_seconds
        self.audit_writer = audit_writer or SqlAuditWriter()

    def build_workspace_path(self, event: PullRequestEvent, workflow_run_id: str) -> Path:
        self._validate_component(event.repository_id, "repository_id")
        self._validate_component(event.pull_request_id, "pull_request_id")
        self._validate_component(event.source_commit_sha, "source_commit_sha")
        self._validate_component(workflow_run_id, "workflow_run_id")
        candidate = (
            self.workspace_root
            / event.repository_id
            / event.pull_request_id
            / event.source_commit_sha
            / workflow_run_id
        )
        resolved = candidate.resolve()
        if self.workspace_root not in resolved.parents:
            raise ValueError("workspace_path_escapes_root")
        return resolved

    def validate_commit_sha(self, sha: str) -> str:
        if not SHA_RE.fullmatch(sha):
            raise ValueError("malformed_sha")
        return sha

    async def prepare_workspace(self, provider: SCMProvider, event: PullRequestEvent, workflow_run_id: str) -> dict[str, Any]:
        self.validate_commit_sha(event.source_commit_sha)
        self.validate_commit_sha(event.target_commit_sha)
        workspace_path = self.build_workspace_path(event, workflow_run_id)

        await self._record_audit_event(
            "workspace_created",
            event=event,
            workflow_run_id=workflow_run_id,
            workspace_path=workspace_path,
            status=WorkspaceStatus.CREATED,
        )
        try:
            workspace_path.mkdir(parents=True, exist_ok=True)
            clone_info = await provider.get_clone_info(event)
            if clone_info is None:
                raise ValueError("clone_info_unavailable")
            self._validate_clone_url(clone_info.clone_url)
            self._ensure_disk_space_available(workspace_path)

            await self._record_audit_event(
                "clone_started",
                event=event,
                workflow_run_id=workflow_run_id,
                workspace_path=workspace_path,
                status=WorkspaceStatus.CLONING,
            )

            await self._clone_source_commit(
                clone_info.clone_url,
                workspace_path,
                event.source_commit_sha,
                clone_info.access_token,
                clone_info.access_username,
            )
            await self._fetch_target_commit(
                workspace_path,
                event.target_commit_sha,
                clone_info.access_token,
                clone_info.access_username,
            )
            self._verify_commit_exists(workspace_path, event.source_commit_sha)
            self._verify_commit_exists(workspace_path, event.target_commit_sha)
            self._ensure_workspace_size_limit(workspace_path)
            await self._checkout_source_detached(workspace_path, event.source_commit_sha)

            await self._record_audit_event(
                "clone_completed",
                event=event,
                workflow_run_id=workflow_run_id,
                workspace_path=workspace_path,
                status=WorkspaceStatus.READY,
            )

            diff_path = await self._generate_diff(workspace_path, event.target_commit_sha, event.source_commit_sha)

            await self._record_audit_event(
                "diff_generated",
                event=event,
                workflow_run_id=workflow_run_id,
                workspace_path=workspace_path,
                status=WorkspaceStatus.READY,
                extra={"diff_path": str(diff_path)},
            )

            return {
                "status": WorkspaceStatus.READY.value,
                "workspace_path": str(workspace_path),
                "diff_path": str(diff_path),
            }
        except Exception as exc:
            await self._record_audit_event(
                "failure",
                event=event,
                workflow_run_id=workflow_run_id,
                workspace_path=workspace_path,
                status=WorkspaceStatus.FAILED,
                extra={"error": redact_secrets(str(exc))},
            )
            # Failure always cleans up immediately, regardless of workspace retention.
            await self.cleanup_workspace(workspace_path)
            raise

    async def mark_processing_complete(self, workspace_path: Path) -> bool:
        """Call once the workflow orchestrator is done with a READY workspace.

        retention_hours <= 0 means clean up immediately. retention_hours > 0 retains the
        workspace on disk (for debugging) until `cleanup_stale_workspaces` reaps it.
        Returns True if the workspace was cleaned up immediately.
        """
        if self.retention_hours <= 0:
            await self.cleanup_workspace(workspace_path)
            return True
        return False

    async def cleanup_workspace(self, workspace_path: Path) -> None:
        existed = workspace_path.exists()
        if existed:
            shutil.rmtree(workspace_path, ignore_errors=True)
        repository_id, pull_request_id, workflow_run_id = self._decompose_workspace_path(workspace_path)
        await self._record_audit_event(
            "cleanup_completed",
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            workflow_run_id=workflow_run_id,
            workspace_path=workspace_path,
            status=WorkspaceStatus.CLEANED,
            extra={"existed": existed},
        )

    async def cleanup_stale_workspaces(self, retention_hours: int | None = None) -> list[Path]:
        retention_hours = retention_hours if retention_hours is not None else self.retention_hours
        now = datetime.now(timezone.utc)
        cleaned: list[Path] = []
        if not self.workspace_root.exists():
            return cleaned
        # Workspaces live exactly four levels deep: repository_id/pull_request_id/source_sha/workflow_run_id.
        for path in sorted(self.workspace_root.glob("*/*/*/*")):
            if not path.is_dir():
                continue
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except FileNotFoundError:
                continue
            if (now - mtime).total_seconds() < retention_hours * 3600:
                continue
            parent = path.parent
            await self.cleanup_workspace(path)
            cleaned.append(path)
            self._prune_empty_parents(parent)
        return cleaned

    def _prune_empty_parents(self, path: Path) -> None:
        current = path
        while current != self.workspace_root and current.exists() and not any(current.iterdir()):
            parent = current.parent
            current.rmdir()
            current = parent

    async def _clone_source_commit(
        self,
        clone_url: str,
        workspace_path: Path,
        source_sha: str,
        access_token: str | None,
        access_username: str,
    ) -> None:
        await self._run_git_command(["git", "init"], cwd=workspace_path)
        await self._run_git_command(["git", "remote", "add", "origin", clone_url], cwd=workspace_path)
        with self._ephemeral_askpass_env(access_token, access_username) as extra_env:
            await self._run_network_git_command(
                ["git", "fetch", "--depth=1", "origin", source_sha],
                cwd=workspace_path,
                timeout=self.clone_timeout,
                extra_env=extra_env,
            )

    async def _fetch_target_commit(
        self,
        workspace_path: Path,
        target_sha: str,
        access_token: str | None,
        access_username: str,
    ) -> None:
        with self._ephemeral_askpass_env(access_token, access_username) as extra_env:
            await self._run_network_git_command(
                ["git", "fetch", "--depth=1", "origin", target_sha],
                cwd=workspace_path,
                timeout=self.fetch_timeout,
                extra_env=extra_env,
            )

    async def _checkout_source_detached(self, workspace_path: Path, source_sha: str) -> None:
        await self._run_git_command(["git", "checkout", "--detach", source_sha], cwd=workspace_path)

    async def _generate_diff(self, workspace_path: Path, target_sha: str, source_sha: str) -> Path:
        diff_path = workspace_path / "diff.patch"
        result = await self._run_git_command(["git", "diff", "--unified=20", target_sha, source_sha], cwd=workspace_path)
        diff_path.write_text(result, encoding="utf-8")
        return diff_path

    @contextlib.contextmanager
    def _ephemeral_askpass_env(self, access_token: str | None, access_username: str) -> Iterator[dict[str, str] | None]:
        """Yield extra subprocess env vars supplying a one-shot GIT_ASKPASS credential helper.

        The askpass script itself contains no secret; it only reads GIT_ASKPASS_TOKEN /
        GIT_ASKPASS_USERNAME from the subprocess environment at invocation time. Nothing
        token-related is ever written to `.git/config`, a database row, or a log line.
        The script and its containing directory are removed as soon as this context
        exits, whether the git command it wrapped succeeded or failed.
        """
        if not access_token:
            yield None
            return
        askpass_dir = Path(tempfile.mkdtemp(prefix="ppa-askpass-"))
        os.chmod(askpass_dir, stat.S_IRWXU)
        askpass_path = askpass_dir / "askpass.sh"
        try:
            askpass_path.write_text(_ASKPASS_SCRIPT, encoding="utf-8")
            os.chmod(askpass_path, stat.S_IRWXU)
            yield {
                "GIT_ASKPASS": str(askpass_path),
                "GIT_ASKPASS_TOKEN": access_token,
                "GIT_ASKPASS_USERNAME": access_username,
            }
        finally:
            shutil.rmtree(askpass_dir, ignore_errors=True)

    async def _run_network_git_command(
        self,
        command: list[str],
        cwd: Path,
        timeout: int,
        extra_env: dict[str, str] | None = None,
    ) -> str:
        """Run a network-facing git command (fetch) with bounded retries on transient failures."""
        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self.max_network_retries:
            try:
                return await self._run_git_command(command, cwd=cwd, timeout=timeout, extra_env=extra_env)
            except (TimeoutError, GitCommandError) as exc:
                last_exc = exc
                attempt += 1
                if attempt > self.max_network_retries:
                    break
                await asyncio.sleep(self.network_retry_backoff_seconds * attempt)
        assert last_exc is not None
        raise last_exc

    async def _run_git_command(
        self,
        command: list[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> str:
        if timeout is None:
            timeout = self.clone_timeout
        argv = self._git_argv(command)
        git_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        if extra_env:
            git_env.update(extra_env)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: subprocess.run(
                        argv,
                        cwd=str(cwd) if cwd is not None else None,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        check=True,
                        env=git_env,
                        shell=False,
                    )
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError("git_command_timed_out") from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("git_command_timed_out") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("git_not_available") from exc
        except subprocess.CalledProcessError as exc:
            stderr = redact_secrets(exc.stderr or "")
            raise GitCommandError(f"git_command_failed: {stderr.strip()}") from None
        return redact_secrets(result.stdout)

    def _verify_commit_exists(self, workspace_path: Path, sha: str) -> None:
        argv = self._git_argv(["git", "-C", str(workspace_path), "rev-parse", "--verify", sha])
        git_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        result = subprocess.run(argv, capture_output=True, text=True, check=False, env=git_env, shell=False)
        if result.returncode != 0:
            raise ValueError("commit_not_found")

    def _ensure_disk_space_available(self, workspace_path: Path) -> None:
        """Best-effort pre-fetch guard: refuse to start a fetch the filesystem cannot hold.

        This is an application-level heuristic, not a hard sandbox. Production
        deployments should also enforce an OS-level quota on WORKSPACE_ROOT.
        """
        if self.max_workspace_size_mb <= 0:
            return
        usage = shutil.disk_usage(workspace_path)
        free_mb = usage.free / (1024 * 1024)
        if free_mb < self.max_workspace_size_mb:
            raise ValueError("insufficient_disk_space")

    def _ensure_workspace_size_limit(self, workspace_path: Path) -> None:
        if self.max_workspace_size_mb <= 0:
            return
        size_mb = sum(path.stat().st_size for path in workspace_path.rglob("*") if path.is_file()) / (1024 * 1024)
        if size_mb > self.max_workspace_size_mb:
            raise ValueError("workspace_too_large")

    def _validate_component(self, value: str, label: str) -> None:
        if not value or not SAFE_NAME_RE.fullmatch(value):
            raise ValueError(f"invalid_{label}")
        if value in {".", ".."}:
            raise ValueError(f"invalid_{label}")

    def _validate_clone_url(self, clone_url: str) -> None:
        if not clone_url.startswith(("https://", "http://", "file://")):
            raise ValueError("unsupported_clone_url")
        if "@" in clone_url:
            raise ValueError("credential_in_clone_url")

    def _git_argv(self, command: list[str]) -> list[str]:
        if command and command[0] == "git":
            return ["git", *_GIT_SAFETY_ARGS, *command[1:]]
        return command

    def _decompose_workspace_path(self, workspace_path: Path) -> tuple[str, str, str]:
        try:
            relative = workspace_path.resolve().relative_to(self.workspace_root)
        except ValueError:
            return "unknown", "unknown", workspace_path.name
        parts = relative.parts
        if len(parts) >= 4:
            return parts[0], parts[1], parts[3]
        return "unknown", "unknown", workspace_path.name

    async def _record_audit_event(
        self,
        action: str,
        *,
        workspace_path: Path,
        status: WorkspaceStatus,
        event: PullRequestEvent | None = None,
        repository_id: str | None = None,
        pull_request_id: str | None = None,
        workflow_run_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if event is not None:
            repository_id = event.repository_id
            pull_request_id = event.pull_request_id
        repository_id = repository_id or "unknown"
        pull_request_id = pull_request_id or "unknown"
        workflow_run_id = workflow_run_id or "unknown"

        entity_id = f"{repository_id}:{pull_request_id}:{workflow_run_id}"
        payload: dict[str, Any] = {
            "workflow_run_id": workflow_run_id,
            "repository_id": repository_id,
            "pull_request_id": pull_request_id,
            "workspace_path": str(workspace_path),
            "status": status.value,
        }
        if extra:
            payload.update(extra)
        metadata_json = redact_secrets(json.dumps(payload, default=str))

        try:
            await self.audit_writer.record(
                entity_type="repository_workspace",
                entity_id=entity_id,
                action=action,
                actor="system",
                metadata_json=metadata_json,
            )
        except Exception as exc:  # pragma: no cover - defensive; injected writers should not raise
            log_contextual("audit_write_failed", action=action, entity_type="repository_workspace", error_type=type(exc).__name__)
