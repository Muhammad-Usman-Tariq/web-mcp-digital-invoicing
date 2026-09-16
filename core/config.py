import sys
import logging
from typing import Optional, List
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("digital-invoice-web.config")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server settings (safe universal defaults)
    HOST: str = Field(default="0.0.0.0", description="Server bind host")
    PORT: int = Field(default=8000, description="Server bind port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Central Auth Settings
    JWKS_URI: str = Field(
        default="https://t91cvjn5boilhilaixggt5y9.s0226.digitalsofts.com/.well-known/jwks.json",
        description="Central Auth JWKS endpoint"
    )
    MCP_AUTH_AUDIENCE: str = Field(
        description="Expected audience for this MCP server's tokens — must be pasted exactly from Central Auth registration. No default: server must fail to start if this is not set."
    )
    REVOCATIONS_URI: Optional[str] = Field(
        default=None,
        description="Optional Central Auth revocation endpoint"
    )
    MCP_AUTH_TOKEN: str = Field(
        default="",
        description="Shared MCP client authentication token / API key"
    )

    # Supabase Settings (No defaults: required)
    SUPABASE_URL: str = Field(
        description="Supabase project URL — must be pasted from Supabase settings. No default: server must fail to start if this is not set."
    )
    SUPABASE_SERVICE_ROLE_KEY: str = Field(
        description="Supabase service role key — must be pasted from Supabase settings. No default: server must fail to start if this is not set."
    )

    # Cryptography (No default: required)
    ENCRYPTION_MASTER_KEY: str = Field(
        description="32-byte hex/base64 master encryption key — generate via scripts/generate_master_key.py. No default: server must fail to start if this is not set."
    )
    CURRENT_KEY_VERSION: int = Field(
        default=1,
        description="Current encryption key version for rotation"
    )

    # Browser Automation Settings (safe defaults)
    PORTAL_BASE_URL: str = Field(
        default="https://www.digitalinvoicingsoftware.com",
        description="Base URL of Digital Invoicing portal"
    )
    HEADLESS: bool = Field(
        default=True,
        description="Run Chromium in headless mode"
    )
    SLOW_MO_MS: int = Field(
        default=500,
        description="Milliseconds to slow down each Playwright action by, only applied when HEADLESS=false. Useful for visually debugging login/automation flows."
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

def validate_critical_settings(s: Settings) -> List[str]:
    """
    Validate that security-critical settings are neither missing, empty, nor using obvious placeholder values.
    Returns a list of FATAL error messages.
    """
    errors: List[str] = []

    # Check MCP_AUTH_AUDIENCE
    if not s.MCP_AUTH_AUDIENCE or not s.MCP_AUTH_AUDIENCE.strip():
        errors.append(
            "FATAL: MCP_AUTH_AUDIENCE is not set. Copy .env.sample to .env and paste the exact audience value from the Central Auth admin panel before starting this server."
        )

    # Check MCP_AUTH_TOKEN
    if not s.MCP_AUTH_TOKEN or not s.MCP_AUTH_TOKEN.strip():
        errors.append(
            "FATAL: MCP_AUTH_TOKEN is not set. Copy .env.example to .env and paste the static token given by Central Auth during registration before starting this server."
        )
    elif s.MCP_AUTH_TOKEN == "your-mcp-auth-token":
        errors.append(
            "FATAL: MCP_AUTH_TOKEN is using the placeholder value from .env.example. Paste the actual static token given by Central Auth during registration."
        )

    # Check SUPABASE_URL
    if not s.SUPABASE_URL or not s.SUPABASE_URL.strip() or "your-supabase-project" in s.SUPABASE_URL:
        errors.append(
            "FATAL: SUPABASE_URL is not set. Copy .env.sample to .env and paste the Supabase project URL before starting this server."
        )

    # Check SUPABASE_SERVICE_ROLE_KEY
    if not s.SUPABASE_SERVICE_ROLE_KEY or not s.SUPABASE_SERVICE_ROLE_KEY.strip() or s.SUPABASE_SERVICE_ROLE_KEY == "your-supabase-service-role-key":
        errors.append(
            "FATAL: SUPABASE_SERVICE_ROLE_KEY is not set. Copy .env.sample to .env and paste the Supabase service role key before starting this server."
        )

    # Check ENCRYPTION_MASTER_KEY
    if not s.ENCRYPTION_MASTER_KEY or not s.ENCRYPTION_MASTER_KEY.strip():
        errors.append(
            "FATAL: ENCRYPTION_MASTER_KEY is not set. Copy .env.sample to .env and generate a master key via 'python scripts/generate_master_key.py' before starting this server."
        )
    elif s.ENCRYPTION_MASTER_KEY == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef":
        errors.append(
            "FATAL: ENCRYPTION_MASTER_KEY is using the illustrative example key from .env.example. Generate a unique key via 'python scripts/generate_master_key.py'."
        )

    return errors

# Initialize settings instance; if Pydantic validation fails, log clear fatal messages before re-raising
try:
    settings = Settings()
except ValidationError as e:
    missing_locs = {err["loc"][0] for err in e.errors()}
    fatal_msgs: List[str] = []
    if "MCP_AUTH_AUDIENCE" in missing_locs:
        fatal_msgs.append(
            "FATAL: MCP_AUTH_AUDIENCE is not set. Copy .env.sample to .env and paste the exact audience value from the Central Auth admin panel before starting this server."
        )
    if "SUPABASE_URL" in missing_locs:
        fatal_msgs.append(
            "FATAL: SUPABASE_URL is not set. Copy .env.sample to .env and paste the Supabase project URL before starting this server."
        )
    if "SUPABASE_SERVICE_ROLE_KEY" in missing_locs:
        fatal_msgs.append(
            "FATAL: SUPABASE_SERVICE_ROLE_KEY is not set. Copy .env.sample to .env and paste the Supabase service role key before starting this server."
        )
    if "ENCRYPTION_MASTER_KEY" in missing_locs:
        fatal_msgs.append(
            "FATAL: ENCRYPTION_MASTER_KEY is not set. Copy .env.sample to .env and generate a master key via 'python scripts/generate_master_key.py' before starting this server."
        )
    for msg in fatal_msgs:
        print(msg, file=sys.stderr)
    raise
