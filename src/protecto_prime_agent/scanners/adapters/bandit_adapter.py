from __future__ import annotations

import json
from pathlib import Path

from ...enums import FindingCategory, Severity
from ..interface import NormalizedFinding, ScannerAdapter, ScanRequest
from ..normalization import REDACTED, compute_fingerprint, sanitize_text, to_relative_path

# bandit's "hardcoded secret" checks echo the literal secret value in both issue_text
# and the code snippet. These are redacted unconditionally -- generic pattern-based
# sanitize_text() cannot catch an arbitrary literal like `password = "hunter2"`.
_HARDCODED_SECRET_TEST_IDS = frozenset({"B105", "B106", "B107", "B108"})


class BanditAdapter(ScannerAdapter):
    """Python security linter (https://bandit.readthedocs.io/)."""

    name = "bandit"
    category_default = FindingCategory.SECURITY.value
    success_exit_codes = frozenset({0, 1})

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        return [
            binary_path,
            "-f",
            "json",
            "-r",
            "--exclude",
            ".git,.venv,venv,node_modules,__pycache__",
            ".",
        ]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        text = raw_output.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed_bandit_output: {exc}") from exc
        if not isinstance(data, dict) or "results" not in data:
            raise ValueError("malformed_bandit_output: expected a 'results' key")

        findings: list[NormalizedFinding] = []
        for item in data["results"]:
            if not isinstance(item, dict):
                continue
            test_id = str(item.get("test_id") or "unknown")
            is_secret_rule = test_id in _HARDCODED_SECRET_TEST_IDS

            message = (
                f"Possible hardcoded secret detected ({test_id})."
                if is_secret_rule
                else sanitize_text(str(item.get("issue_text", "")))
            )
            file_path = to_relative_path(item.get("filename"), request.workspace_path)
            line_number = item.get("line_number")
            column_number = item.get("col_offset")
            severity = str(item.get("issue_severity", "low")).lower()
            confidence = str(item.get("issue_confidence", "low")).lower()
            if severity not in {s.value for s in Severity}:
                severity = Severity.LOW.value

            sanitized_item = dict(item)
            if is_secret_rule:
                sanitized_item["code"] = REDACTED
                sanitized_item["issue_text"] = message
            raw_details_json = sanitize_text(json.dumps(sanitized_item, default=str))

            fingerprint = compute_fingerprint("bandit", test_id, file_path, line_number, message)
            findings.append(
                NormalizedFinding(
                    scanner_name="bandit",
                    rule_id=test_id,
                    severity=severity,
                    category=FindingCategory.SECURITY.value,
                    confidence=confidence,
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
