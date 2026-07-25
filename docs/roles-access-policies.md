# Roles and Access Policies

Stage 11.3 adds a provider-independent role policy gate without changing the
authentication, ownership authorization, orchestration, provider, or business
tool implementations.

## Security boundaries

1. **Authentication** verifies who the caller is and creates an immutable
   trusted identity.
2. **Role policy** checks whether that trusted identity's role may use the
   capability declared by the selected tool.
3. **Ownership authorization** verifies whether the authenticated customer may
   access the requested transactional resource.
4. The tool executes only after both policy gates allow it.

Roles never come from model-generated tool arguments. The trusted identity
supplies the role and the application copies it into `ExecutionContext`.

## Supported roles

- `customer`: customer-facing read capabilities, still restricted to owned data.
- `customer_support_agent`: approved business read capabilities.
- `supervisor`: support read capabilities and a policy extension point for
  broader operational capabilities.
- `administrator`: all currently registered business read capabilities.
- `internal_system`: trusted service-to-service capability execution and
  unclassified system tools.

The current business tools are customer-scoped. Support, supervisor, and
administrator roles therefore do not bypass Stage 11.2 ownership rules. A
future operator workflow needs an explicit, trusted subject-customer context;
client arguments must never be used for impersonation.

## Declarative policy

`CapabilityRolePolicyService` owns an immutable role-to-capability mapping. It
evaluates `ToolMetadata.grounding_capabilities`, so no tool-name checks or
provider-specific rules exist. Business tools do not contain role logic.

Customer-facing Knowledge is allowed for every recognized role and remains
separate from transactional evidence. Tools with missing business capability
metadata fail closed. Only `internal_system` may invoke unclassified system
tools when the role gate is enabled.

## Failures

- `insufficient_role` and `unknown_role` map to HTTP 403.
- `policy_unavailable` and `policy_evaluation_failure` map to HTTP 503.

Responses contain stable codes and safe messages, never policy tables or
internal evaluation details. Denied operations do not execute tools or create
tool audit writes.

## Extensibility

Future roles are added centrally to `PrincipalRole` and the policy mapping.
Future business capabilities participate through existing tool metadata. No
business tool, provider, or orchestration change is required.
