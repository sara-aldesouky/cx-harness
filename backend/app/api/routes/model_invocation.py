"""Thin HTTP transport for the existing model-pipeline application boundary."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.dependencies import (
    get_authenticated_customer_identity,
    get_model_invocation_mapper,
)
from app.api.model_invocation import ModelInvocationMapper
from app.authentication import TrustedCustomerIdentity
from app.authorization import AuthorizationError, AuthorizationFailureCode
from app.role_policy import RolePolicyError, RolePolicyFailureCode
from app.tool_authorization import (
    ToolAuthorizationFailureCode,
    ToolAuthorizationPolicyError,
)
from app.harness.model_pipeline import ModelRunPersistenceError
from app.harness.runtime import ModelPipelineStartupError
from app.harness.tool_loop_runtime import ModelToolLoopStartupError
from app.providers.ollama_qwen import (
    EmptyModelResponseError,
    InvalidOllamaResponseError,
    OllamaRequestTimeoutError,
    OllamaUnavailableError,
)
from app.schemas.common import APIErrorResponse
from app.schemas.model_invocation import (
    ModelInvocationRequest,
    ModelInvocationResponse,
)
from app.services.model_pipeline_service import ModelPipelineServiceInputError
from app.services.model_tool_loop_service import (
    ModelToolLoopApplicationError,
    ModelToolLoopTermination,
)


router = APIRouter(prefix="/model", tags=["Model Invocation"])


ERROR_RESPONSES = {
    401: {"model": APIErrorResponse, "description": "Authentication required"},
    403: {"model": APIErrorResponse, "description": "Access denied"},
    400: {"model": APIErrorResponse, "description": "Invalid application input"},
    500: {"model": APIErrorResponse, "description": "Internal invocation failure"},
    502: {"model": APIErrorResponse, "description": "Invalid model response"},
    503: {"model": APIErrorResponse, "description": "Model service unavailable"},
}


@router.post(
    "/invoke",
    response_model=ModelInvocationResponse,
    responses=ERROR_RESPONSES,
    summary="Invoke the configured customer-service model",
    description=(
        "Submit trusted conversation context and receive one model response."
    ),
)
def invoke_model(
    request: ModelInvocationRequest,
    identity: TrustedCustomerIdentity = Depends(
        get_authenticated_customer_identity
    ),
    mapper: ModelInvocationMapper = Depends(get_model_invocation_mapper),
):
    """Invoke the existing application boundary exactly once."""

    try:
        return mapper.invoke(request, identity)
    except AuthorizationError as error:
        if error.code in {
            AuthorizationFailureCode.RESOURCE_OWNERSHIP_MISMATCH,
            AuthorizationFailureCode.UNAUTHORIZED_RESOURCE,
            AuthorizationFailureCode.RESOURCE_NOT_FOUND,
        }:
            return _error(
                404,
                "resource_not_found",
                "The requested resource was not found.",
            )
        return _error(
            503
            if error.code is AuthorizationFailureCode.AUTHORIZATION_UNAVAILABLE
            else 403,
            error.code.value,
            error.public_message,
        )
    except RolePolicyError as error:
        return _error(
            503
            if error.code
            in {
                RolePolicyFailureCode.POLICY_UNAVAILABLE,
                RolePolicyFailureCode.POLICY_EVALUATION_FAILURE,
            }
            else 403,
            error.code.value,
            error.public_message,
        )
    except ToolAuthorizationPolicyError as error:
        if error.code is ToolAuthorizationFailureCode.UNKNOWN_TOOL:
            status_code = 400
        elif error.code is ToolAuthorizationFailureCode.TOOL_NOT_PERMITTED:
            status_code = 403
        else:
            status_code = 503
        return _error(
            status_code,
            error.code.value,
            error.public_message,
        )
    except (ModelPipelineServiceInputError, ValidationError):
        return _error(
            400,
            "invalid_application_input",
            "The model invocation input is invalid.",
        )
    except (ModelPipelineStartupError, ModelToolLoopStartupError):
        return _error(
            503,
            "model_service_unavailable",
            "The model service is temporarily unavailable.",
        )
    except (OllamaUnavailableError, OllamaRequestTimeoutError):
        return _error(
            503,
            "provider_unavailable",
            "The model provider is temporarily unavailable.",
        )
    except (InvalidOllamaResponseError, EmptyModelResponseError):
        return _error(
            502,
            "invalid_provider_response",
            "The model provider returned an invalid response.",
        )
    except ModelRunPersistenceError:
        return _error(
            500,
            "model_run_persistence_failed",
            "The model invocation could not be recorded.",
        )
    except ModelToolLoopApplicationError as error:
        if error.result.termination_reason in {
            ModelToolLoopTermination.PROVIDER_ERROR,
            ModelToolLoopTermination.TIMEOUT,
        }:
            return _error(
                503,
                "provider_unavailable",
                "The model provider is temporarily unavailable.",
            )
        if error.result.termination_reason is ModelToolLoopTermination.INVALID_TOOL_CALL:
            return _error(
                400,
                "invalid_tool_call",
                "The model requested an invalid tool call.",
            )
        return _error(
            500,
            "model_tool_loop_failed",
            "The model tool loop could not complete.",
        )
    except Exception:
        return _error(
            500,
            "internal_error",
            "The model invocation failed unexpectedly.",
        )


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    body = APIErrorResponse(code=code, message=message)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))
