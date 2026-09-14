import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server settings
    HOST: str = Field(default="0.0.0.0", description="Server bind host")
    PORT: int = Field(default=8000, description="Server bind port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Central Auth Settings
    JWKS_URI: str = Field(
        default="https://t91cvjn5boilhilaixggt5y9.s0226.digitalsofts.com/.well-known/jwks.json",
        description="Central Auth JWKS endpoint"
    )
    MCP_AUTH_AUDIENCE: str = Field(
        default="digital-invoice-web",
        description="Expected audience for digital-invoice-web tokens"
    )
    REVOCATIONS_URI: Optional[str] = Field(
        default=None,
        description="Optional Central Auth revocation endpoint"
    )

    # Supabase Settings
    SUPABASE_URL: str = Field(
        default="",
        description="Supabase project URL"
    )
    SUPABASE_SERVICE_ROLE_KEY: str = Field(
        default="",
        description="Supabase service role key (bypasses RLS server-side)"
    )

    # Cryptography
    ENCRYPTION_MASTER_KEY: str = Field(
        default="",
        description="32-byte hex/base64 encoded master key for AES-256-GCM"
    )
    CURRENT_KEY_VERSION: int = Field(
        default=1,
        description="Current encryption key version for rotation"
    )

    # Browser Automation Settings
    PORTAL_BASE_URL: str = Field(
        default="https://www.digitalinvoicingsoftware.com",
        description="Base URL of Digital Invoicing portal"
    )
    HEADLESS: bool = Field(
        default=True,
        description="Run Chromium in headless mode"
    )
    MAX_CONCURRENT_BROWSERS: int = Field(
        default=3,
        description="Max concurrent Playwright contexts allowed"
    )
    NAVIGATION_TIMEOUT_MS: int = Field(
        default=20000,
        description="Playwright navigation timeout in milliseconds"
    )
    ACTION_TIMEOUT_MS: int = Field(
        default=15000,
        description="Playwright action timeout in milliseconds"
    )
    SESSION_TTL_HOURS: int = Field(
        default=24,
        description="Storage state cache expiry in hours"
    )

settings = Settings()
