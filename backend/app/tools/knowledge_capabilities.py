"""Provider-independent, read-only approved knowledge capabilities."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.repositories import KnowledgeRepository
from app.database.session import get_session_factory
from app.tools.contracts import BaseTool, GroundingCapability, ToolCategory, ToolMetadata
from app.tools.result import ToolError, ToolResult, ToolStatus


class KnowledgeLookupInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    slug: str
    language: str = "en"
    @field_validator("slug")
    @classmethod
    def slug_valid(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized): raise ValueError("slug is invalid")
        return normalized
    @field_validator("language")
    @classmethod
    def language_valid(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", normalized): raise ValueError("language is invalid")
        return normalized


class KnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    query: str = Field(min_length=2, max_length=200)
    language: str = "en"
    limit: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0)
    @field_validator("query")
    @classmethod
    def query_valid(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2: raise ValueError("query must contain at least two characters")
        return normalized
    @field_validator("language")
    @classmethod
    def language_valid(cls, value: str) -> str:
        return KnowledgeLookupInput(slug="validation", language=value).language


class RelatedArticlesInput(KnowledgeLookupInput):
    limit: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


class KnowledgeSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    slug: str
    title: str
    category: str
    language: str
    version: str
    last_updated: datetime


class KnowledgeAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    answer: str
    source: KnowledgeSource


class KnowledgeResults(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    articles: tuple[KnowledgeAnswer, ...]
    total_returned: int = Field(ge=0)


def _metadata(name: str, description: str, use_cases: tuple[str, ...]) -> ToolMetadata:
    return ToolMetadata(name=name, version="1.0.0", description=description, category=ToolCategory.POLICY, supported_use_cases=use_cases, grounding_capabilities=(GroundingCapability.KNOWLEDGE,), requires_customer_identity=False, requires_order_ownership=False, requires_policy_check=False, is_read_only=True)


class SearchKnowledgeTool(BaseTool[KnowledgeSearchInput, KnowledgeResults]):
    metadata = _metadata("search_knowledge", "Search approved customer-facing business knowledge.", ("knowledge_search", "policy_question", "faq_question"))
    input_schema, output_schema = KnowledgeSearchInput, KnowledgeResults
    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        with get_session_factory()() as session: versions = KnowledgeRepository(session).search(input_model.query, input_model.language, input_model.limit, input_model.offset)
        if not versions: return _failure("knowledge_unavailable", "No approved knowledge matched that question.")
        return _results(versions)


class GetPolicyTool(BaseTool[KnowledgeLookupInput, KnowledgeAnswer]):
    metadata = _metadata("get_policy", "Return the latest published version of an approved company policy.", ("policy_lookup",))
    input_schema, output_schema = KnowledgeLookupInput, KnowledgeAnswer
    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        return _lookup(input_model, "policy", "policy_not_found", "The requested policy is not available.")


class GetFaqAnswerTool(BaseTool[KnowledgeLookupInput, KnowledgeAnswer]):
    metadata = _metadata("get_faq_answer", "Return the latest published answer for an approved FAQ.", ("faq_lookup",))
    input_schema, output_schema = KnowledgeLookupInput, KnowledgeAnswer
    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        return _lookup(input_model, "faq", "faq_not_found", "The requested FAQ is not available.")


class ListRelatedArticlesTool(BaseTool[RelatedArticlesInput, KnowledgeResults]):
    metadata = _metadata("list_related_articles", "List approved articles related by business category.", ("related_knowledge",))
    input_schema, output_schema = RelatedArticlesInput, KnowledgeResults
    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        with get_session_factory()() as session: versions = KnowledgeRepository(session).list_related(input_model.slug, input_model.language, input_model.limit, input_model.offset)
        if not versions: return _failure("article_not_found", "No related approved articles are available.")
        return _results(versions)


def _lookup(input_model, category, code, message):  # type: ignore[no-untyped-def]
    with get_session_factory()() as session: version = KnowledgeRepository(session).get_latest(input_model.slug, input_model.language, category)
    if version is None: return _failure(code, message)
    return ToolResult[KnowledgeAnswer](status=ToolStatus.SUCCESS, data=_answer(version))


def _results(versions):  # type: ignore[no-untyped-def]
    items = tuple(_answer(version) for version in versions)
    return ToolResult[KnowledgeResults](status=ToolStatus.SUCCESS, data=KnowledgeResults(articles=items, total_returned=len(items)))


def _answer(version):  # type: ignore[no-untyped-def]
    return KnowledgeAnswer(answer=version.content, source=KnowledgeSource(slug=version.article.slug, title=version.title, category=version.article.category, language=version.article.language, version=version.version, last_updated=version.published_at))


def _failure(code, message):  # type: ignore[no-untyped-def]
    return ToolResult(status=ToolStatus.FAILURE, error=ToolError(error_code=code, public_message=message))
