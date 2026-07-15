from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Only what a scanner binary needs to run locally. Deliberately excludes everything
# else in the parent process environment -- in particular DATABASE_*, REDIS_*,
# *_WEBHOOK_SECRET, and any SCM access token, none of which a scanner subprocess
# should ever be able to read.
_SCANNER_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "PYTHONHASHSEED")


def build_minimal_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a minimal, explicit-allowlist environment for a scanner subprocess.

    This is the primary control satisfying "scanner containers/processes must not
    receive SCM/database/Redis/SMTP credentials, webhook secrets, or platform access
    tokens": rather than inheriting `os.environ` (which holds all of those), only a
    small, named set of variables needed for a tool binary to execute is copied over.
    """
    env = {key: os.environ[key] for key in _SCANNER_ENV_ALLOWLIST if key in os.environ}
    env.setdefault("LANG", "C.UTF-8")
    # Disable telemetry/network side effects some tools attempt by default.
    env["SEMGREP_SEND_METRICS"] = "off"
    if extra:
        env.update(extra)
    return env


@dataclass(slots=True)
class ResourceLimits:
    """Bounds applied to a single scanner execution."""

    timeout_seconds: int
    cpu_seconds: int
    memory_mb: int
    max_processes: int
    cpu_cores: float = 1.0


@dataclass(slots=True)
class ExecutionOutcome:
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    error: str | None = None


def _posix_resource_limiter(limits: ResourceLimits):
    """Return a preexec_fn applying a CPU-time limit.

    Runs in the forked child before exec, POSIX only. Deliberately applies only
    RLIMIT_CPU here, not RLIMIT_AS/RLIMIT_NPROC: empirically (verified against the
    real pyright and semgrep binaries, both of which wrap a Node.js/OCaml runtime and
    either reserve large virtual address ranges or fork helper processes) those two
    limits are unreliable for local-process execution -- RLIMIT_AS rejects normal
    virtual-memory reservations that are never actually resident, and RLIMIT_NPROC is
    a per-UID system-wide limit on most platforms (including macOS) rather than a
    per-process-tree one, so a modest value can spuriously break an unrelated tool.
    Memory and process-count are hard-enforced in production via
    ContainerExecutionBackend's docker `--memory`/`--pids-limit` flags, which use
    cgroup RSS/pids accounting rather than these POSIX ulimits and do not have this
    false-positive problem. A platform that rejects even RLIMIT_CPU is ignored rather
    than failing the scan, since the wall-clock timeout is the primary time bound.
    """

    def _apply() -> None:
        import resource

        try:
            resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        except (ValueError, OSError):
            pass

    return _apply


class ExecutionBackend(Protocol):
    async def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        limits: ResourceLimits,
    ) -> ExecutionOutcome: ...


class LocalProcessExecutionBackend:
    """Executes a scanner command as a local subprocess.

    Suitable for local development and tests. Applies POSIX resource limits and a
    wall-clock timeout, but provides no filesystem or network isolation of its own --
    use ContainerExecutionBackend for that in production.
    """

    async def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        limits: ResourceLimits,
    ) -> ExecutionOutcome:
        preexec_fn = _posix_resource_limiter(limits) if os.name == "posix" else None
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: subprocess.run(
                        command,
                        cwd=str(cwd),
                        capture_output=True,
                        text=True,
                        timeout=limits.timeout_seconds,
                        env=env,
                        shell=False,
                        check=False,
                        preexec_fn=preexec_fn,
                    )
                ),
                timeout=limits.timeout_seconds,
            )
        except (asyncio.TimeoutError, subprocess.TimeoutExpired):
            return ExecutionOutcome(stdout="", stderr="", exit_code=None, timed_out=True)
        except FileNotFoundError as exc:
            return ExecutionOutcome(stdout="", stderr=str(exc), exit_code=None, timed_out=False, error="tool_not_available")
        return ExecutionOutcome(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode, timed_out=False)


class ContainerExecutionBackend:
    """Builds (and can run) docker-isolated scanner invocations.

    Every constructed invocation:
      - never mounts the Docker socket (no `/var/run/docker.sock` bind, ever)
      - never sets `--privileged`
      - mounts the repository workspace read-only (`:ro`)
      - mounts a dedicated, isolated output directory read-write, and nothing else
        writable except a small noexec tmpfs for scratch space
      - disables container networking (`--network none`)
      - drops all Linux capabilities and disables privilege escalation
      - runs as a non-root, unprivileged user
      - enforces memory, CPU, and pids limits
      - passes only the minimal environment from build_minimal_env -- no ambient
        platform secrets

    Requires a pre-built, version-pinned image per scanner (e.g.
    `protecto-scanner-ruff:0.15.21`); building and publishing those images is out of
    scope for this milestone. This class defines the exact, security-reviewed
    invocation contract any such image must be run under.
    """

    def build_docker_argv(
        self,
        *,
        image: str,
        command: list[str],
        workspace_path: Path,
        output_path: Path,
        limits: ResourceLimits,
        env: dict[str, str],
    ) -> list[str]:
        argv = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--user",
            "65534:65534",
            "--pids-limit",
            str(limits.max_processes),
            "--memory",
            f"{limits.memory_mb}m",
            "--cpus",
            str(limits.cpu_cores),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=67108864",
        ]
        for key, value in env.items():
            argv += ["--env", f"{key}={value}"]
        argv += [
            "--volume",
            f"{workspace_path}:/workspace:ro",
            "--volume",
            f"{output_path}:/output:rw",
            "--workdir",
            "/workspace",
            image,
            *command,
        ]
        return argv

    async def run(
        self,
        *,
        image: str,
        command: list[str],
        workspace_path: Path,
        output_path: Path,
        limits: ResourceLimits,
        env: dict[str, str],
    ) -> ExecutionOutcome:
        argv = self.build_docker_argv(
            image=image,
            command=command,
            workspace_path=workspace_path,
            output_path=output_path,
            limits=limits,
            env=env,
        )
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: subprocess.run(
                        argv,
                        capture_output=True,
                        text=True,
                        timeout=limits.timeout_seconds,
                        shell=False,
                        check=False,
                    )
                ),
                timeout=limits.timeout_seconds,
            )
        except (asyncio.TimeoutError, subprocess.TimeoutExpired):
            return ExecutionOutcome(stdout="", stderr="", exit_code=None, timed_out=True)
        except FileNotFoundError as exc:
            return ExecutionOutcome(stdout="", stderr=str(exc), exit_code=None, timed_out=False, error="docker_not_available")
        return ExecutionOutcome(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode, timed_out=False)
