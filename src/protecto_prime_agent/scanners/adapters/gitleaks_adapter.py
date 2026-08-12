from __future__ import annotations

import json
from pathlib import Path

from ...enums import Confidence, FindingCategory, Severity
from ..interface import NormalizedFinding, ScannerAdapter, ScanRequest
from ..normalization import REDACTED, compute_fingerprint, sanitize_text, to_relative_path

# gitleaks' own report includes the literal secret value under these keys. They must
# never be stored, logged, or returned verbatim -- that would just create a second,
# insecure copy of the very secret the scan is meant to flag.
_SECRET_VALUE_KEYS = ("Secret", "Match")


class GitleaksAdapter(ScannerAdapter):
    """Secret scanner (https://github.com/gitleaks/gitleaks). Uses its built-in ruleset."""

    name = "gitleaks"
    category_default = FindingCategory.SECRET.value
    success_exit_codes = frozenset({0, 1})

    def version_args(self) -> list[str]:
        return ["version"]

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        report_path = output_dir / "gitleaks-report.json"
        return [
            binary_path,
            "detect",
            "--source",
            ".",
            "--no-git",
            "-f",
            "json",
            "-r",
            str(report_path),
        ]

    def read_output(self, stdout: str, output_dir: Path) -> str:
        report_path = output_dir / "gitleaks-report.json"
        if report_path.exists():
            return report_path.read_text(encoding="utf-8")
        return stdout

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        text = raw_output.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed_gitleaks_output: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("malformed_gitleaks_output: expected a JSON array")

        findings: list[NormalizedFinding] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rule_id = str(item.get("RuleID") or "unknown-secret")
            description = str(item.get("Description") or "Potential secret detected")
            message = sanitize_text(f"{description} (rule: {rule_id}).")
            file_path = to_relative_path(item.get("File"), request.workspace_path)
            line_number = item.get("StartLine")
            column_number = item.get("StartColumn")

            sanitized_item = {key: value for key, value in item.items() if key not in _SECRET_VALUE_KEYS}
            for key in _SECRET_VALUE_KEYS:
                sanitized_item[key] = REDACTED
            raw_details_json = sanitize_text(json.dumps(sanitized_item, default=str))

            fingerprint = compute_fingerprint("gitleaks", rule_id, file_path, line_number, message)
            findings.append(
                NormalizedFinding(
                    scanner_name="gitleaks",
                    rule_id=rule_id,
                    severity=Severity.CRITICAL.value,
                    category=FindingCategory.SECRET.value,
                    confidence=Confidence.HIGH.value,
                    message=message,
                    file_path=file_path,
                    line_number=line_number,
                    column_number=column_number,
                    fingerprint=fingerprint,
                    commit_sha=request.commit_sha,
                    raw_details_json=raw_details_json,
                )
            )
        return findings
