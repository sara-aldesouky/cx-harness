"""FastAPI application entry point."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config.settings import settings
from app.database.repositories import RepositoryValidationError


app = FastAPI(title="CX Harness", debug=settings.environment == "development")
app.include_router(api_router)


@app.exception_handler(RepositoryValidationError)
async def repository_validation_error_handler(
    request: Request, exc: RepositoryValidationError
) -> JSONResponse:
    """Return safe client feedback for invalid repository filters."""

    return JSONResponse(status_code=422, content={"detail": str(exc)})
