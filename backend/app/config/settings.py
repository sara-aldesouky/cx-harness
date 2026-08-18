"""Environment-backed application settings."""

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Configuration loaded from environment variables or the local .env file."""

    database_url: str = ""
    active_model: str = "gemini"
    environment: str = "development"
    cors_allowed_origins: str = "http://localhost:3000"
    authentication_hmac_secret: Optional[SecretStr] = None
    security_audit_pseudonym_key: Optional[SecretStr] = None
    audit_payload_max_bytes: int = Field(default=16_384, gt=0)
    tool_call_retention_days: int = Field(default=90, gt=0)
    tool_call_stale_after_seconds: int = Field(default=300, gt=0)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model_name: str = "qwen3:8b"
    ollama_connect_timeout_seconds: float = Field(default=2.0, gt=0)
    ollama_read_timeout_seconds: float = Field(default=120.0, gt=0)
    ollama_context_size: int = Field(default=8_192, ge=4_096, le=131_072)
    ollama_max_output_tokens: int = Field(default=256, gt=0, le=8_192)
    ollama_keep_alive: str = "15m"
    ollama_tool_thinking_enabled: bool = False
    max_model_turns: int = Field(default=5, gt=0, le=100)
    max_user_message_chars: int = Field(default=16_384, gt=0, le=1_000_000)
    max_conversation_history: int = Field(default=100, ge=0, le=10_000)
    max_provider_messages: int = Field(default=128, gt=0, le=20_000)
    max_tools_exposed: int = Field(default=64, gt=0, le=1_000)
    max_tool_calls_per_turn: int = Field(default=16, gt=0, le=1_000)
    max_tool_argument_bytes: int = Field(default=16_384, gt=0, le=10_000_000)
    max_tool_result_bytes: int = Field(default=65_536, gt=0, le=50_000_000)
    max_provider_response_bytes: int = Field(
        default=1_048_576, gt=0, le=50_000_000
    )

    @property
    def allowed_cors_origins(self) -> tuple[str, ...]:
        """Return normalized explicit origins without allowing wildcards."""

        origins = tuple(
            item.strip().rstrip("/")
            for item in self.cors_allowed_origins.split(",")
            if item.strip()
        )
        if not origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one origin")
        for origin in origins:
            parsed = urlparse(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.params
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or origin == "*"
            ):
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS must contain explicit HTTP(S) origins"
                )
        return tuple(dict.fromkeys(origins))

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, value: str) -> str:
        """Fail at settings load for unsafe or malformed provider endpoints."""

        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("OLLAMA_BASE_URL must use HTTP or HTTPS")
        if parsed.username or parsed.password:
            raise ValueError("OLLAMA_BASE_URL must not contain credentials")
        if (parsed.hostname or "").lower() not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("OLLAMA_BASE_URL must target the local machine")
        return normalized

    @field_validator("ollama_model_name")
    @classmethod
    def validate_ollama_model_name(cls, value: str) -> str:
        """Require an explicit non-empty model identity at startup."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("OLLAMA_MODEL_NAME must not be empty")
        return normalized

    @field_validator("ollama_keep_alive")
    @classmethod
    def validate_ollama_keep_alive(cls, value: str) -> str:
        """Require one explicit Ollama duration without provider leakage."""

        normalized = value.strip().lower()
        if not normalized or len(normalized) > 32:
            raise ValueError("OLLAMA_KEEP_ALIVE must be a valid duration")
        if normalized in {"0", "-1"}:
            return normalized
        suffix = next(
            (item for item in ("ms", "s", "m", "h") if normalized.endswith(item)),
            None,
        )
        amount = normalized[: -len(suffix)] if suffix else ""
        if suffix is None or not amount.isdigit() or int(amount) <= 0:
            raise ValueError("OLLAMA_KEEP_ALIVE must be a valid duration")
        return normalized

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
