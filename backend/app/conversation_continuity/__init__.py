"""Public Stage 15.2 trusted entity-continuity API."""

from app.conversation_continuity.contracts import (
    TRUSTED_CONTINUITY_SCHEMA_VERSION,
    ContinuityAuditMetadata,
    ContinuityFailureCategory,
    ContinuityResolutionMethod,
    TrustedContinuityBindingContext,
    TrustedConversationEntityState,
    TrustedEntityReference,
    TrustedEntityStatus,
    TrustedEntityType,
)
from app.conversation_continuity.service import (
    TrustedContinuityError,
    TrustedContinuityStore,
    TrustedConversationEntityContinuityService,
)

__all__ = [
    "TRUSTED_CONTINUITY_SCHEMA_VERSION",
    "ContinuityAuditMetadata",
    "ContinuityFailureCategory",
    "ContinuityResolutionMethod",
    "TrustedContinuityBindingContext",
    "TrustedConversationEntityState",
    "TrustedContinuityError",
    "TrustedContinuityStore",
    "TrustedConversationEntityContinuityService",
    "TrustedEntityReference",
    "TrustedEntityStatus",
    "TrustedEntityType",
]
