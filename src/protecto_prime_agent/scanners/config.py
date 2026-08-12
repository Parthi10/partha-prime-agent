from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from .execution import ResourceLimits


@dataclass(slots=True)
class ScannerRuntimeConfig:
    """Provider-agnostic scanner runtime configuration, sourced from Settings."""

    enabled_scanners: tuple[str, ...]
    output_root: Path
    limits: ResourceLimits
    tool_versions: dict[str, str]

    @classmethod
    def from_settings(cls, settings: Settings) -> ScannerRuntimeConfig:
        enabled = tuple(name.strip() for name in settings.scanners_enabled.split(",") if name.strip())
        return cls(
            enabled_scanners=enabled,
            output_root=Path(settings.scanner_output_root),
            limits=ResourceLimits(
                timeout_seconds=settings.scanner_timeout_seconds,
                cpu_seconds=settings.scanner_cpu_seconds,
                memory_mb=settings.scanner_memory_mb,
                max_processes=settings.scanner_max_processes,
            ),
            tool_versions={
                "ruff": settings.ruff_version,
                "bandit": settings.bandit_version,
                "semgrep": settings.semgrep_version,
                "pyright": settings.pyright_version,
                "gitleaks": settings.gitleaks_version,
                "pip-audit": settings.pip_audit_version,
            },
        )
