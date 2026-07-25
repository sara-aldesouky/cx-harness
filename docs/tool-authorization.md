# Tool Authorization

Stage 11.4 introduces exact-tool authorization without changing providers,
business tools, role capability policy, or resource ownership rules.

## Execution flow

1. **Authentication** establishes the trusted identity and role.
2. **Role Policy** determines whether that role may use the declared business
   capability.
3. **Tool Authorization** checks permission for the exact registered tool name
   and version.
4. **Ownership Authorization** verifies access to the requested customer-owned
   resource.
5. The business tool executes.

All four decisions are provider-independent. Business tools and providers have
no authorization code.

## Policy registry

`ToolPolicyRegistry` is an append-only in-memory registry. It distinguishes:

- tools known to the runtime;
- exact tool versions with an assigned `ToolPermission`;
- the immutable roles allowed to invoke each exact tool.

Runtime composition derives known identities from the existing `ToolRegistry`
and assigns policies centrally from immutable metadata. Authorization does not
contain scattered tool-name conditionals.

Current customer-facing business tools are approved for customers, customer
support agents, supervisors, and administrators. Stage 11.2 ownership checks
still restrict the resource being accessed. Unclassified system tools are
approved only for `internal_system`; that role cannot execute customer-facing
business tools.

## Failures

- `tool_not_permitted`: HTTP 403
- `unknown_tool`: HTTP 400
- `unknown_tool_policy`: HTTP 503
- `tool_authorization_unavailable`: HTTP 503

Messages do not reveal policy contents. A denied operation stops before input
rehydration, tool construction, invocation, repository access, or ToolCall
audit creation.

## Extensibility

New tools are registered through the existing runtime registry. The central
tool-policy composition assigns an exact versioned permission based on its
approved metadata classification. More granular exceptions can be introduced
in this one registry without modifying providers or business tools.
