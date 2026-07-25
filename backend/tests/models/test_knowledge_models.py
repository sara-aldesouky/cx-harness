import pytest
from sqlalchemy.exc import IntegrityError
from tests.models.factories import create_knowledge_article, create_knowledge_version

def test_article_version_relationship(db_session):
    article = create_knowledge_article(db_session); version = create_knowledge_version(db_session, article)
    assert version.article is article and version in article.versions

def test_invalid_category_rejected(db_session):
    with pytest.raises(IntegrityError): create_knowledge_article(db_session, category="internal")

def test_article_version_is_unique(db_session):
    article = create_knowledge_article(db_session); create_knowledge_version(db_session, article)
    with pytest.raises(IntegrityError): create_knowledge_version(db_session, article)
