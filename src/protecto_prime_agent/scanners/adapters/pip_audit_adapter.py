from __future__ import annotations

import json
from pathlib import Path

from ...enums import Confidence, FindingCategory, Severity
from ..interface import NormalizedFinding, ScannerAdapter, ScanRequest
from ..normalization import compute_fingerprint, sanitize_text, to_relative_path

_REQUIREMENTS_FILENAME = "requirements.txt"


class PipAuditAdapter(ScannerAdapter):
    """Dependency vulnerability scanner (https://pypi.org/project/pip-audit/).

    Audits a pinned requirements.txt against a vulnerability database by version
    metadata only -- it never installs the listed packages. This is the one adapter
    that requires network access (to query the vulnerability database); that is
    inherent to what the tool does, distinct from "downloading the scanning tool or
    its rules" at scan time.
    """

    name = "pip-audit"
    category_default = FindingCategory.DEPENDENCY.value
    success_exit_codes = frozenset({0, 1})
    requires_network = True

    def should_run(self, request: ScanRequest) -> bool:
        return (request.workspace_path / _REQUIREMENTS_FILENAME).exists()

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        requirements_path = request.workspace_path / _REQUIREMENTS_FILENAME
        return [
            binary_path,
            "-r",
            str(requirements_path),
            "-f",
            "json",
            "--progress-spinner=off",
        ]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        text = raw_output.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed_pip_audit_output: {exc}") from exc
        if not isinstance(data, dict) or "dependencies" not in data:
            raise ValueError("malformed_pip_audit_output: expected a 'dependencies' key")

        file_path = to_relative_path(str(request.workspace_path / _REQUIREMENTS_FILENAME), request.workspace_path)

        findings: list[NormalizedFinding] = []
        for dependency in data["dependencies"]:
            if not isinstance(dependency, dict):
                continue
            name = str(dependency.get("name") or "unknown")
            version = str(dependency.get("version") or "unknown")
            for vuln in dependency.get("vulns") or []:
                vuln_id = str(vuln.get("id") or "unknown-vuln")
                description = sanitize_text(str(vuln.get("description") or ""))[:400]
                message = f"{name} {version}: {description}"
                raw_details_json = sanitize_text(json.dumps({"name": name, "version": version, **vuln}, default=str))
                fingerprint = compute_fingerprint(
                    "pip-audit", vuln_id, file_path, None, f"{name}=={version}:{vuln_id}"
                )
                findings.append(
                    NormalizedFinding(
                        scanner_name="pip-audit",
                        rule_id=vuln_id,
                        severity=Severity.HIGH.value,
                        category=FindingCategory.DEPENDENCY.value,
                        confidence=Confidence.HIGH.value,
                        message=message,
                        file_path=file_path,
                        line_number=None,
                        column_number=None,
                        fingerprint=fingerprint,
                        commit_sha=request.commit_sha,
                        raw_details_json=raw_details_json,
                    )
                )
        return findings
