from __future__ import annotations

import json
from pathlib import Path

from ...enums import Confidence, FindingCategory, Severity
from ..interface import NormalizedFinding, ScannerAdapter, ScanRequest
from ..normalization import compute_fingerprint, sanitize_text, to_relative_path

_RULESET_PATH = Path(__file__).resolve().parent.parent / "rulesets" / "semgrep_python.yaml"

_SEVERITY_MAP = {
    "ERROR": Severity.HIGH.value,
    "WARNING": Severity.MEDIUM.value,
    "INFO": Severity.INFO.value,
}


class SemgrepAdapter(ScannerAdapter):
    """Pattern-based static analysis scanner (https://semgrep.dev/), offline ruleset only.

    Uses a small, hand-authored, package-local ruleset (see scanners/rulesets/) instead
    of a registry config (`p/...`, `auto`) so no rules are ever fetched over the
    network during a scan.
    """

    name = "semgrep"
    category_default = FindingCategory.SECURITY.value
    success_exit_codes = frozenset({0, 1})

    def build_command(self, request: ScanRequest, binary_path: str, output_dir: Path) -> list[str]:
        return [
            binary_path,
            "--config",
            str(_RULESET_PATH),
            "--json",
            "--metrics=off",
            "--quiet",
            ".",
        ]

    def parse_output(self, raw_output: str, request: ScanRequest) -> list[NormalizedFinding]:
        text = raw_output.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed_semgrep_output: {exc}") from exc
        if not isinstance(data, dict) or "results" not in data:
            raise ValueError("malformed_semgrep_output: expected a 'results' key")

        findings: list[NormalizedFinding] = []
        for item in data["results"]:
            if not isinstance(item, dict):
                continue
            # semgrep prefixes check_id with a namespace derived from the config file's
            # path (e.g. an absolute-path install location turned into dotted
            # segments). Our own rule ids never contain dots, so the final segment is
            # always the stable, install-location-independent rule id.
            rule_id = str(item.get("check_id") or "unknown").rsplit(".", 1)[-1]
            extra = item.get("extra") or {}
            message = sanitize_text(str(extra.get("message", "")))
            file_path = to_relative_path(item.get("path"), request.workspace_path)
            start = item.get("start") or {}
            line_number = start.get("line")
            column_number = start.get("col")
            severity = _SEVERITY_MAP.get(str(extra.get("severity", "")).upper(), Severity.MEDIUM.value)
            raw_details_json = sanitize_text(json.dumps(item, default=str))
            fingerprint = compute_fingerprint("semgrep", rule_id, file_path, line_number, message)
            findings.append(
                NormalizedFinding(
                    scanner_name="semgrep",
                    rule_id=rule_id,
                    severity=severity,
                    category=FindingCategory.SECURITY.value,
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
