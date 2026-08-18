"""Thread-safe explicit registry for argument-binding policies."""

from __future__ import annotations

from threading import RLock

from app.argument_binding.policies import ToolBindingPolicy


class ArgumentBindingPolicyRegistryError(ValueError):
    pass


class DuplicateArgumentBindingPolicyError(ArgumentBindingPolicyRegistryError):
    pass


class ArgumentBindingPolicyNotFoundError(ArgumentBindingPolicyRegistryError):
    pass


class ArgumentBindingPolicyRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, ToolBindingPolicy] = {}
        self._lock = RLock()

    def register(self, policy: ToolBindingPolicy) -> None:
        if not isinstance(policy, ToolBindingPolicy):
            raise TypeError("policy must be a ToolBindingPolicy")
        with self._lock:
            if policy.tool_name in self._policies:
                raise DuplicateArgumentBindingPolicyError(
                    "argument binding policy is already registered"
                )
            self._policies[policy.tool_name] = policy.model_copy(deep=True)

    def get(self, tool_name: str) -> ToolBindingPolicy:
        normalized = self._normalize(tool_name)
        with self._lock:
            try:
                return self._policies[normalized].model_copy(deep=True)
            except KeyError as error:
                raise ArgumentBindingPolicyNotFoundError(
                    "argument binding policy was not found"
                ) from error

    def contains(self, tool_name: str) -> bool:
        normalized = self._normalize(tool_name)
        with self._lock:
            return normalized in self._policies

    def list_policies(self) -> tuple[ToolBindingPolicy, ...]:
        with self._lock:
            return tuple(
                self._policies[name].model_copy(deep=True)
                for name in sorted(self._policies)
            )

    @staticmethod
    def _normalize(tool_name: str) -> str:
        if not isinstance(tool_name, str):
            raise TypeError("tool_name must be a string")
        normalized = tool_name.strip()
        if not normalized:
            raise ValueError("tool_name must not be empty")
        return normalized


def build_write_argument_binding_policy_registry() -> ArgumentBindingPolicyRegistry:
    registry = ArgumentBindingPolicyRegistry()
    from app.argument_binding.policies import write_tool_binding_policies

    for policy in write_tool_binding_policies():
        registry.register(policy)
    return registry
