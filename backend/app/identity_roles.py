"""Trusted, provider-independent principal role identities."""

from enum import Enum


class PrincipalRole(str, Enum):
    """Stable roles assigned only by trusted identity infrastructure."""

    CUSTOMER = "customer"
    CUSTOMER_SUPPORT_AGENT = "customer_support_agent"
    SUPERVISOR = "supervisor"
    ADMINISTRATOR = "administrator"
    INTERNAL_SYSTEM = "internal_system"
