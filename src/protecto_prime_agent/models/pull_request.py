from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .repository import Repository


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        Index("ix_pull_requests_repository_id", "repository_id"),
        Index("ix_pull_requests_provider_pr_id", "provider_pr_id"),
        Index("ix_pull_requests_source_commit_sha", "source_commit_sha"),
        Index("ix_pull_requests_target_commit_sha", "target_commit_sha"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("repositories.id"), nullable=False)
    provider_pr_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    source_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    source_commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    target_commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    merge_decision: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    repository: Mapped["Repository"] = relationship(back_populates="pull_requests")
