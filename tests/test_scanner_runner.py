from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from protecto_prime_agent.enums import ScannerExecutionStatus
from protecto_prime_agent.scanners.audit import AuditWriter
from protecto_prime_agent.scanners.config import ScannerRuntimeConfig
from protecto_prime_agent.scanners.execution import ResourceLimits
from protecto_prime_agent.scanners.interface import NormalizedFinding, ScannerAdapter, ScanRequest
from protecto_prime_agent.scanners.registry import ScannerRegistry
from protecto_prime_agent.scanners.runner import ScannerRunner


class RecordingAuditWriter(AuditWriter):
    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    async def record(self, *, entity_type: str, entity_id: str, action: str, actor: str, metadata_json: str) -> None:
        self.events.append(
            {"entity_type": entity_type, "entity_id": entity_id, "action": action, "actor": actor, "metadata_json": metadata_json}
        )


class _SuccessAdapter(ScannerAdapter):
    name = "stub-success"
    category_default = "quality"

    def binary_name(self) -> str:
        return "python3"

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        return [binary_path, "-c", "print('[{\"ok\": true}]')"]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        json.loads(raw_output)  # would raise ValueError if malformed
        return [
            NormalizedFinding(
                scanner_name=self.name,
                rule_id="stub-rule",
                severity="low",
                category="quality",
                confidence="medium",
                message="stub finding",
                file_path="app.py",
                line_number=1,
                column_number=1,
                fingerprint="fingerprint-stub",
                commit_sha=request.commit_sha,
                raw_details_json=raw_output,
            )
        ]


class _NonZeroExitAdapter(ScannerAdapter):
    name = "stub-nonzero-exit"
    category_default = "quality"

    def binary_name(self) -> str:
        return "python3"

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        return [binary_path, "-c", "import sys; sys.exit(3)"]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        return []


class _SleepAdapter(ScannerAdapter):
    name = "stub-sleep"
    category_default = "quality"

    def binary_name(self) -> str:
        return "python3"

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        return [binary_path, "-c", "import time; time.sleep(5)"]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        return []


class _MalformedOutputAdapter(ScannerAdapter):
    name = "stub-malformed"
    category_default = "quality"

    def binary_name(self) -> str:
        return "python3"

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        return [binary_path, "-c", "print('not valid json')"]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        raise ValueError("malformed_stub_output")


class _MissingBinaryAdapter(ScannerAdapter):
    name = "stub-missing-binary"
    category_default = "quality"

    def binary_name(self) -> str:
        return "definitely-not-a-real-binary-xyz"

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        return [binary_path]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        return []


class _EnvEchoAdapter(ScannerAdapter):
    name = "stub-env-echo"
    category_default = "quality"

    def binary_name(self) -> str:
        return "python3"

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        return [binary_path, "-c", "import json, os; print(json.dumps(dict(os.environ)))"]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        env = json.loads(raw_output)
        return [
            NormalizedFinding(
                scanner_name=self.name,
                rule_id="env-snapshot",
                severity="info",
                category="quality",
                confidence="high",
                message="env snapshot",
                file_path=None,
                line_number=None,
                column_number=None,
                fingerprint="fp-env",
                commit_sha=request.commit_sha,
                raw_details_json=json.dumps(env),
            )
        ]


def _make_config(tmp_path: Path, enabled: tuple[str, ...], timeout_seconds: int = 15) -> ScannerRuntimeConfig:
    return ScannerRuntimeConfig(
        enabled_scanners=enabled,
        output_root=tmp_path / "scanner-output",
        limits=ResourceLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds, memory_mb=256, max_processes=64),
        tool_versions={},
    )


def _make_request(tmp_path: Path, workflow_run_id: str = "wf-1") -> ScanRequest:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir(exist_ok=True)
    return ScanRequest(
        workspace_path=workspace_path,
        commit_sha="a" * 40,
        workflow_run_id=workflow_run_id,
        repository_id="repo-1",
    )


@pytest.mark.asyncio
async def test_successful_scanner_execution(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_SuccessAdapter())
    config = _make_config(tmp_path, ("stub-success",))
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    result = await runner.run_scan(_make_request(tmp_path))

    assert len(result.scan_results) == 1
    scan_result = result.scan_results[0]
    assert scan_result.status == ScannerExecutionStatus.COMPLETED
    assert scan_result.exit_code == 0
    assert len(scan_result.findings) == 1
    assert scan_result.findings[0].rule_id == "stub-rule"


@pytest.mark.asyncio
async def test_scanner_non_zero_exit_is_recorded_as_failed(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_NonZeroExitAdapter())
    config = _make_config(tmp_path, ("stub-nonzero-exit",))
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    result = await runner.run_scan(_make_request(tmp_path))

    scan_result = result.scan_results[0]
    assert scan_result.status == ScannerExecutionStatus.FAILED
    assert scan_result.exit_code == 3
    assert scan_result.findings == []


@pytest.mark.asyncio
async def test_scanner_timeout_is_recorded_independently(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_SleepAdapter())
    config = _make_config(tmp_path, ("stub-sleep",), timeout_seconds=1)
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    result = await runner.run_scan(_make_request(tmp_path))

    scan_result = result.scan_results[0]
    assert scan_result.status == ScannerExecutionStatus.TIMEOUT
    assert scan_result.exit_code is None


@pytest.mark.asyncio
async def test_malformed_scanner_output_is_inconclusive(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_MalformedOutputAdapter())
    config = _make_config(tmp_path, ("stub-malformed",))
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    result = await runner.run_scan(_make_request(tmp_path))

    scan_result = result.scan_results[0]
    assert scan_result.status == ScannerExecutionStatus.INCONCLUSIVE
    assert scan_result.exit_code == 0
    assert "malformed_stub_output" in (scan_result.error_message or "")


@pytest.mark.asyncio
async def test_missing_tool_binary_is_recorded_as_failed(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_MissingBinaryAdapter())
    config = _make_config(tmp_path, ("stub-missing-binary",))
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    result = await runner.run_scan(_make_request(tmp_path))

    scan_result = result.scan_results[0]
    assert scan_result.status == ScannerExecutionStatus.FAILED
    assert scan_result.error_message == "tool_not_available"


@pytest.mark.asyncio
async def test_one_scanner_failure_does_not_block_others_and_result_is_aggregated(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_SuccessAdapter())
    registry.register(_NonZeroExitAdapter())
    registry.register(_MalformedOutputAdapter())
    config = _make_config(tmp_path, ("stub-success", "stub-nonzero-exit", "stub-malformed"))
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    result = await runner.run_scan(_make_request(tmp_path))

    statuses = {r.scanner_name: r.status for r in result.scan_results}
    assert statuses["stub-success"] == ScannerExecutionStatus.COMPLETED
    assert statuses["stub-nonzero-exit"] == ScannerExecutionStatus.FAILED
    assert statuses["stub-malformed"] == ScannerExecutionStatus.INCONCLUSIVE
    assert result.has_failures is True
    # Aggregated findings only include the successful scanner's findings.
    assert len(result.findings) == 1
    assert result.findings[0].scanner_name == "stub-success"


@pytest.mark.asyncio
async def test_disabled_scanner_is_not_executed(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_SuccessAdapter())
    registry.register(_NonZeroExitAdapter())
    config = _make_config(tmp_path, ("stub-success",))  # stub-nonzero-exit not enabled
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    result = await runner.run_scan(_make_request(tmp_path))

    assert [r.scanner_name for r in result.scan_results] == ["stub-success"]


@pytest.mark.asyncio
async def test_cleanup_after_success(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_SuccessAdapter())
    config = _make_config(tmp_path, ("stub-success",))
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    await runner.run_scan(_make_request(tmp_path, workflow_run_id="wf-cleanup-success"))

    assert not (config.output_root / "wf-cleanup-success").exists()


@pytest.mark.asyncio
async def test_cleanup_after_scanner_failure(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_NonZeroExitAdapter())
    config = _make_config(tmp_path, ("stub-nonzero-exit",))
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    await runner.run_scan(_make_request(tmp_path, workflow_run_id="wf-cleanup-failure"))

    assert not (config.output_root / "wf-cleanup-failure").exists()


@pytest.mark.asyncio
async def test_output_directory_path_traversal_is_rejected(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_SuccessAdapter())
    config = _make_config(tmp_path, ("stub-success",))
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    request = _make_request(tmp_path, workflow_run_id="../../evil")
    with pytest.raises(ValueError):
        await runner.run_scan(request)


@pytest.mark.asyncio
async def test_audit_events_cover_full_scanner_lifecycle(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_SuccessAdapter())
    registry.register(_SleepAdapter())
    config = _make_config(tmp_path, ("stub-success", "stub-sleep"), timeout_seconds=1)
    writer = RecordingAuditWriter()
    runner = ScannerRunner(registry, config, audit_writer=writer)

    await runner.run_scan(_make_request(tmp_path))

    actions = [event["action"] for event in writer.events]
    assert "scan_started" in actions
    assert "scanner_started" in actions
    assert "scanner_completed" in actions
    assert "scanner_timeout" in actions
    assert "scan_completed" in actions
    assert "cleanup_completed" in actions


@pytest.mark.asyncio
async def test_no_platform_secrets_reach_scanner_environment(tmp_path: Path) -> None:
    registry = ScannerRegistry()
    registry.register(_EnvEchoAdapter())
    config = _make_config(tmp_path, ("stub-env-echo",))
    runner = ScannerRunner(registry, config, audit_writer=RecordingAuditWriter())

    fake_secrets = {
        "DATABASE_PASSWORD": "db-secret-value",
        "REDIS_PASSWORD": "redis-secret-value",
        "BITBUCKET_WEBHOOK_SECRET": "bitbucket-secret-value",
        "GITHUB_WEBHOOK_SECRET": "github-secret-value",
    }
    with patch.dict(os.environ, fake_secrets):
        result = await runner.run_scan(_make_request(tmp_path))

    scanner_env = json.loads(result.scan_results[0].findings[0].raw_details_json)
    for key, value in fake_secrets.items():
        assert key not in scanner_env
        assert value not in scanner_env.values()
