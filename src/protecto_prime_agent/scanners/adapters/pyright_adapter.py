from __future__ import annotations

import json
from pathlib import Path

from ...enums import Confidence, FindingCategory, Severity
from ..interface import NormalizedFinding, ScannerAdapter, ScanRequest
from ..normalization import compute_fingerprint, sanitize_text, to_relative_path

_SEVERITY_MAP = {
    "error": Severity.HIGH.value,
    "warning": Severity.MEDIUM.value,
    "information": Severity.INFO.value,
}


class PyrightAdapter(ScannerAdapter):
    """Static type checker for Python (https://microsoft.github.io/pyright/)."""

    name = "pyright"
    category_default = FindingCategory.TYPING.value
    success_exit_codes = frozenset({0, 1})

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        return [binary_path, "--outputjson", "."]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        text = raw_output.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed_pyright_output: {exc}") from exc
        if not isinstance(data, dict) or "generalDiagnostics" not in data:
            raise ValueError("malformed_pyright_output: expected a 'generalDiagnostics' key")

        findings: list[NormalizedFinding] = []
        for item in data["generalDiagnostics"]:
            if not isinstance(item, dict):
                continue
            rule_id = str(item.get("rule") or "pyright-general")
            message = sanitize_text(str(item.get("message", "")))
            file_path = to_relative_path(item.get("file"), request.workspace_path)
            rng = item.get("range") or {}
            start = rng.get("start") or {}
            line_number = start.get("line")
            column_number = start.get("character")
            severity = _SEVERITY_MAP.get(str(item.get("severity", "")).lower(), Severity.MEDIUM.value)
            raw_details_json = sanitize_text(json.dumps(item, default=str))
            fingerprint = compute_fingerprint("pyright", rule_id, file_path, line_number, message)
            findings.append(
                NormalizedFinding(
                    scanner_name="pyright",
                    rule_id=rule_id,
                    severity=severity,
                    category=FindingCategory.TYPING.value,
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
