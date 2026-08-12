from __future__ import annotations

import json
from pathlib import Path

from ...enums import Confidence, FindingCategory, Severity
from ..interface import NormalizedFinding, ScannerAdapter, ScanRequest
from ..normalization import compute_fingerprint, sanitize_text, to_relative_path


def _map_severity_category(code: str) -> tuple[str, str]:
    if code.startswith("S"):
        return Severity.HIGH.value, FindingCategory.SECURITY.value
    if code.startswith("F"):
        return Severity.MEDIUM.value, FindingCategory.QUALITY.value
    return Severity.LOW.value, FindingCategory.STYLE.value


class RuffAdapter(ScannerAdapter):
    """Python lint/style/security-lite scanner (https://docs.astral.sh/ruff/)."""

    name = "ruff"
    category_default = FindingCategory.STYLE.value
    success_exit_codes = frozenset({0, 1})

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        # --isolated ignores any ruff config the target repository ships, so scan
        # behavior is deterministic and not opt-out-able by the repository itself.
        return [
            binary_path,
            "check",
            "--isolated",
            "--select=E,F,W,S",
            "--output-format=json",
            ".",
        ]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        text = raw_output.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed_ruff_output: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("malformed_ruff_output: expected a JSON array")

        findings: list[NormalizedFinding] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "unknown")
            message = sanitize_text(str(item.get("message", "")))
            location = item.get("location") or {}
            file_path = to_relative_path(item.get("filename"), request.workspace_path)
            line_number = location.get("row")
            column_number = location.get("column")
            severity, category = _map_severity_category(code)
            raw_details_json = sanitize_text(json.dumps(item, default=str))
            fingerprint = compute_fingerprint("ruff", code, file_path, line_number, message)
            findings.append(
                NormalizedFinding(
                    scanner_name="ruff",
                    rule_id=code,
                    severity=severity,
                    category=category,
                    confidence=Confidence.MEDIUM.value,
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
