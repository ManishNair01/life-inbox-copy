"""Startup configuration validation for local and deployable beta modes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import sys
from dotenv import load_dotenv

if "pytest" not in sys.modules and not os.getenv("PYTEST_CURRENT_TEST"):
    load_dotenv()


class ConfigError(RuntimeError):
    pass


EMAIL_PROVIDERS = frozenset({"console", "fake", "smtp", "off"})
DEV_ONLY_EMAIL_PROVIDERS = frozenset({"console", "fake"})
LOCAL_OTP_PEPPER = "local-only-otp-pepper-do-not-use-in-beta"


@dataclass(frozen=True)
class AppConfig:
    database_url: str
    upload_dir: str
    auth_mode: str  # password
    environment: str  # local | beta | production
    max_upload_mb: int
    timezone: str
    email_provider: str  # console | fake (smtp/resend later)
    otp_pepper: str
    nvidia_api_key: str
    nvidia_base_url: str
    nvidia_llm_model: str
    nvidia_asr_model: str

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


def load_config(*, strict: Optional[bool] = None) -> AppConfig:
    environment = os.getenv("LIFE_INBOX_ENV", "local").strip() or "local"
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite:///./data/life_inbox.db",
    ).strip()
    upload_dir = os.getenv("LIFE_INBOX_UPLOAD_DIR", "./data/uploads").strip()
    auth_mode = os.getenv("LIFE_INBOX_AUTH_MODE", "password").strip() or "password"
    timezone = os.getenv("LIFE_INBOX_TIMEZONE", "UTC").strip() or "UTC"
    max_upload_mb = int(os.getenv("LIFE_INBOX_MAX_UPLOAD_MB", "5") or "5")
    email_provider = (
        os.getenv("LIFE_INBOX_EMAIL_PROVIDER", "console").strip().lower()
        or "console"
    )
    otp_pepper = os.getenv("LIFE_INBOX_OTP_PEPPER", "").strip()
    nvidia_api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if nvidia_api_key and not nvidia_api_key.startswith("nvapi-") and not nvidia_api_key.startswith("Bearer "):
        nvidia_api_key = f"nvapi-{nvidia_api_key}"
    nvidia_base_url = (
        os.getenv("NVIDIA_BASE_URL", "").strip()
        or "https://integrate.api.nvidia.com/v1"
    )
    nvidia_llm_model = (
        os.getenv("NVIDIA_LLM_MODEL", "").strip()
        or "nvidia/nemotron-3.5-bolt-e4b"
    )
    nvidia_asr_model = (
        os.getenv("NVIDIA_ASR_MODEL", "").strip()
        or "openai/whisper-large-v3"
    )

    if strict is None:
        strict = environment in {"beta", "production"}

    errors: list[str] = []
    if not database_url:
        errors.append("DATABASE_URL is required.")
    if environment in {"beta", "production"} and database_url.startswith("sqlite"):
        errors.append(
            "PostgreSQL DATABASE_URL is required for beta/production "
            "(SQLite is local/dev only)."
        )
    if not upload_dir:
        errors.append("LIFE_INBOX_UPLOAD_DIR is required.")
    if auth_mode != "password":
        errors.append("LIFE_INBOX_AUTH_MODE must be 'password'.")
    if max_upload_mb < 1 or max_upload_mb > 50:
        errors.append("LIFE_INBOX_MAX_UPLOAD_MB must be between 1 and 50.")
    if email_provider not in EMAIL_PROVIDERS:
        errors.append(
            "LIFE_INBOX_EMAIL_PROVIDER must be one of: "
            + ", ".join(sorted(EMAIL_PROVIDERS))
        )
    if environment in {"beta", "production"}:
        if email_provider in DEV_ONLY_EMAIL_PROVIDERS:
            errors.append(
                "LIFE_INBOX_EMAIL_PROVIDER must be smtp (or off, private beta "
                "only) in beta/production; console/fake are local only."
            )
        if email_provider == "off" and environment == "production":
            errors.append("LIFE_INBOX_EMAIL_PROVIDER=off is for a private beta, not production.")
        if email_provider == "smtp":
            for name in ("LIFE_INBOX_SMTP_HOST", "LIFE_INBOX_SMTP_USER", "LIFE_INBOX_SMTP_PASSWORD"):
                if not os.getenv(name, "").strip():
                    errors.append(f"{name} is required when LIFE_INBOX_EMAIL_PROVIDER=smtp.")
        if len(otp_pepper) < 32:
            errors.append(
                "LIFE_INBOX_OTP_PEPPER must be at least 32 random characters "
                "in beta/production."
            )

    if errors and strict:
        raise ConfigError("; ".join(errors))

    if not otp_pepper:
        # Local-only fallback; strict environments must set a real secret.
        otp_pepper = LOCAL_OTP_PEPPER

    return AppConfig(
        database_url=database_url,
        upload_dir=upload_dir,
        auth_mode=auth_mode,
        environment=environment,
        max_upload_mb=max_upload_mb,
        timezone=timezone,
        email_provider=email_provider,
        otp_pepper=otp_pepper,
        nvidia_api_key=nvidia_api_key,
        nvidia_base_url=nvidia_base_url,
        nvidia_llm_model=nvidia_llm_model,
        nvidia_asr_model=nvidia_asr_model,
    )


def config_warnings(config: AppConfig) -> list[str]:
    warnings: list[str] = []
    if config.email_provider == "off":
        warnings.append(
            "Email is off: \"Forgot password\" is unavailable; reset passwords with "
            "python -m scripts.reset_password."
        )
    if not config.nvidia_api_key:
        warnings.append(
            "NVIDIA_API_KEY is not configured; running in deterministic fallback mode."
        )
    if config.is_sqlite and config.environment != "local":
        warnings.append("SQLite in use outside local environment.")
    if config.email_provider == "console":
        warnings.append("Email is printed to the server terminal (console mode).")
    if config.otp_pepper == LOCAL_OTP_PEPPER:
        warnings.append("Using the local-only OTP pepper.")
    return warnings
