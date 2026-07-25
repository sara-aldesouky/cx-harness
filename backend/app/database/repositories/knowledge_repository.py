"""Read-only access to active, published business knowledge."""

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.database.models import KnowledgeArticle, KnowledgeArticleVersion
from app.database.repositories._common import DEFAULT_LIMIT, validate_pagination


class KnowledgeRepository:
    """Enforce publication boundaries for all knowledge reads."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_latest(self, slug: str, language: str, category: Optional[str] = None) -> Optional[KnowledgeArticleVersion]:
        statement = select(KnowledgeArticleVersion).join(KnowledgeArticleVersion.article).where(KnowledgeArticle.slug == slug, KnowledgeArticle.language == language, KnowledgeArticle.is_active.is_(True), KnowledgeArticleVersion.is_published.is_(True))
        if category is not None:
            statement = statement.where(KnowledgeArticle.category == category)
        return self._session.scalar(statement.options(joinedload(KnowledgeArticleVersion.article)).order_by(KnowledgeArticleVersion.published_at.desc(), KnowledgeArticleVersion.version.desc()).limit(1))

    def search(self, query: str, language: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> list[KnowledgeArticleVersion]:
        validate_pagination(limit, offset)
        pattern = f"%{query}%"
        return list(self._session.scalars(select(KnowledgeArticleVersion).join(KnowledgeArticleVersion.article).where(KnowledgeArticle.language == language, KnowledgeArticle.is_active.is_(True), KnowledgeArticleVersion.is_published.is_(True), or_(KnowledgeArticleVersion.title.ilike(pattern), KnowledgeArticleVersion.content.ilike(pattern))).distinct(KnowledgeArticle.id).options(joinedload(KnowledgeArticleVersion.article)).order_by(KnowledgeArticle.id, KnowledgeArticleVersion.published_at.desc()).offset(offset).limit(limit)).all())

    def list_related(self, slug: str, language: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> list[KnowledgeArticleVersion]:
        validate_pagination(limit, offset)
        source = self._session.scalar(select(KnowledgeArticle).where(KnowledgeArticle.slug == slug, KnowledgeArticle.language == language, KnowledgeArticle.is_active.is_(True)))
        if source is None:
            return []
        return list(self._session.scalars(select(KnowledgeArticleVersion).join(KnowledgeArticleVersion.article).where(KnowledgeArticle.category == source.category, KnowledgeArticle.id != source.id, KnowledgeArticle.language == language, KnowledgeArticle.is_active.is_(True), KnowledgeArticleVersion.is_published.is_(True)).distinct(KnowledgeArticle.id).options(joinedload(KnowledgeArticleVersion.article)).order_by(KnowledgeArticle.id, KnowledgeArticleVersion.published_at.desc()).offset(offset).limit(limit)).all())
