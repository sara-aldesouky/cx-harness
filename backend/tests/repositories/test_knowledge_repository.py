from datetime import datetime, timezone
from app.database.repositories import KnowledgeRepository
from tests.models.factories import create_knowledge_article, create_knowledge_version

def test_latest_published_version_excludes_drafts_and_inactive(db_session):
    article = create_knowledge_article(db_session, slug="refund-policy", category="policy")
    old = create_knowledge_version(db_session, article, version="1.0")
    create_knowledge_version(db_session, article, version="2.0", is_published=False, published_at=datetime(2026, 7, 26, tzinfo=timezone.utc))
    inactive = create_knowledge_article(db_session, slug="hidden", is_active=False); create_knowledge_version(db_session, inactive)
    repo = KnowledgeRepository(db_session)
    assert repo.get_latest("refund-policy", "en", "policy") is old
    assert repo.get_latest("hidden", "en") is None

def test_search_and_related_use_latest_approved_versions(db_session):
    source = create_knowledge_article(db_session, slug="delivery-hours", category="faq"); create_knowledge_version(db_session, source, content="Delivery hours are listed here.")
    related = create_knowledge_article(db_session, slug="delivery-window", category="faq"); latest = create_knowledge_version(db_session, related, content="Delivery window guidance.")
    repo = KnowledgeRepository(db_session)
    assert repo.search("Delivery", "en")
    assert repo.list_related("delivery-hours", "en") == [latest]
