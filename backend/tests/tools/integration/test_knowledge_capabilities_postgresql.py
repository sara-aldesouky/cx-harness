"""PostgreSQL integration for approved knowledge capabilities."""

from datetime import datetime, timezone
import json
import pytest
from sqlalchemy import delete, func, select

import app.tools.knowledge_capabilities as capabilities
from app.database.models import KnowledgeArticle, KnowledgeArticleVersion
from app.tools.knowledge_capabilities import GetFaqAnswerTool, GetPolicyTool, KnowledgeLookupInput, KnowledgeSearchInput, ListRelatedArticlesTool, RelatedArticlesInput, SearchKnowledgeTool
from app.tools.result import ToolStatus
from tests.models.factories import create_knowledge_article, create_knowledge_version

pytestmark = pytest.mark.integration

@pytest.fixture
def knowledge_records(test_session_factory):
    with test_session_factory.begin() as session:
        policy = create_knowledge_article(session, slug="refund-policy", category="policy")
        create_knowledge_version(session, policy, version="1.0", content="Refunds take five business days.", published_at=datetime(2026, 7, 20, tzinfo=timezone.utc))
        latest = create_knowledge_version(session, policy, version="2.0", content="Refunds take three to five business days.", published_at=datetime(2026, 7, 25, tzinfo=timezone.utc))
        faq = create_knowledge_article(session, slug="delivery-hours", category="faq"); create_knowledge_version(session, faq, title="Delivery hours", content="Delivery is available from 8 AM to 10 PM.")
        related = create_knowledge_article(session, slug="missing-items", category="faq"); create_knowledge_version(session, related, title="Missing items", content="Report missing items through customer care.")
        inactive = create_knowledge_article(session, slug="old-policy", category="policy", is_active=False); create_knowledge_version(session, inactive, content="Hidden policy.")
        draft = create_knowledge_article(session, slug="draft-faq", category="faq"); create_knowledge_version(session, draft, is_published=False, content="Internal draft.")
        ids = (policy.id, faq.id, related.id, inactive.id, draft.id)
    try: yield latest
    finally:
        with test_session_factory.begin() as session: session.execute(delete(KnowledgeArticle).where(KnowledgeArticle.id.in_(ids)))

def counts(factory):
    with factory() as session: return tuple(session.scalar(select(func.count()).select_from(m)) or 0 for m in (KnowledgeArticle, KnowledgeArticleVersion))

def test_policy_faq_search_related_versioning_privacy_and_read_only(monkeypatch, test_session_factory, knowledge_records):
    monkeypatch.setattr(capabilities, "get_session_factory", lambda: test_session_factory); before = counts(test_session_factory)
    policy = GetPolicyTool().execute(None, KnowledgeLookupInput(slug="refund-policy")); faq = GetFaqAnswerTool().execute(None, KnowledgeLookupInput(slug="delivery-hours"))
    search = SearchKnowledgeTool().execute(None, KnowledgeSearchInput(query="Delivery")); related = ListRelatedArticlesTool().execute(None, RelatedArticlesInput(slug="delivery-hours"))
    assert all(r.status is ToolStatus.SUCCESS for r in (policy, faq, search, related))
    assert policy.data.source.version == "2.0" and policy.data.answer == knowledge_records.content
    assert faq.data.source.title == "Delivery hours" and related.data.total_returned == 1
    serialized = json.dumps(search.model_dump(mode="json"))
    for forbidden in ("author", "draft", "internal", '"id"'): assert forbidden not in serialized.lower()
    assert counts(test_session_factory) == before

@pytest.mark.parametrize(("tool", "input_model", "code"), [
    (GetPolicyTool(), KnowledgeLookupInput(slug="missing"), "policy_not_found"),
    (GetFaqAnswerTool(), KnowledgeLookupInput(slug="missing"), "faq_not_found"),
    (SearchKnowledgeTool(), KnowledgeSearchInput(query="unmatched phrase"), "knowledge_unavailable"),
    (ListRelatedArticlesTool(), RelatedArticlesInput(slug="missing"), "article_not_found"),
    (GetPolicyTool(), KnowledgeLookupInput(slug="old-policy"), "policy_not_found"),
    (GetFaqAnswerTool(), KnowledgeLookupInput(slug="draft-faq"), "faq_not_found"),
])
def test_failures_and_unpublished_content(monkeypatch, test_session_factory, knowledge_records, tool, input_model, code):
    monkeypatch.setattr(capabilities, "get_session_factory", lambda: test_session_factory)
    result = tool.execute(None, input_model)
    assert result.status is ToolStatus.FAILURE and result.error.error_code == code
