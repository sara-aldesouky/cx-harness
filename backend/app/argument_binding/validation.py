"""Startup-only compatibility validation for neutral tool schema descriptors."""

from __future__ import annotations

from pydantic import field_validator, model_validator

from app.argument_binding.contracts import ArgumentSource, _BindingModel
from app.argument_binding.policies import ToolBindingPolicy
from app.argument_binding.registry import ArgumentBindingPolicyRegistry


class BindingStartupValidationError(ValueError):
    """Fail startup when tool schemas and binding policies are incompatible."""


class ToolSchemaArgument(_BindingModel):
    name: str
    required: bool
    protected: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("schema argument name must not be empty")
        return normalized


class RegisteredToolSchema(_BindingModel):
    tool_name: str
    arguments: tuple[ToolSchemaArgument, ...]
    executable: bool = True
    write_operation: bool = True

    @field_validator("tool_name")
    @classmethod
    def normalize_tool_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool_name must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_arguments(self) -> RegisteredToolSchema:
        names = tuple(argument.name for argument in self.arguments)
        if len(set(names)) != len(names):
            raise ValueError("tool schema arguments must be unique")
        return self


class PolicySchemaCompatibilityValidator:
    """Validate one policy against a neutral startup schema descriptor."""

    _TRUSTED_SIDEBAND_ARGUMENTS = frozenset({"customer_id", "conversation_id"})

    def validate(
        self, policy: ToolBindingPolicy, schema: RegisteredToolSchema
    ) -> None:
        if not isinstance(policy, ToolBindingPolicy):
            raise TypeError("policy must be a ToolBindingPolicy")
        if not isinstance(schema, RegisteredToolSchema):
            raise TypeError("schema must be a RegisteredToolSchema")
        if policy.tool_name != schema.tool_name:
            raise BindingStartupValidationError("policy and tool names do not match")
        policy_by_name = {item.argument_name: item for item in policy.argument_policies}
        schema_by_name = {item.name: item for item in schema.arguments}
        for name, requirement in policy_by_name.items():
            if requirement.include_in_tool_arguments:
                if name not in schema_by_name:
                    raise BindingStartupValidationError(
                        "policy inserts an argument absent from the tool schema"
                    )
                if requirement.protected != schema_by_name[name].protected:
                    raise BindingStartupValidationError(
                        "protected argument classification does not match schema"
                    )
            elif not (
                name in self._TRUSTED_SIDEBAND_ARGUMENTS
                and requirement.protected
                and requirement.permitted_sources == (ArgumentSource.EXECUTION_CONTEXT,)
            ):
                raise BindingStartupValidationError("policy contains an orphan argument")
        for name, argument in schema_by_name.items():
            requirement = policy_by_name.get(name)
            if argument.required and (
                requirement is None or not requirement.required
            ):
                raise BindingStartupValidationError(
                    "required schema argument is not represented by policy"
                )


class RegistryCompletenessValidator:
    """Optionally validate full write-tool policy coverage during startup."""

    def __init__(
        self,
        compatibility_validator: PolicySchemaCompatibilityValidator = (
            PolicySchemaCompatibilityValidator()
        ),
    ) -> None:
        if not isinstance(
            compatibility_validator, PolicySchemaCompatibilityValidator
        ):
            raise TypeError(
                "compatibility_validator must be a PolicySchemaCompatibilityValidator"
            )
        self._compatibility = compatibility_validator

    def validate(
        self,
        registry: ArgumentBindingPolicyRegistry,
        schemas: tuple[RegisteredToolSchema, ...],
    ) -> None:
        if not isinstance(registry, ArgumentBindingPolicyRegistry):
            raise TypeError("registry must be an ArgumentBindingPolicyRegistry")
        if not isinstance(schemas, tuple) or any(
            not isinstance(schema, RegisteredToolSchema) for schema in schemas
        ):
            raise TypeError("schemas must be a tuple of RegisteredToolSchema values")
        schema_names = tuple(schema.tool_name for schema in schemas)
        if len(set(schema_names)) != len(schema_names):
            raise BindingStartupValidationError("registered tool schemas are duplicated")
        executable_writes = {
            schema.tool_name
            for schema in schemas
            if schema.executable and schema.write_operation
        }
        policy_names = {policy.tool_name for policy in registry.list_policies()}
        if executable_writes - policy_names:
            raise BindingStartupValidationError("an executable write tool is missing a policy")
        if policy_names - executable_writes:
            raise BindingStartupValidationError("an orphan binding policy is registered")
        by_name = {schema.tool_name: schema for schema in schemas}
        for policy in registry.list_policies():
            self._compatibility.validate(policy, by_name[policy.tool_name])
