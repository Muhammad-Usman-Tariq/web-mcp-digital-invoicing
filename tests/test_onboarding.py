import uuid
import pytest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient
from server import app
from core.config import settings
from sdk.python.mcp_auth_middleware import McpAuthMiddleware
import routes.onboarding as onboarding_module

@pytest.fixture
def client():
    with patch("server.browser_manager.start", new_callable=AsyncMock), \
         patch("server.browser_manager.stop", new_callable=AsyncMock):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

@pytest.fixture(autouse=True)
def reset_rate_limits():
    onboarding_module._rate_limits.clear()


def test_server_auth_wiring_matches_official_pattern():
    """
    Assert that server.py configures McpAuthMiddleware matching the official
    Central Auth pattern exactly, with jwks_uri and audience sourced from settings,
    and contains no other custom auth middleware.
    """
    auth_middlewares = [m for m in app.user_middleware if m.cls is McpAuthMiddleware]
    assert len(auth_middlewares) == 1, "Exactly one McpAuthMiddleware must be registered"
    
    mcp_middleware = auth_middlewares[0]
    assert mcp_middleware.kwargs.get("jwks_uri") == settings.JWKS_URI
    assert mcp_middleware.kwargs.get("audience") == settings.MCP_AUTH_AUDIENCE

    # Ensure no dual-mode, custom auth, or key-hashing middleware exists
    middleware_names = [m.cls.__name__ for m in app.user_middleware]
    for disallowed in ["ApiKeyAuthMiddleware", "CustomAuthMiddleware", "DualAuthMiddleware", "TenantKeyMiddleware"]:
        assert disallowed not in middleware_names, f"Unexpected custom auth middleware {disallowed} found"


def test_root_redirects_to_onboarding_without_auth(client):
    """
    Confirm GET / returns a 307/302 redirect to /onboarding without requiring
    any authentication header.
    """
    res = client.get("/", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers.get("location") == "/onboarding"

    # Verify following the redirect loads onboarding page without auth
    followed = client.get("/", follow_redirects=True)
    assert followed.status_code == 200
    assert 'name="company_name"' in followed.text


def test_onboarding_get_form_renders_without_auth(client):
    """
    GET /onboarding renders the form directly without any login requirement or redirect.
    """
    res = client.get("/onboarding")
    assert res.status_code == 200
    html = res.text
    
    # Must contain noindex meta tag
    assert '<meta name="robots" content="noindex, nofollow">' in html
    
    # Must contain required fields
    assert 'name="company_name"' in html
    assert 'name="email"' in html
    assert 'name="password"' in html
    assert 'type="password"' in html
    assert 'autocomplete="new-password"' in html
    assert 'id="toggle-password"' in html
    assert 'id="eye-icon"' in html


def test_onboarding_get_form_ignores_cookies_and_headers(client):
    """
    GET /onboarding always returns the blank form template regardless of any
    cookies/headers sent with the request.
    """
    client.cookies.set("session", "fake_session_123")
    client.cookies.set("auth_token", "expired_or_forged")
    res = client.get(
        "/onboarding",
        headers={"Authorization": "Bearer fake_token"}
    )
    assert res.status_code == 200
    html = res.text
    assert '<h1 class="card-title">Tenant Onboarding</h1>' in html
    assert 'name="company_name"' in html
    assert 'name="email"' in html
    assert 'name="password"' in html
    assert 'id="toggle-password"' in html


def test_onboarding_post_brand_new_email(client):
    """
    POST /onboarding with a brand-new email:
    - Checks db_service.get_tenant, finds None
    - Creates tenant, generates new url_token, saves credentials
    - Shows results page with Log out link and caption
    """
    test_email = "newuser@example.com"
    with patch("routes.onboarding.db_service.get_tenant", new_callable=AsyncMock) as mock_get_tenant, \
         patch("routes.onboarding.db_service.save_tenant_credentials", new_callable=AsyncMock) as mock_save:
        mock_get_tenant.return_value = None
        mock_save.return_value = True

        res = client.post("/onboarding", data={
            "company_name": "Brand New Corp",
            "email": test_email,
            "password": "ValidPassword123!"
        })

        assert res.status_code == 200
        mock_get_tenant.assert_called_once()
        mock_save.assert_called_once()
        saved_kwargs = mock_save.call_args.kwargs
        assert saved_kwargs["email"] == test_email
        assert saved_kwargs["company_name"] == "Brand New Corp"
        assert saved_kwargs["url_token"] is not None
        assert f"/mcp/{saved_kwargs['url_token']}" in res.text
        assert "Log out" in res.text
        assert "You'll need your portal email and password to view this again." in res.text


def test_onboarding_post_returning_customer_correct_password(client):
    """
    POST /onboarding with an email that already has a tenant + correct password:
    - Results page shown with the SAME url_token as before (no new tenant/token created)
    - Assert db_service create/insert (save_tenant_credentials) was NOT called again
    - Only the existing record was read
    """
    test_email = "returning@example.com"
    test_tenant_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, test_email))
    existing_url_token = "existing_safe_token_abc123"

    existing_tenant_record = {
        "id": test_tenant_id,
        "company_name": "Returning Enterprise",
        "url_token": existing_url_token,
        "is_active": True
    }

    with patch("routes.onboarding.db_service.get_tenant", new_callable=AsyncMock) as mock_get_tenant, \
         patch("routes.onboarding.verify_tenant_credentials", new_callable=AsyncMock) as mock_verify, \
         patch("routes.onboarding.db_service.save_tenant_credentials", new_callable=AsyncMock) as mock_save, \
         patch("routes.onboarding.db_service.rotate_url_token", new_callable=AsyncMock) as mock_rotate:
        
        mock_get_tenant.return_value = existing_tenant_record
        mock_verify.return_value = True

        res = client.post("/onboarding", data={
            "company_name": "Returning Enterprise",
            "email": test_email,
            "password": "CorrectPassword123!"
        })

        assert res.status_code == 200
        mock_get_tenant.assert_called_once_with(test_tenant_id)
        mock_verify.assert_called_once_with(test_tenant_id, test_email, "CorrectPassword123!")
        
        # Assert NO create/save or rotate was executed
        mock_save.assert_not_called()
        mock_rotate.assert_not_called()

        # Confirm results page contains the SAME existing url_token
        assert f"/mcp/{existing_url_token}" in res.text
        assert "Returning Enterprise" in res.text
        assert "Log out" in res.text
        assert "You'll need your portal email and password to view this again." in res.text


def test_onboarding_post_returning_customer_wrong_password(client):
    """
    POST /onboarding with an existing email + wrong password:
    - Generic 'Invalid email or password' error
    - Does not reveal whether email exists or which field was wrong
    - Status code 401
    """
    test_email = "victim@example.com"
    test_tenant_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, test_email))

    existing_tenant_record = {
        "id": test_tenant_id,
        "company_name": "Victim Inc",
        "url_token": "victim_token_999",
        "is_active": True
    }

    with patch("routes.onboarding.db_service.get_tenant", new_callable=AsyncMock) as mock_get_tenant, \
         patch("routes.onboarding.verify_tenant_credentials", new_callable=AsyncMock) as mock_verify, \
         patch("routes.onboarding.db_service.save_tenant_credentials", new_callable=AsyncMock) as mock_save:
        
        mock_get_tenant.return_value = existing_tenant_record
        mock_verify.return_value = False

        res = client.post("/onboarding", data={
            "company_name": "Victim Inc",
            "email": test_email,
            "password": "WrongPassword999!"
        })

        assert res.status_code == 401
        assert "Invalid email or password" in res.text
        mock_save.assert_not_called()


def test_onboarding_post_saves_credentials_and_renders_results(client):
    """
    Submitting the onboarding form:
    1. Saves encrypted credentials via db_service.save_tenant_credentials.
    2. Renders results page with MCP URL, Central Auth explanation, per-LLM tabs, and test-connection.
    """
    with patch("routes.onboarding.db_service.save_tenant_credentials", new_callable=AsyncMock) as mock_save:
        mock_save.return_value = True

        res = client.post("/onboarding", data={
            "company_name": "Acme Global Solutions",
            "email": "billing@acmeglobal.com",
            "password": "SuperSecretPassword123!"
        })

        assert res.status_code == 200
        html = res.text

        # Verify db_service.save_tenant_credentials was called with correct data
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args.kwargs
        assert call_kwargs["company_name"] == "Acme Global Solutions"
        assert call_kwargs["email"] == "billing@acmeglobal.com"
        assert call_kwargs["password"] == "SuperSecretPassword123!"
        
        # Verify internal tenant_id was deterministically generated as a valid UUID
        tenant_id = call_kwargs["tenant_id"]
        assert uuid.UUID(tenant_id)
        assert tenant_id == str(uuid.uuid5(uuid.NAMESPACE_DNS, "billing@acmeglobal.com"))

        # Verify results page contains MCP Server URL with /mcp
        assert "/mcp" in html

        # Verify customer-facing copy and absence of internal terms
        assert "MCP Server Connection" in html
        assert "MCP Server URL" in html
        assert "MCP API Key" in html
        assert "Central Auth" not in html
        assert "OAuth 2.1" not in html
        assert "JWKS" not in html

        # Verify per-LLM tabs are present
        assert "Claude" in html
        assert "Cursor" in html
        assert "Windsurf" in html
        assert "Antigravity" in html
        assert "OpenAI / GPT" in html

        # Verify key differences in client tab configurations
        assert '"url":' in html  # Cursor uses "url"
        assert '"serverUrl":' in html  # Windsurf & Antigravity use "serverUrl"
        assert '"x-api-key":' in html  # Header used across tools
        assert "Developer mode" in html  # OpenAI step
        assert "click here to connect automatically" not in html.lower()

        # Verify disclaimer on all sections
        disclaimer = "Steps may change as the provider updates their product — verify before publishing."
        assert disclaimer in html
        assert html.count(disclaimer) >= 5

        # Verify password is never leaked in HTML
        assert "SuperSecretPassword123!" not in html


def test_onboarding_rate_limiting_per_ip(client):
    """Rate limits POST /onboarding to 5 requests per 5 minutes per IP."""
    with patch("routes.onboarding.db_service.save_tenant_credentials", new_callable=AsyncMock) as mock_save:
        mock_save.return_value = True

        for i in range(5):
            res = client.post("/onboarding", data={
                "company_name": f"Org {i}",
                "email": f"org{i}@example.com",
                "password": "validpassword"
            })
            assert res.status_code == 200

        # 6th attempt should be blocked
        blocked = client.post("/onboarding", data={
            "company_name": "Blocked Org",
            "email": "blocked@example.com",
            "password": "validpassword"
        })
        assert blocked.status_code == 429
        assert "Too many submissions" in blocked.text


def test_test_connection_endpoint(client):
    """
    POST /onboarding/test-connection verifies the saved portal credentials
    via check_login_status for the given tenant_id.
    """
    test_tenant_id = str(uuid.uuid4())
    with patch("routes.onboarding.check_login_status", new_callable=AsyncMock) as mock_status:
        mock_status.return_value = {
            "success": True,
            "data": {
                "is_logged_in": True,
                "current_url": "https://www.digitalinvoicingsoftware.com/dashboard",
                "is_on_dashboard": True,
                "page_title": "Dashboard"
            },
            "tenant_id": test_tenant_id,
            "duration_ms": 950
        }

        res = client.post("/onboarding/test-connection", data={"tenant_id": test_tenant_id})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["is_logged_in"] is True
        assert data["current_url"] == "https://www.digitalinvoicingsoftware.com/dashboard"
        mock_status.assert_called_once()
