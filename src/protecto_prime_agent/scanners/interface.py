from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..enums import ScannerExecutionStatus


@dataclass(slots=True)
class ScanRequest:
    """Input to a scanner run: a Milestone 3 workspace checked out at a single commit.

    workspace_path must already point at a workspace whose working tree is the exact
    source commit (see RepositoryWorkspaceService.prepare_workspace). Scanners never
    receive the target commit or diff -- only the checked-out source tree.
    """

    workspace_path: Path
    commit_sha: str
    workflow_run_id: str
    repository_id: str
    enabled_scanners: tuple[str, ...] | None = None


@dataclass(slots=True)
class NormalizedFinding:
    """One finding translated from a scanner-specific result into the common schema."""

    scanner_name: str
    rule_id: str
    severity: str
    category: str
    confidence: str
    message: str
    file_path: str | None
    line_number: int | None
    column_number: int | None
    fingerprint: str
    commit_sha: str
    raw_details_json: str


@dataclass(slots=True)
class ScanResult:
    """Outcome of running a single scanner adapter."""

    scanner_name: str
    status: ScannerExecutionStatus
    findings: list[NormalizedFinding] = field(default_factory=list)
    exit_code: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    tool_version: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class AggregatedScanResult:
    """Aggregated outcome across every scanner enabled for a single scan request."""

    workflow_run_id: str
    commit_sha: str
    scan_results: list[ScanResult]
    started_at: datetime
    completed_at: datetime

    @property
    def findings(self) -> list[NormalizedFinding]:
        return [finding for result in self.scan_results for finding in result.findings]

    @property
    def has_failures(self) -> bool:
        return any(
            result.status in (ScannerExecutionStatus.FAILED, ScannerExecutionStatus.TIMEOUT)
            for result in self.scan_results
        )


class ScannerAdapter(ABC):
    """Translates between the provider-agnostic runtime contract and one specific tool.

    An adapter only knows how to build a command line for its tool and how to parse
    that tool's own output format into NormalizedFinding objects. It never executes
    repository code, never installs dependencies, and never decides on its own whether
    it is "enabled" -- that is the registry's and runner's job.
    """

    name: str
    category_default: str
    success_exit_codes: frozenset[int] = frozenset({0, 1})
    # True only for adapters whose function inherently requires network access (e.g.
    # pip-audit querying a vulnerability database). All other adapters run fully
    # offline; a production container backend should pass --network none for them.
    requires_network: bool = False

    def binary_name(self) -> str:
        """The executable name to locate on PATH. Override if it differs from `name`."""
        return self.name

    def version_args(self) -> list[str]:
        """Args (excluding the binary path) used to print the tool's version."""
        return ["--version"]

    def should_run(self, request: ScanRequest) -> bool:
        """Return False if there is nothing for this scanner to do for this request.

        E.g. pip-audit returns False when no dependency manifest is present. Default
        is always True.
        """
        return True

    @abstractmethod
    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        """Return the argv list to execute, rooted at request.workspace_path.

        output_dir is this scanner's isolated, per-run temporary output directory; use
        it for any tool-native report-file flag (see GitleaksAdapter).
        """
        raise NotImplementedError

    def read_output(self, stdout: str, output_dir: Path) -> str:
        """Return the raw text to hand to parse_output.

        Defaults to the captured stdout. Override for tools that write their report to
        a file (in output_dir) instead of stdout.
        """
        return stdout

    @abstractmethod
    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        """Parse this tool's output into normalized findings. Raise ValueError on malformed output."""
        raise NotImplementedError
