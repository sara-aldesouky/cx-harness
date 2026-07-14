"""FastAPI application entry point."""

from fastapi import FastAPI

from app.config.settings import settings


app = FastAPI(title="CX Harness", debug=settings.environment == "development")
