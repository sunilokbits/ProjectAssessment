"""Persistence model.

The schema is deliberately domain-agnostic: domain knowledge is stored as
validated JSON inside immutable ``DomainPackVersion`` rows, and every
assessment-side record is keyed by string ids coming from packs. Adding a new
industry therefore never requires a schema migration (requirement 33).
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DomainPackStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    ARCHIVED = "archived"


class DomainPack(Base):
    """A domain (industry / technology / project type / global)."""

    __tablename__ = "domain_pack"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    source_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    versions: Mapped[list["DomainPackVersion"]] = relationship(
        back_populates="pack", cascade="all, delete-orphan", order_by="DomainPackVersion.id"
    )


class DomainPackVersion(Base):
    """Immutable once published. Assessments pin to a specific version row."""

    __tablename__ = "domain_pack_version"
    __table_args__ = (UniqueConstraint("pack_id", "version", name="uq_pack_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("domain_pack.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(40))
    status: Mapped[DomainPackStatus] = mapped_column(Enum(DomainPackStatus), default=DomainPackStatus.DRAFT)
    content: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(120), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    pack: Mapped[DomainPack] = relationship(back_populates="versions")
    status_events: Mapped[list["DomainPackStatusEvent"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="DomainPackStatusEvent.id"
    )


class DomainPackStatusEvent(Base):
    """Audit trail of DomainPackStatus transitions."""

    __tablename__ = "domain_pack_status_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("domain_pack_version.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(120), default="system")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    version: Mapped[DomainPackVersion] = relationship(back_populates="status_events")


class Assessment(Base):
    __tablename__ = "assessment"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_name: Mapped[str] = mapped_column(String(200))
    project_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(String(40), default="discovery")
    # classification_pending -> in_progress -> completed
    status: Mapped[str] = mapped_column(String(40), default="classification_pending")
    # Confirmed classification (geography, regulatory regions, project types, data classifications, ...)
    classification: Mapped[dict] = mapped_column(JSON, default=dict)
    classification_confirmed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    classification_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    mappings: Mapped[list["DomainAssessmentMapping"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    answers: Mapped[list["AssessmentAnswer"]] = relationship(back_populates="assessment", cascade="all, delete-orphan")
    items: Mapped[list["AssessmentItem"]] = relationship(back_populates="assessment", cascade="all, delete-orphan")
    documents: Mapped[list["AssessmentDocument"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class DomainAssessmentMapping(Base):
    """Which domain-pack *version* an assessment uses, and in what role."""

    __tablename__ = "domain_assessment_mapping"
    __table_args__ = (UniqueConstraint("assessment_id", "pack_id", name="uq_assessment_pack"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), index=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("domain_pack.id"))
    pack_version_id: Mapped[int] = mapped_column(ForeignKey("domain_pack_version.id"))
    # global | primary | secondary | technology | project_type
    role: Mapped[str] = mapped_column(String(30))
    sub_domains: Mapped[list] = mapped_column(JSON, default=list)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assessment: Mapped[Assessment] = relationship(back_populates="mappings")
    pack: Mapped[DomainPack] = relationship()
    pack_version: Mapped[DomainPackVersion] = relationship()


class DomainRuleSource(Base):
    """Provenance: which domain pack (version / sub-domain) contributed each rule."""

    __tablename__ = "domain_rule_source"
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), index=True)
    rule_type: Mapped[str] = mapped_column(String(40), index=True)  # question, risk, kpi, ...
    rule_key: Mapped[str] = mapped_column(String(200))
    origin: Mapped[str] = mapped_column(String(30))  # GLOBAL / INDUSTRY / SUB-DOMAIN / TECHNOLOGY / PROJECT / AI-DISCOVERED
    pack_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    pack_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sub_domain: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # included | duplicate | conflict | overridden
    status: Mapped[str] = mapped_column(String(30), default="included")
    merged_into: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssessmentAnswer(Base):
    __tablename__ = "assessment_answer"
    __table_args__ = (UniqueConstraint("assessment_id", "question_key", name="uq_answer"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), index=True)
    question_key: Mapped[str] = mapped_column(String(200))
    value: Mapped[object] = mapped_column(JSON, nullable=True)
    evidence: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    answered_by: Mapped[str] = mapped_column(String(120), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    assessment: Mapped[Assessment] = relationship(back_populates="answers")


class AssessmentItem(Base):
    """Generic per-assessment record keyed by kind + key.

    kinds: requirement, ai_question, kpi, compliance, conflict, risk, classification_suggestion
    Human review state (status/reviewer) lives here; AI never sets reviewed states.
    """

    __tablename__ = "assessment_item"
    __table_args__ = (UniqueConstraint("assessment_id", "kind", "key", name="uq_assessment_item"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(40), default="system")  # system | ai | human | domain_pack
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    assessment: Mapped[Assessment] = relationship(back_populates="items")


class AssessmentDocument(Base):
    __tablename__ = "assessment_document"
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    doc_type: Mapped[str] = mapped_column(String(40), default="other")  # rfp, rfi, brd, sow, architecture, requirements
    content_text: Mapped[str] = mapped_column(Text)
    uploaded_by: Mapped[str] = mapped_column(String(120), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assessment: Mapped[Assessment] = relationship(back_populates="documents")
