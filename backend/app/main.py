"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config.settings import settings
from app.database.repositories import RepositoryValidationError
from app.database.session import close_database_resources
from app.services.orchestration_runtime_gate import orchestration_runtime_gate
from app.schemas.common import APIErrorResponse
from app.api.dependencies import (
    get_customer_authenticator,
    get_model_invocation_mapper,
)
from app.authentication import AuthenticationError, AuthenticationFailureCode
from app.data_protection import (
    install_privacy_log_filters,
    remove_privacy_log_filters,
)
from app.security_audit import security_audit_recorder


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Open admission on startup and release runtime resources on shutdown."""

    orchestration_runtime_gate.start()
    privacy_filters = install_privacy_log_filters()
    audit_key = settings.security_audit_pseudonym_key
    if audit_key is None:
        security_audit_recorder.configuration_problem()
    else:
        try:
            security_audit_recorder.configure_key(audit_key.get_secret_value())
        except Exception:
            security_audit_recorder.configuration_problem()
    try:
        yield
    finally:
        orchestration_runtime_gate.begin_shutdown()
        get_model_invocation_mapper.cache_clear()
        get_customer_authenticator.cache_clear()
        close_database_resources()
        remove_privacy_log_filters(privacy_filters)


app = FastAPI(
    title="CX Harness",
    debug=settings.environment == "development",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Authorization", "Content-Type"],
)
app.include_router(api_router)


@app.get("/health", include_in_schema=False)
def health_check() -> dict[str, str]:
    """Return a dependency-free liveness response for the hosting platform."""

    return {"status": "ok", "service": "cx-harness-api"}


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(
    request: Request, exc: AuthenticationError
) -> JSONResponse:
    """Return stable failures without exposing credentials or verifier details."""

    status_code = (
        503
        if exc.code in {
            AuthenticationFailureCode.AUTHENTICATION_UNAVAILABLE,
            AuthenticationFailureCode.REPLAY_PROTECTION_UNAVAILABLE,
            AuthenticationFailureCode.SIGNING_KEY_UNAVAILABLE,
        }
        else 401
    )
    body = APIErrorResponse(code=exc.code.value, message=exc.public_message)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


@app.exception_handler(RepositoryValidationError)
async def repository_validation_error_handler(
    request: Request, exc: RepositoryValidationError
) -> JSONResponse:
    """Return safe client feedback for invalid repository filters."""

    return JSONResponse(status_code=422, content={"detail": str(exc)})
