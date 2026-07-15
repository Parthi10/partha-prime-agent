from __future__ import annotations

from pathlib import Path

from protecto_prime_agent.scanners.normalization import (
    compute_fingerprint,
    sanitize_text,
    to_relative_path,
)


def test_sanitize_text_strips_url_credentials_and_tokens() -> None:
    text = (
        "fatal: unable to access 'https://user:s3cr3t@example.com/repo.git/': "
        "Authorization: Bearer abcdef123456 token=ghp_abcdefghijklmnopqrstuvwx "
        "aws=AKIAABCDEFGHIJKLMNOP"
    )
    redacted = sanitize_text(text)

    assert "s3cr3t" not in redacted
    assert "abcdef123456" not in redacted
    assert "ghp_abcdefghijklmnopqrstuvwx" not in redacted
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted
    assert "[REDACTED]" in redacted


def test_sanitize_text_passes_through_clean_text() -> None:
    text = "unused import 'os' at line 1"
    assert sanitize_text(text) == text


def test_sanitize_text_handles_empty_string() -> None:
    assert sanitize_text("") == ""


def test_fingerprint_is_stable_across_repeated_calls() -> None:
    args = ("ruff", "F401", "app.py", 12, "unused import")
    assert compute_fingerprint(*args) == compute_fingerprint(*args)


def test_fingerprint_differs_for_different_findings() -> None:
    base = compute_fingerprint("ruff", "F401", "app.py", 12, "unused import")
    different_rule = compute_fingerprint("ruff", "F402", "app.py", 12, "unused import")
    different_file = compute_fingerprint("ruff", "F401", "other.py", 12, "unused import")
    different_line = compute_fingerprint("ruff", "F401", "app.py", 13, "unused import")
    different_scanner = compute_fingerprint("bandit", "F401", "app.py", 12, "unused import")

    assert len({base, different_rule, different_file, different_line, different_scanner}) == 5


def test_fingerprint_is_commit_independent() -> None:
    # Fingerprint does not take commit_sha as input at all -- it is computed purely
    # from scanner/rule/location/message, so the same underlying issue keeps the same
    # fingerprint across commits (needed for future baseline comparison).
    fp = compute_fingerprint("ruff", "F401", "app.py", 12, "unused import")
    assert isinstance(fp, str)
    assert len(fp) == 64  # sha256 hex digest


def test_to_relative_path_converts_absolute_path_under_workspace() -> None:
    workspace = Path("/tmp/workspace-root")
    result = to_relative_path(str(workspace / "src" / "app.py"), workspace)
    assert result == "src/app.py"


def test_to_relative_path_leaves_relative_path_untouched() -> None:
    workspace = Path("/tmp/workspace-root")
    assert to_relative_path("src/app.py", workspace) == "src/app.py"


def test_to_relative_path_handles_none() -> None:
    workspace = Path("/tmp/workspace-root")
    assert to_relative_path(None, workspace) is None
