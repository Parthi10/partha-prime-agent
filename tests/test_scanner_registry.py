from __future__ import annotations

from pathlib import Path

from protecto_prime_agent.scanners.interface import NormalizedFinding, ScannerAdapter, ScanRequest
from protecto_prime_agent.scanners.registry import ScannerRegistry, build_default_registry


class _StubAdapter(ScannerAdapter):
    def __init__(self, name: str) -> None:
        self.name = name
        self.category_default = "quality"

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        return [binary_path]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        return []


def test_register_and_get() -> None:
    registry = ScannerRegistry()
    adapter = _StubAdapter("stub-one")
    registry.register(adapter)

    assert registry.get("stub-one") is adapter
    assert registry.get("does-not-exist") is None


def test_names_and_all_reflect_registrations() -> None:
    registry = ScannerRegistry()
    registry.register(_StubAdapter("a"))
    registry.register(_StubAdapter("b"))

    assert registry.names() == ["a", "b"]
    assert [adapter.name for adapter in registry.all()] == ["a", "b"]


def test_resolve_enabled_returns_all_when_requested_is_none() -> None:
    registry = ScannerRegistry()
    registry.register(_StubAdapter("a"))
    registry.register(_StubAdapter("b"))

    resolved = registry.resolve_enabled(None)

    assert [adapter.name for adapter in resolved] == ["a", "b"]


def test_resolve_enabled_filters_to_requested_names() -> None:
    registry = ScannerRegistry()
    registry.register(_StubAdapter("a"))
    registry.register(_StubAdapter("b"))
    registry.register(_StubAdapter("c"))

    resolved = registry.resolve_enabled(["b"])

    assert [adapter.name for adapter in resolved] == ["b"]


def test_disabled_scanner_is_excluded_from_resolution() -> None:
    registry = ScannerRegistry()
    registry.register(_StubAdapter("ruff"))
    registry.register(_StubAdapter("bandit"))

    resolved = registry.resolve_enabled(["ruff"])

    assert "bandit" not in [adapter.name for adapter in resolved]


def test_resolve_enabled_ignores_unknown_requested_names() -> None:
    registry = ScannerRegistry()
    registry.register(_StubAdapter("a"))

    resolved = registry.resolve_enabled(["a", "not-a-real-scanner"])

    assert [adapter.name for adapter in resolved] == ["a"]


def test_build_default_registry_registers_all_six_adapters() -> None:
    registry = build_default_registry()

    assert set(registry.names()) == {"ruff", "bandit", "semgrep", "pyright", "gitleaks", "pip-audit"}
