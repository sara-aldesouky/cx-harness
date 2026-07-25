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
from app.api.dependencies import get_model_invocation_mapper


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Open admission on startup and release runtime resources on shutdown."""

    orchestration_runtime_gate.start()
    try:
        yield
    finally:
        orchestration_runtime_gate.begin_shutdown()
        get_model_invocation_mapper.cache_clear()
        close_database_resources()


app = FastAPI(
    title="CX Harness",
    debug=settings.environment == "development",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Content-Type"],
)
app.include_router(api_router)


@app.exception_handler(RepositoryValidationError)
async def repository_validation_error_handler(
    request: Request, exc: RepositoryValidationError
) -> JSONResponse:
    """Return safe client feedback for invalid repository filters."""

    return JSONResponse(status_code=422, content={"detail": str(exc)})
