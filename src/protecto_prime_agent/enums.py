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
