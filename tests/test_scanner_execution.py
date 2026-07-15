from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from protecto_prime_agent.scanners.execution import (
    ContainerExecutionBackend,
    LocalProcessExecutionBackend,
    ResourceLimits,
    build_minimal_env,
)

_FAKE_SECRETS = {
    "DATABASE_PASSWORD": "db-secret-value",
    "REDIS_PASSWORD": "redis-secret-value",
    "BITBUCKET_WEBHOOK_SECRET": "bitbucket-secret-value",
    "GITHUB_WEBHOOK_SECRET": "github-secret-value",
    "SMTP_PASSWORD": "smtp-secret-value",
    "GIT_ASKPASS_TOKEN": "scm-access-token-value",
}


def test_build_minimal_env_excludes_platform_secrets() -> None:
    with patch.dict(os.environ, _FAKE_SECRETS):
        env = build_minimal_env()

    for key, value in _FAKE_SECRETS.items():
        assert key not in env
        assert value not in env.values()


def test_build_minimal_env_only_contains_allowlisted_keys() -> None:
    allowlist = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "PYTHONHASHSEED", "SEMGREP_SEND_METRICS"}
    env = build_minimal_env()
    assert set(env.keys()) <= allowlist


def test_build_minimal_env_merges_extra_without_leaking_full_environment() -> None:
    with patch.dict(os.environ, _FAKE_SECRETS):
        env = build_minimal_env(extra={"GIT_ASKPASS_TOKEN": "one-shot-token"})

    assert env["GIT_ASKPASS_TOKEN"] == "one-shot-token"
    assert "scm-access-token-value" not in env.values()


@pytest.mark.asyncio
async def test_local_backend_runs_argument_list_without_shell(tmp_path: Path) -> None:
    backend = LocalProcessExecutionBackend()
    limits = ResourceLimits(timeout_seconds=5, cpu_seconds=5, memory_mb=256, max_processes=32)

    outcome = await backend.run(
        ["python3", "-c", "print('hello')"],
        cwd=tmp_path,
        env=build_minimal_env(),
        limits=limits,
    )

    assert outcome.exit_code == 0
    assert "hello" in outcome.stdout
    assert not outcome.timed_out


@pytest.mark.asyncio
async def test_local_backend_reports_non_zero_exit_without_raising(tmp_path: Path) -> None:
    backend = LocalProcessExecutionBackend()
    limits = ResourceLimits(timeout_seconds=5, cpu_seconds=5, memory_mb=256, max_processes=32)

    outcome = await backend.run(
        ["python3", "-c", "import sys; sys.exit(1)"],
        cwd=tmp_path,
        env=build_minimal_env(),
        limits=limits,
    )

    assert outcome.exit_code == 1
    assert not outcome.timed_out


@pytest.mark.asyncio
async def test_local_backend_times_out(tmp_path: Path) -> None:
    backend = LocalProcessExecutionBackend()
    limits = ResourceLimits(timeout_seconds=1, cpu_seconds=1, memory_mb=256, max_processes=32)

    outcome = await backend.run(
        ["python3", "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        env=build_minimal_env(),
        limits=limits,
    )

    assert outcome.timed_out is True
    assert outcome.exit_code is None


@pytest.mark.asyncio
async def test_local_backend_reports_missing_binary(tmp_path: Path) -> None:
    backend = LocalProcessExecutionBackend()
    limits = ResourceLimits(timeout_seconds=5, cpu_seconds=5, memory_mb=256, max_processes=32)

    outcome = await backend.run(
        ["definitely-not-a-real-binary-xyz"],
        cwd=tmp_path,
        env=build_minimal_env(),
        limits=limits,
    )

    assert outcome.error == "tool_not_available"
    assert outcome.exit_code is None


def test_container_backend_never_mounts_docker_socket(tmp_path: Path) -> None:
    backend = ContainerExecutionBackend()
    limits = ResourceLimits(timeout_seconds=60, cpu_seconds=60, memory_mb=512, max_processes=32, cpu_cores=1.0)

    argv = backend.build_docker_argv(
        image="protecto-scanner-ruff:0.15.21",
        command=["ruff", "check", "."],
        workspace_path=tmp_path / "workspace",
        output_path=tmp_path / "output",
        limits=limits,
        env=build_minimal_env(),
    )

    joined = " ".join(argv)
    assert "docker.sock" not in joined
    assert "/var/run/docker.sock" not in joined


def test_container_backend_disables_privileged_mode_and_drops_capabilities(tmp_path: Path) -> None:
    backend = ContainerExecutionBackend()
    limits = ResourceLimits(timeout_seconds=60, cpu_seconds=60, memory_mb=512, max_processes=32, cpu_cores=1.0)

    argv = backend.build_docker_argv(
        image="protecto-scanner-bandit:1.9.4",
        command=["bandit", "-f", "json", "-r", "."],
        workspace_path=tmp_path / "workspace",
        output_path=tmp_path / "output",
        limits=limits,
        env=build_minimal_env(),
    )

    assert "--privileged" not in argv
    assert "--cap-drop" in argv
    assert "ALL" in argv
    assert "--security-opt" in argv
    assert "no-new-privileges" in argv


def test_container_backend_mounts_workspace_read_only_and_isolates_output(tmp_path: Path) -> None:
    backend = ContainerExecutionBackend()
    limits = ResourceLimits(timeout_seconds=60, cpu_seconds=60, memory_mb=512, max_processes=32, cpu_cores=1.0)
    workspace_path = tmp_path / "workspace"
    output_path = tmp_path / "output"

    argv = backend.build_docker_argv(
        image="protecto-scanner-gitleaks:8.30.1",
        command=["gitleaks", "detect"],
        workspace_path=workspace_path,
        output_path=output_path,
        limits=limits,
        env=build_minimal_env(),
    )

    assert f"{workspace_path}:/workspace:ro" in argv
    assert f"{output_path}:/output:rw" in argv


def test_container_backend_applies_resource_limits(tmp_path: Path) -> None:
    backend = ContainerExecutionBackend()
    limits = ResourceLimits(timeout_seconds=60, cpu_seconds=60, memory_mb=384, max_processes=48, cpu_cores=2.0)

    argv = backend.build_docker_argv(
        image="protecto-scanner-semgrep:1.169.0",
        command=["semgrep", "--config", "rules.yaml"],
        workspace_path=tmp_path / "workspace",
        output_path=tmp_path / "output",
        limits=limits,
        env=build_minimal_env(),
    )

    assert "--memory" in argv
    assert "384m" in argv
    assert "--pids-limit" in argv
    assert "48" in argv
    assert "--cpus" in argv
    assert "2.0" in argv
    assert "--network" in argv
    assert "none" in argv


def test_container_backend_env_never_contains_platform_secrets(tmp_path: Path) -> None:
    backend = ContainerExecutionBackend()
    limits = ResourceLimits(timeout_seconds=60, cpu_seconds=60, memory_mb=512, max_processes=32)

    with patch.dict(os.environ, _FAKE_SECRETS):
        argv = backend.build_docker_argv(
            image="protecto-scanner-pyright:1.1.411",
            command=["pyright", "--outputjson", "."],
            workspace_path=tmp_path / "workspace",
            output_path=tmp_path / "output",
            limits=limits,
            env=build_minimal_env(),
        )

    joined = " ".join(argv)
    for value in _FAKE_SECRETS.values():
        assert value not in joined
