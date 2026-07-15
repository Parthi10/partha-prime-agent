from __future__ import annotations

from ..database import SessionLocal
from ..logging import log_contextual
from ..models import AuditLog


class AuditWriter:
    """Injectable sink for scanner lifecycle audit events.

    Mirrors RepositoryWorkspaceService's AuditWriter (Milestone 3): production code
    uses SqlAuditWriter; tests inject an in-memory recording writer so scanner tests
    never open a real database connection. Kept local to the scanners package so the
    scanner runtime has no dependency on the services package.
    """

    async def record(self, *, entity_type: str, entity_id: str, action: str, actor: str, metadata_json: str) -> None:
        raise NotImplementedError


class SqlAuditWriter(AuditWriter):
    """Writes audit events to the database. Never raises: failures are sanitized and logged."""

    async def record(self, *, entity_type: str, entity_id: str, action: str, actor: str, metadata_json: str) -> None:
        try:
            async with SessionLocal() as session:
                session.add(
                    AuditLog(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        action=action,
                        actor=actor,
                        metadata_json=metadata_json,
                    )
                )
                await session.commit()
        except Exception as exc:  # pragma: no cover - audit logging must never block scanning
            log_contextual("audit_write_failed", action=action, entity_type=entity_type, error_type=type(exc).__name__)
