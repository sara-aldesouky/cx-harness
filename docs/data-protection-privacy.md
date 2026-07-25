# Data Protection and Privacy

Stage 11.5 adds provider-independent privacy controls around the existing
security and business layers. Trusted values used internally for identity,
ownership, and repository lookup remain unchanged; only boundary projections
are masked or redacted.

## Privacy lifecycle

1. Authentication establishes trusted identity.
2. Role, exact-tool, and ownership policies authorize execution.
3. Conversation input is copied and sanitized before provider invocation.
4. Business tools execute against trusted internal context.
5. Tool results are minimized and protected before provider continuation.
6. Model output is sanitized before the application/API response.
7. Audit payloads use stronger full redaction and size limits.
8. Application logging handlers sanitize rendered messages during the FastAPI
   application lifespan.

Business tools and providers contain no privacy logic.

## Protected information

- Customer names
- Email addresses
- Phone numbers
- Delivery and billing addresses
- Customer, conversation, and session identifiers
- Payment and processor identifiers
- Authentication tokens, passwords, API keys, card numbers, and security codes

Customer-facing order numbers remain available because they are required for
order reasoning and are not internal customer identifiers.

## Strategy

`PrivacyRules` is immutable and centrally classifies protected fields.
`DataProtectionService` recursively protects structured values and masks common
PII in unstructured text. Default examples include:

- `John Smith` → `J*** S****`
- `john@email.com` → `j***@email.com`
- `+201234567890` → `+20********90`
- addresses → `[REDACTED ADDRESS]`
- internal and payment identifiers → `[REDACTED]`

Audit storage uses full redaction rather than partial masking. The original
caller-owned message collection and trusted `ExecutionContext` are never
mutated.

## Data minimization

Stage 10 tools already expose customer-safe projections rather than ORM rows.
The privacy boundary adds defense in depth before tool output reaches a model.
Unneeded protected fields are redacted while operational fields such as order
status, timestamps, totals, and customer-facing order numbers remain usable.

## Logs and errors

FastAPI lifespan installs privacy filters on configured logging handlers.
Secrets, common PII, and payment numbers are sanitized before emission. UUID
identifiers receive stable one-way pseudonyms so events remain correlatable
without revealing raw identifiers. Safe error utilities collapse SQL, database URL, and traceback-like
details into a generic public message. Existing API exception mappings continue
to return stable safe codes without raw exception representations.

## Extensibility

Additional protected fields are added through `PrivacyRules`; providers and
business tools do not change. Future deployments may supply environment-backed
rules or specialized jurisdictional policies at composition time.
