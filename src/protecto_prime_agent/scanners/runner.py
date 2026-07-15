from __future__ import annotations

import asyncio
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..enums import ScannerExecutionStatus
from ..logging import log_contextual
from .audit import AuditWriter, SqlAuditWriter
from .config import ScannerRuntimeConfig
from .execution import (
    ExecutionBackend,
    LocalProcessExecutionBackend,
    ResourceLimits,
    build_minimal_env,
)
from .interface import AggregatedScanResult, ScannerAdapter, ScanRequest, ScanResult
from .normalization import sanitize_text
from .registry import ScannerRegistry

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

_VERSION_CHECK_LIMITS = ResourceLimits(timeout_seconds=10, cpu_seconds=10, memory_mb=256, max_processes=16)


class ScannerRunner:
    """Provider-agnostic orchestrator: runs every enabled scanner against a workspace.

    Each scanner is executed and evaluated independently -- one adapter crashing,
    timing out, or producing malformed output never prevents the others from running
    or from being reported in the aggregated result.
    """

    def __init__(
        self,
        registry: ScannerRegistry,
        config: ScannerRuntimeConfig,
        execution_backend: ExecutionBackend | None = None,
        audit_writer: AuditWriter | None = None,
    ) -> None:
        self.registry = registry
        self.config = config
        self.config.output_root.mkdir(parents=True, exist_ok=True)
        self.execution_backend = execution_backend or LocalProcessExecutionBackend()
        self.audit_writer = audit_writer or SqlAuditWriter()

    async def run_scan(self, request: ScanRequest) -> AggregatedScanResult:
        started_at = datetime.now(timezone.utc)
        output_dir = self._build_scan_output_dir(request.workflow_run_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        await self._audit("scan_started", request, extra={"output_dir": str(output_dir)})
        try:
            adapters = self.registry.resolve_enabled(request.enabled_scanners or self.config.enabled_scanners)
            results = list(
                await asyncio.gather(*(self._run_one(adapter, request, output_dir) for adapter in adapters))
            )
            completed_at = datetime.now(timezone.utc)
            await self._audit("scan_completed", request, extra={"scanner_count": len(results)})
            return AggregatedScanResult(
                workflow_run_id=request.workflow_run_id,
                commit_sha=request.commit_sha,
                scan_results=results,
                started_at=started_at,
                completed_at=completed_at,
            )
        finally:
            await self._cleanup(output_dir, request)

    async def _run_one(self, adapter: ScannerAdapter, request: ScanRequest, output_dir: Path) -> ScanResult:
        started_at = datetime.now(timezone.utc)
        scanner_output_dir = output_dir / adapter.name
        scanner_output_dir.mkdir(parents=True, exist_ok=True)

        try:
            if not adapter.should_run(request):
                return ScanResult(
                    scanner_name=adapter.name,
                    status=ScannerExecutionStatus.COMPLETED,
                    findings=[],
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=0.0,
                )

            binary_path = shutil.which(adapter.binary_name())
            if binary_path is None:
                await self._audit("scanner_failed", request, scanner_name=adapter.name, extra={"reason": "tool_not_available"})
                return ScanResult(
                    scanner_name=adapter.name,
                    status=ScannerExecutionStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    error_message="tool_not_available",
                )

            await self._audit("scanner_started", request, scanner_name=adapter.name)

            tool_version = await self._detect_version(adapter, binary_path, request.workspace_path)
            self._warn_on_version_mismatch(adapter, tool_version)

            command = adapter.build_command(request, binary_path, scanner_output_dir)
            env = build_minimal_env()
            outcome = await self.execution_backend.run(
                command, cwd=request.workspace_path, env=env, limits=self.config.limits
            )
            duration = (datetime.now(timezone.utc) - started_at).total_seconds()

            if outcome.timed_out:
                await self._audit("scanner_timeout", request, scanner_name=adapter.name)
                return ScanResult(
                    scanner_name=adapter.name,
                    status=ScannerExecutionStatus.TIMEOUT,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=duration,
                    tool_version=tool_version,
                    error_message="scanner_timed_out",
                )

            if outcome.error is not None or outcome.exit_code is None:
                error_message = sanitize_text(outcome.error or "execution_failed")
                await self._audit("scanner_failed", request, scanner_name=adapter.name, extra={"error": error_message})
                return ScanResult(
                    scanner_name=adapter.name,
                    status=ScannerExecutionStatus.FAILED,
                    exit_code=outcome.exit_code,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=duration,
                    tool_version=tool_version,
                    error_message=error_message,
                )

            if outcome.exit_code not in adapter.success_exit_codes:
                error_message = sanitize_text(outcome.stderr)[:2000]
                await self._audit(
                    "scanner_failed",
                    request,
                    scanner_name=adapter.name,
                    extra={"exit_code": outcome.exit_code},
                )
                return ScanResult(
                    scanner_name=adapter.name,
                    status=ScannerExecutionStatus.FAILED,
                    exit_code=outcome.exit_code,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=duration,
                    tool_version=tool_version,
                    error_message=error_message,
                )

            raw_output = adapter.read_output(outcome.stdout, scanner_output_dir)
            (scanner_output_dir / "raw_output.txt").write_text(sanitize_text(raw_output), encoding="utf-8")

            try:
                findings = adapter.parse_output(raw_output, request)
            except ValueError as exc:
                await self._audit(
                    "scanner_failed", request, scanner_name=adapter.name, extra={"reason": "malformed_output"}
                )
                return ScanResult(
                    scanner_name=adapter.name,
                    status=ScannerExecutionStatus.INCONCLUSIVE,
                    exit_code=outcome.exit_code,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=duration,
                    tool_version=tool_version,
                    error_message=sanitize_text(str(exc)),
                )

            await self._audit(
                "scanner_completed", request, scanner_name=adapter.name, extra={"finding_count": len(findings)}
            )
            return ScanResult(
                scanner_name=adapter.name,
                status=ScannerExecutionStatus.COMPLETED,
                findings=findings,
                exit_code=outcome.exit_code,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                duration_seconds=duration,
                tool_version=tool_version,
            )
        except Exception as exc:  # a single scanner crashing must never affect the others
            await self._audit(
                "scanner_failed", request, scanner_name=adapter.name, extra={"error_type": type(exc).__name__}
            )
            return ScanResult(
                scanner_name=adapter.name,
                status=ScannerExecutionStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                error_message=sanitize_text(str(exc)),
            )

    async def _cleanup(self, output_dir: Path, request: ScanRequest) -> None:
        existed = output_dir.exists()
        if existed:
            shutil.rmtree(output_dir, ignore_errors=True)
        await self._audit("cleanup_completed", request, extra={"existed": existed})

    async def _detect_version(self, adapter: ScannerAdapter, binary_path: str, cwd: Path) -> str | None:
        try:
            outcome = await self.execution_backend.run(
                [binary_path, *adapter.version_args()],
                cwd=cwd,
                env=build_minimal_env(),
                limits=_VERSION_CHECK_LIMITS,
            )
        except Exception:  # pragma: no cover - version detection is best-effort only
            return None
        if outcome.timed_out or outcome.error is not None or not outcome.stdout.strip():
            return None
        first_line = outcome.stdout.strip().splitlines()[0]
        return sanitize_text(first_line)[:200]

    def _warn_on_version_mismatch(self, adapter: ScannerAdapter, detected_version: str | None) -> None:
        expected = self.config.tool_versions.get(adapter.name)
        if expected and detected_version and expected not in detected_version:
            log_contextual(
                "scanner_version_mismatch",
                scanner_name=adapter.name,
                expected=expected,
                detected=detected_version,
            )

    def _build_scan_output_dir(self, workflow_run_id: str) -> Path:
        if not workflow_run_id or not SAFE_NAME_RE.fullmatch(workflow_run_id):
            raise ValueError("invalid_workflow_run_id")
        candidate = self.config.output_root / workflow_run_id
        resolved = candidate.resolve()
        if self.config.output_root.resolve() not in resolved.parents:
            raise ValueError("scanner_output_path_escapes_root")
        return resolved

    async def _audit(
        self,
        action: str,
        request: ScanRequest,
        *,
        scanner_name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        entity_id = f"{request.repository_id}:{request.workflow_run_id}"
        if scanner_name:
            entity_id = f"{entity_id}:{scanner_name}"
        payload: dict[str, Any] = {
            "workflow_run_id": request.workflow_run_id,
            "repository_id": request.repository_id,
            "commit_sha": request.commit_sha,
        }
        if scanner_name:
            payload["scanner_name"] = scanner_name
        if extra:
            payload.update(extra)
        metadata_json = sanitize_text(json.dumps(payload, default=str))
        try:
            await self.audit_writer.record(
                entity_type="scanner_execution",
                entity_id=entity_id,
                action=action,
                actor="system",
                metadata_json=metadata_json,
            )
        except Exception as exc:  # pragma: no cover - defensive; injected writers should not raise
            log_contextual("audit_write_failed", action=action, entity_type="scanner_execution", error_type=type(exc).__name__)
