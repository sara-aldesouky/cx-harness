"""Controlled knowledge seed integration tests."""

import pytest
from sqlalchemy import delete, func, select

from app.database.models import KnowledgeArticle, KnowledgeArticleVersion
from app.database.repositories import KnowledgeRepository
from scripts.seed_knowledge_data import APPROVED_ARTICLES, seed

pytestmark = pytest.mark.integration


def test_seed_is_deterministic_filtered_versioned_and_idempotent(test_session_factory):
    with test_session_factory.begin() as session:
        session.execute(delete(KnowledgeArticleVersion))
        session.execute(delete(KnowledgeArticle))
        created = seed(session)
        session.flush()
        article_count = session.scalar(select(func.count()).select_from(KnowledgeArticle))
        version_count = session.scalar(select(func.count()).select_from(KnowledgeArticleVersion))
        latest = KnowledgeRepository(session).get_latest("refund-policy", "en", "policy")
        inactive = KnowledgeRepository(session).get_latest("inactive-example", "en")
        draft = KnowledgeRepository(session).get_latest("unpublished-example", "en")
        repeated = seed(session)

        assert created == (len(APPROVED_ARTICLES) + 2, len(APPROVED_ARTICLES) + 3)
        assert article_count == len(APPROVED_ARTICLES) + 2
        assert version_count == len(APPROVED_ARTICLES) + 3
        assert latest.version == "2.0"
        assert inactive is None and draft is None
        assert repeated == (0, 0)

    with test_session_factory.begin() as session:
        session.execute(delete(KnowledgeArticleVersion))
        session.execute(delete(KnowledgeArticle))
