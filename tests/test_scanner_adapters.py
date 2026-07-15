from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from protecto_prime_agent.scanners.adapters.bandit_adapter import BanditAdapter
from protecto_prime_agent.scanners.adapters.gitleaks_adapter import GitleaksAdapter
from protecto_prime_agent.scanners.adapters.pip_audit_adapter import PipAuditAdapter
from protecto_prime_agent.scanners.adapters.pyright_adapter import PyrightAdapter
from protecto_prime_agent.scanners.adapters.ruff_adapter import RuffAdapter
from protecto_prime_agent.scanners.adapters.semgrep_adapter import SemgrepAdapter
from protecto_prime_agent.scanners.execution import (
    LocalProcessExecutionBackend,
    ResourceLimits,
    build_minimal_env,
)
from protecto_prime_agent.scanners.interface import ScannerAdapter, ScanRequest

_ALL_ADAPTER_CLASSES = [RuffAdapter, BanditAdapter, SemgrepAdapter, PyrightAdapter, GitleaksAdapter, PipAuditAdapter]

_LIMITS = ResourceLimits(timeout_seconds=30, cpu_seconds=30, memory_mb=1024, max_processes=128)

_HARDCODED_SECRET_VALUE = "hardcoded-super-secret-123"
_AWS_KEY_VALUE = "AKIAABCDEFGHIJKLMNOP"


def _make_request(workspace_path: Path) -> ScanRequest:
    return ScanRequest(
        workspace_path=workspace_path,
        commit_sha="a" * 40,
        workflow_run_id="wf-adapter-test",
        repository_id="repo-adapter-test",
    )


async def _execute(adapter: ScannerAdapter, workspace_path: Path, output_dir: Path):
    binary_path = shutil.which(adapter.binary_name())
    assert binary_path is not None, f"{adapter.binary_name()} must be installed to run this test"
    request = _make_request(workspace_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    command = adapter.build_command(request, binary_path, output_dir)
    backend = LocalProcessExecutionBackend()
    outcome = await backend.run(command, cwd=workspace_path, env=build_minimal_env(), limits=_LIMITS)
    assert not outcome.timed_out
    assert outcome.exit_code in adapter.success_exit_codes, (
        f"{adapter.name} exited {outcome.exit_code}, stderr={outcome.stderr[:500]}"
    )
    raw_output = adapter.read_output(outcome.stdout, output_dir)
    findings = adapter.parse_output(raw_output, request)
    return findings, request


def _write_vulnerable_python_repo(root: Path) -> None:
    (root / "bad.py").write_text(
        "\n".join(
            [
                "import os",
                "import subprocess",
                "",
                "",
                "def run(cmd):",
                "    subprocess.call(cmd, shell=True)",
                "",
                "",
                f'password = "{_HARDCODED_SECRET_VALUE}"',
                "",
                "",
                "def add(a: int, b: int) -> int:",
                "    return a + b",
                "",
                "",
                'result: int = add("x", "y")',
                "",
                "",
                "def unsafe(user_input):",
                "    return eval(user_input)",
                "",
            ]
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_ruff_adapter_maps_severity_and_category_by_rule_prefix(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_vulnerable_python_repo(workspace)

    findings, request = await _execute(RuffAdapter(), workspace, tmp_path / "output")

    by_rule = {f.rule_id: f for f in findings}
    assert by_rule["F401"].severity == "medium"
    assert by_rule["F401"].category == "quality"
    assert by_rule["S602"].severity == "high"
    assert by_rule["S602"].category == "security"
    assert by_rule["S105"].severity == "high"
    # ruff's message for hardcoded-password names the variable, not the secret value.
    assert _HARDCODED_SECRET_VALUE not in by_rule["S105"].message
    assert all(f.commit_sha == request.commit_sha for f in findings)
    assert all(f.file_path == "bad.py" for f in findings)


@pytest.mark.asyncio
async def test_bandit_adapter_redacts_hardcoded_secret_value(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_vulnerable_python_repo(workspace)

    findings, _request = await _execute(BanditAdapter(), workspace, tmp_path / "output")

    by_rule = {f.rule_id: f for f in findings}
    assert by_rule["B602"].severity == "high"
    assert by_rule["B602"].category == "security"
    assert by_rule["B602"].confidence == "high"

    secret_finding = by_rule["B105"]
    assert _HARDCODED_SECRET_VALUE not in secret_finding.message
    assert _HARDCODED_SECRET_VALUE not in secret_finding.raw_details_json
    assert "[REDACTED]" in secret_finding.raw_details_json


@pytest.mark.asyncio
async def test_semgrep_adapter_uses_offline_ruleset_and_normalizes_rule_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_vulnerable_python_repo(workspace)

    findings, _request = await _execute(SemgrepAdapter(), workspace, tmp_path / "output")

    by_rule = {f.rule_id: f for f in findings}
    # Rule ids must be exactly what we authored -- not prefixed with the local
    # filesystem path semgrep derives its check_id namespace from.
    assert "subprocess-shell-true" in by_rule
    assert "dangerous-eval-usage" in by_rule
    assert by_rule["dangerous-eval-usage"].severity == "high"
    assert by_rule["subprocess-shell-true"].severity == "medium"
    assert all(f.category == "security" for f in findings)


@pytest.mark.asyncio
async def test_pyright_adapter_detects_type_error(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "typed.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n\n\nresult: int = add('x', 'y')\n",
        encoding="utf-8",
    )

    findings, request = await _execute(PyrightAdapter(), workspace, tmp_path / "output")

    assert len(findings) >= 1
    assert all(f.category == "typing" for f in findings)
    assert all(f.severity == "high" for f in findings)
    assert all(f.file_path == "typed.py" for f in findings)
    assert all(f.commit_sha == request.commit_sha for f in findings)


@pytest.mark.asyncio
async def test_gitleaks_adapter_redacts_secret_value(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "secret.py").write_text(f'AWS_KEY = "{_AWS_KEY_VALUE}"\n', encoding="utf-8")

    findings, _request = await _execute(GitleaksAdapter(), workspace, tmp_path / "output")

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "critical"
    assert finding.category == "secret"
    assert finding.file_path == "secret.py"
    assert _AWS_KEY_VALUE not in finding.message
    assert _AWS_KEY_VALUE not in finding.raw_details_json
    assert "[REDACTED]" in finding.raw_details_json


@pytest.mark.asyncio
async def test_pip_audit_should_run_is_false_without_requirements_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = _make_request(workspace)

    assert PipAuditAdapter().should_run(request) is False


def test_pip_audit_should_run_is_true_with_requirements_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "requirements.txt").write_text("urllib3==1.24.1\n", encoding="utf-8")
    request = _make_request(workspace)

    assert PipAuditAdapter().should_run(request) is True


def test_pip_audit_adapter_parses_canned_output_deterministically(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "requirements.txt").write_text("urllib3==1.24.1\n", encoding="utf-8")
    request = _make_request(workspace)

    canned_output = json.dumps(
        {
            "dependencies": [
                {
                    "name": "urllib3",
                    "version": "1.24.1",
                    "vulns": [
                        {
                            "id": "PYSEC-2019-133",
                            "fix_versions": ["1.24.2"],
                            "aliases": ["CVE-2019-11324"],
                            "description": "mishandles certain cases of CA certificates",
                        }
                    ],
                }
            ],
            "fixes": [],
        }
    )

    findings = PipAuditAdapter().parse_output(canned_output, request)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "PYSEC-2019-133"
    assert finding.severity == "high"
    assert finding.category == "dependency"
    assert finding.confidence == "high"
    assert finding.file_path == "requirements.txt"
    assert "urllib3" in finding.message
    assert finding.commit_sha == request.commit_sha


@pytest.mark.parametrize("adapter_cls", _ALL_ADAPTER_CLASSES)
def test_malformed_output_raises_value_error(adapter_cls: type[ScannerAdapter], tmp_path: Path) -> None:
    request = _make_request(tmp_path)
    with pytest.raises(ValueError):
        adapter_cls().parse_output("not valid json { at all", request)


@pytest.mark.parametrize("adapter_cls", _ALL_ADAPTER_CLASSES)
def test_empty_output_yields_no_findings(adapter_cls: type[ScannerAdapter], tmp_path: Path) -> None:
    request = _make_request(tmp_path)
    assert adapter_cls().parse_output("", request) == []


@pytest.mark.parametrize("adapter_cls", _ALL_ADAPTER_CLASSES)
def test_all_adapters_use_argument_list_commands(adapter_cls: type[ScannerAdapter], tmp_path: Path) -> None:
    request = _make_request(tmp_path)
    command = adapter_cls().build_command(request, "/usr/bin/fake-tool", tmp_path / "output")
    assert isinstance(command, list)
    assert all(isinstance(part, str) for part in command)
    joined = " ".join(command)
    assert ";" not in joined and "&&" not in joined and "|" not in joined
