"""Public Stage 14 provider-neutral model orchestration API."""

from app.model_orchestration.adapter import (
    ModelProviderAdapter,
    ModelProviderAdapterError,
    ProviderFailureCategory,
)
from app.model_orchestration.contracts import (
    AvailableModelTool,
    ModelExecutionMetadata,
    ModelFinishReason,
    ModelGenerationSettings,
    ModelMessage,
    ModelMessageRole,
    ModelOrchestrationRequest,
    ModelOrchestrationResponse,
    ModelProviderCapabilities,
    ModelResponseMetadata,
    NormalizedToolSelection,
)
from app.model_orchestration.fake import FakeModelProviderAdapter
from app.model_orchestration.orchestrator import (
    ModelOrchestrationError,
    ModelOrchestrator,
    ModelOrchestratorConfiguration,
)
from app.model_orchestration.registry import (
    DuplicateModelAdapterError,
    ModelAdapterNotFoundError,
    ModelAdapterRegistryError,
    ModelProviderAdapterRegistry,
)

__all__ = [
    "AvailableModelTool",
    "DuplicateModelAdapterError",
    "FakeModelProviderAdapter",
    "ModelAdapterNotFoundError",
    "ModelAdapterRegistryError",
    "ModelExecutionMetadata",
    "ModelFinishReason",
    "ModelGenerationSettings",
    "ModelMessage",
    "ModelMessageRole",
    "ModelOrchestrationError",
    "ModelOrchestrationRequest",
    "ModelOrchestrationResponse",
    "ModelOrchestrator",
    "ModelOrchestratorConfiguration",
    "ModelProviderAdapter",
    "ModelProviderAdapterError",
    "ModelProviderAdapterRegistry",
    "ModelProviderCapabilities",
    "ModelResponseMetadata",
    "NormalizedToolSelection",
    "ProviderFailureCategory",
]
