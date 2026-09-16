import pytest
from pydantic import ValidationError
from core.config import Settings, validate_critical_settings

def test_missing_critical_settings_raises_validation_error(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_AUDIENCE", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("ENCRYPTION_MASTER_KEY", raising=False)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    errors = excinfo.value.errors()
    missing_fields = {e["loc"][0] for e in errors}
    assert "MCP_AUTH_AUDIENCE" in missing_fields
    assert "SUPABASE_URL" in missing_fields
    assert "SUPABASE_SERVICE_ROLE_KEY" in missing_fields
    assert "ENCRYPTION_MASTER_KEY" in missing_fields

def test_validate_critical_settings_empty_strings():
    s = Settings(
        MCP_AUTH_AUDIENCE="",
        MCP_AUTH_TOKEN="",
        SUPABASE_URL="",
        SUPABASE_SERVICE_ROLE_KEY="",
        ENCRYPTION_MASTER_KEY="",
        _env_file=None
    )
    errors = validate_critical_settings(s)
    joined = "\n".join(errors)

    assert "FATAL: MCP_AUTH_AUDIENCE is not set" in joined
    assert "FATAL: MCP_AUTH_TOKEN is not set" in joined
    assert "FATAL: SUPABASE_URL is not set" in joined
    assert "FATAL: SUPABASE_SERVICE_ROLE_KEY is not set" in joined
    assert "FATAL: ENCRYPTION_MASTER_KEY is not set" in joined

def test_validate_critical_settings_valid():
    s = Settings(
        MCP_AUTH_AUDIENCE="prod-audience",
        MCP_AUTH_TOKEN="my-mcp-auth-token",
        SUPABASE_URL="https://myproj.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY="my-secret-key",
        ENCRYPTION_MASTER_KEY="a" * 64,
        _env_file=None
    )
    errors = validate_critical_settings(s)
    assert len(errors) == 0

def test_validate_critical_settings_placeholder_token():
    s = Settings(
        MCP_AUTH_AUDIENCE="prod-audience",
        MCP_AUTH_TOKEN="your-mcp-auth-token",
        SUPABASE_URL="https://myproj.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY="my-secret-key",
        ENCRYPTION_MASTER_KEY="a" * 64,
        _env_file=None
    )
    errors = validate_critical_settings(s)
    joined = "\n".join(errors)
    assert "FATAL: MCP_AUTH_TOKEN is using the placeholder value" in joined

@pytest.mark.asyncio
async def test_server_lifespan_fails_with_invalid_settings(monkeypatch):
    from server import lifespan, app
    import core.config

    # Set an invalid/empty audience on the loaded settings object
    monkeypatch.setattr(core.config.settings, "MCP_AUTH_AUDIENCE", "")
    with pytest.raises(RuntimeError) as excinfo:
        async with lifespan(app):
            pass
    assert "FATAL: MCP_AUTH_AUDIENCE is not set" in str(excinfo.value)

    # Set an invalid/empty MCP_AUTH_TOKEN on the loaded settings object
    monkeypatch.setattr(core.config.settings, "MCP_AUTH_AUDIENCE", "valid-audience")
    monkeypatch.setattr(core.config.settings, "MCP_AUTH_TOKEN", "")
    with pytest.raises(RuntimeError) as excinfo:
        async with lifespan(app):
            pass
    assert "FATAL: MCP_AUTH_TOKEN is not set" in str(excinfo.value)
