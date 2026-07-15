from __future__ import annotations

from enum import Enum


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    QUEUED = "queued"


class MergeDecision(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class WorkspaceStatus(str, Enum):
    CREATED = "CREATED"
    CLONING = "CLONING"
    READY = "READY"
    FAILED = "FAILED"
    CLEANED = "CLEANED"


class ScannerExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    INCONCLUSIVE = "INCONCLUSIVE"
    SKIPPED = "SKIPPED"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingCategory(str, Enum):
    SECURITY = "security"
    QUALITY = "quality"
    TYPING = "typing"
    DEPENDENCY = "dependency"
    SECRET = "secret"
    STYLE = "style"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
