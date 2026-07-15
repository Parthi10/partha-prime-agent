from __future__ import annotations

import hashlib
import re
from pathlib import Path

# Generic secret/credential shapes that might appear in scanner stdout, stderr, error
# text, or a finding's own message/context snippet (e.g. a bandit hardcoded-password
# finding echoing the literal value it flagged). Applied to everything the runtime
# stores, logs, or raises.
_URL_CREDENTIAL_RE = re.compile(r"(https?://)[^/\s@]+@")
_PREFIXED_SECRET_PATTERNS = [
    re.compile(r"(?i)(x-access-token:)\S+"),
    re.compile(r"(?i)(authorization:\s*(?:basic|bearer)\s+)\S+"),
]
_BARE_SECRET_PATTERNS = [
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bATBB[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
]

REDACTED = "[REDACTED]"


def sanitize_text(text: str) -> str:
    """Strip embedded credentials/tokens/keys from scanner stdout, stderr, and errors."""
    if not text:
        return text
    redacted = _URL_CREDENTIAL_RE.sub(rf"\1{REDACTED}@", text)
    for pattern in _PREFIXED_SECRET_PATTERNS:
        redacted = pattern.sub(rf"\1{REDACTED}", redacted)
    for pattern in _BARE_SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def compute_fingerprint(
    scanner_name: str,
    rule_id: str,
    file_path: str | None,
    line_number: int | None,
    message: str,
) -> str:
    """Stable, commit-independent identity for a finding.

    Deliberately excludes commit_sha so the same underlying issue keeps the same
    fingerprint across commits/runs (needed for future baseline comparison -- not
    implemented in this milestone). Two identical inputs always produce the same
    fingerprint; the fingerprint never changes between repeated runs of a scanner
    against unchanged input.
    """
    basis = "\x1f".join(
        [
            scanner_name,
            rule_id,
            file_path or "",
            str(line_number) if line_number is not None else "",
            message,
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def to_relative_path(raw_path: str | None, workspace_path: Path) -> str | None:
    """Normalize a scanner-reported path to be relative to the workspace root.

    Scanners report paths in whatever form they were given/resolved (absolute or
    relative); findings should never leak the host's absolute temp-directory layout.
    """
    if not raw_path:
        return raw_path
    candidate = Path(raw_path)
    try:
        if candidate.is_absolute():
            return str(candidate.resolve().relative_to(workspace_path.resolve()))
        return str(candidate)
    except ValueError:
        return str(candidate)
