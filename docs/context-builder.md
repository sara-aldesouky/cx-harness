# Context Builder

Stage 7.4 adds a stateless assembly boundary between trusted application inputs
and the immutable `ConversationContext` contract.

```text
System instructions + ordered messages + optional provider/model
                              |
                              v
                       ContextBuilder
                              |
                  defensive copy + validation
                              |
                              v
                    ConversationContext
```

The builder accepts existing `ConversationMessage` objects or mapping-shaped
message data. It copies and revalidates every message, preserves collection
order, and delegates normalization and structural validation to the Stage 7.3
contracts. It retains no state and never mutates caller-owned collections or
metadata.

It does not retrieve history, access a database, choose a provider, generate a
prompt, count tokens, truncate content, call tools, or invoke a model.
