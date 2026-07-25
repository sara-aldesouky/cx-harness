"""Approved customer-facing knowledge articles with version history."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, false, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

KNOWLEDGE_CATEGORIES = ("policy", "faq", "orders", "delivery", "payment", "refund")


class KnowledgeArticle(Base):
    """Stable identity and classification for one approved knowledge topic."""

    __tablename__ = "knowledge_articles"
    __table_args__ = (
        UniqueConstraint("slug", "language", name="uq_knowledge_articles_slug_language"),
        CheckConstraint(f"category IN {KNOWLEDGE_CATEGORIES!r}", name="valid_knowledge_category"),
        Index("ix_knowledge_articles_category_active", "category", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    versions: Mapped[list[KnowledgeArticleVersion]] = relationship(back_populates="article", cascade="all, delete-orphan", passive_deletes=True)


class KnowledgeArticleVersion(Base):
    """One immutable revision; only published revisions are customer-readable."""

    __tablename__ = "knowledge_article_versions"
    __table_args__ = (
        UniqueConstraint("article_id", "version", name="uq_knowledge_article_versions_article_version"),
        Index("ix_knowledge_versions_article_published", "article_id", "is_published", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    article_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    article: Mapped[KnowledgeArticle] = relationship(back_populates="versions")
