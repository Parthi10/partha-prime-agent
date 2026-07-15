from __future__ import annotations

from collections.abc import Iterable

from .config import ScannerRuntimeConfig
from .interface import ScannerAdapter


class ScannerRegistry:
    """Holds every known scanner adapter and resolves which ones are enabled.

    Registration is independent of enablement: an adapter can be registered (known
    to the runtime) without being enabled (selected to actually run). This keeps the
    registry provider-agnostic -- it has no notion of ruff/bandit/etc. beyond whatever
    adapters are registered with it.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ScannerAdapter] = {}

    def register(self, adapter: ScannerAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> ScannerAdapter | None:
        return self._adapters.get(name)

    def all(self) -> list[ScannerAdapter]:
        return list(self._adapters.values())

    def names(self) -> list[str]:
        return list(self._adapters.keys())

    def resolve_enabled(self, requested: Iterable[str] | None) -> list[ScannerAdapter]:
        """Return registered adapters matching `requested` names, in registration order.

        Unknown names are silently ignored (they are not registered scanners, so there
        is nothing to run or skip); the runner records SKIPPED only for names that ARE
        registered but excluded from `requested`.
        """
        if requested is None:
            return self.all()
        requested_set = set(requested)
        return [adapter for adapter in self._adapters.values() if adapter.name in requested_set]


def build_default_registry() -> ScannerRegistry:
    """Register all six built-in scanner adapters (regardless of enablement)."""
    from .adapters.bandit_adapter import BanditAdapter
    from .adapters.gitleaks_adapter import GitleaksAdapter
    from .adapters.pip_audit_adapter import PipAuditAdapter
    from .adapters.pyright_adapter import PyrightAdapter
    from .adapters.ruff_adapter import RuffAdapter
    from .adapters.semgrep_adapter import SemgrepAdapter

    registry = ScannerRegistry()
    for adapter in (
        RuffAdapter(),
        BanditAdapter(),
        SemgrepAdapter(),
        PyrightAdapter(),
        GitleaksAdapter(),
        PipAuditAdapter(),
    ):
        registry.register(adapter)
    return registry


__all__ = ["ScannerRegistry", "ScannerRuntimeConfig", "build_default_registry"]
