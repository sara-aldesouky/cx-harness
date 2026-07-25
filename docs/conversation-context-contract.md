# Conversation Context Contract

Stage 7.3 defines immutable data shared by future context builders, prompt
managers, tool coordination, evaluation, and provider adapters. It does not
assemble or persist context.

`ConversationMessage` contains a provider-independent role, normalized text,
and optional deterministic string metadata. `ConversationContext` contains
normalized system instructions, an ordered non-empty tuple of messages, and an
optional provider/model selection. Provider and model identifiers must either
both be selected or both be absent.

Metadata uses sorted key/value tuples instead of mutable dictionaries. This
keeps nested data immutable and produces stable JSON independent of mapping
insertion order. The contracts forbid undeclared fields so provider-specific
payloads cannot leak into the shared harness boundary.

This stage intentionally excludes context retrieval, prompt generation,
history persistence, token counting, tools, streaming, and model APIs.
