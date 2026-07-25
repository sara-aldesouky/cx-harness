# Stage 10.6 — Knowledge & FAQ Read Capabilities

## Business model

```text
KnowledgeArticle 1 → many KnowledgeArticleVersion
```

`KnowledgeArticle` owns the stable slug, category, language, and active state.
`KnowledgeArticleVersion` preserves revisions and publication timestamps. Only
active articles with published versions cross the repository boundary; drafts
and inactive content remain inaccessible.

## Repository and versioning

`KnowledgeRepository` provides latest published lookup, keyword search, and
same-category related-article discovery. Latest revision selection is
deterministic. No customer identity is needed because this is shared approved
company knowledge.

## Runtime tools

- `search_knowledge`
- `get_policy`
- `get_faq_answer`
- `list_related_articles`

Every successful answer includes its article slug, title, category, language,
version, and last-updated timestamp. Expected failures use
`article_not_found`, `policy_not_found`, `faq_not_found`, or
`knowledge_unavailable` through the existing `ToolResult` contract.

## Grounding

Knowledge tools declare only `KNOWLEDGE`. This is policy evidence: it can prove
general rules such as “refunds normally take three to five business days,” but
it cannot prove customer state such as “your refund was approved.” Customer
state requires successful Customer, Order, Delivery, Payment, or Refund tools.

The declarative classifier distinguishes general policy phrasing from factual
status phrasing. A mixed request requires both knowledge and transactional
evidence. No tool-name mapping, provider behavior, or orchestration change is
required.

## Controlled development seed

`python -m scripts.seed_knowledge_data` installs deterministic local/demo data:
15 approved English articles, refund-policy versions 1.0 and 2.0, one inactive
example, and one unpublished example. Stable UUIDs, slugs, versions, and UTC
publication timestamps make demonstrations repeatable. The command skips when
knowledge data already exists and performs all inserts in one transaction.

The inactive and unpublished examples intentionally verify that the repository
publication boundary hides them. This seed is not a production authoring or
publishing workflow.

## Scope

This stage does not author, publish, update, or delete knowledge. It adds no CMS,
provider behavior, authentication, API route, or Stage 9 orchestration change.
