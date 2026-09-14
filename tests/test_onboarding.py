import pytest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient
from server import app
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

def test_unauthenticated_redirects_to_login(client):
    # 1. Root /onboarding
    res = client.get("/onboarding", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/onboarding/login"

    # 2. /onboarding/credentials
    res = client.get("/onboarding/credentials", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/onboarding/login"

    # 3. /onboarding/connect
    res = client.get("/onboarding/connect", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/onboarding/login"


def test_login_page_renders_with_noindex(client):
    res = client.get("/onboarding/login")
    assert res.status_code == 200
    html = res.text
    # Step 5: Check noindex meta tag
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert "Identify Your Tenant" in html
    assert "Central Auth" in html


def test_login_submit_invalid_token(client):
    with patch("routes.onboarding.verify_onboarding_token", return_value=None):
        res = client.post("/onboarding/login", data={"token": "invalid.jwt.token"})
        assert res.status_code == 400
        assert "Invalid or expired token" in res.text


def test_login_submit_valid_token_sets_session_cookie(client):
    mock_claims = {"tenant_id": "tenant-uuid-12345", "sub": "user-uuid-67890"}
    with patch("routes.onboarding.verify_onboarding_token", return_value=mock_claims):
        res = client.post("/onboarding/login", data={"token": "valid.mock.jwt"}, follow_redirects=False)
        assert res.status_code == 302
        assert res.headers["location"] == "/onboarding/credentials"
        assert "onboarding_token=valid.mock.jwt" in res.headers["set-cookie"]
        assert "HttpOnly" in res.headers["set-cookie"]


def test_credentials_page_renders_verified_tenant(client):
    mock_claims = {"tenant_id": "tenant-uuid-12345", "sub": "user-uuid-67890"}
    client.cookies.set("onboarding_token", "valid.mock.jwt")

    with patch("routes.onboarding.verify_onboarding_token", return_value=mock_claims), \
         patch("routes.onboarding.db_service.get_tenant", new_callable=AsyncMock) as mock_get_tenant, \
         patch("routes.onboarding.db_service.get_decrypted_credentials", new_callable=AsyncMock) as mock_get_creds:
        mock_get_tenant.return_value = {"company_name": "Test Company", "updated_at": "2026-09-14T00:00:00Z"}
        mock_get_creds.return_value = {"email": "portal@example.com"}

        res = client.get("/onboarding/credentials")
        assert res.status_code == 200
        html = res.text
        # Verified tenant_id is displayed as read-only, not an editable input field
        assert "tenant-uuid-12345" in html
        assert "Test Company" in html
        assert "p***l@example.com" in html
        assert '<meta name="robots" content="noindex, nofollow">' in html


def test_credentials_submit_invokes_save_tenant_credentials_with_token_tenant_id(client):
    mock_claims = {"tenant_id": "verified-tenant-abc", "sub": "user-123"}
    client.cookies.set("onboarding_token", "valid.mock.jwt")

    with patch("routes.onboarding.verify_onboarding_token", return_value=mock_claims), \
         patch("routes.onboarding.db_service.save_tenant_credentials", new_callable=AsyncMock) as mock_save:
        mock_save.return_value = True

        res = client.post("/onboarding/credentials", data={
            "company_name": "Acme Widgets Ltd",
            "email": "invoicing@acmewidgets.com",
            "password": "SuperSecretPassword999!"
        })

        assert res.status_code == 200
        assert "Credentials successfully encrypted with AES-256-GCM" in res.text
        assert "i***g@acmewidgets.com" in res.text

        # Verify that save_tenant_credentials was called with the VERIFIED tenant_id from JWT claims,
        # not anything passed in by user
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args.kwargs
        assert call_kwargs["tenant_id"] == "verified-tenant-abc"
        assert call_kwargs["company_name"] == "Acme Widgets Ltd"
        assert call_kwargs["email"] == "invoicing@acmewidgets.com"
        assert call_kwargs["password"] == "SuperSecretPassword999!"


def test_test_connection_endpoint(client):
    mock_claims = {"tenant_id": "verified-tenant-abc", "sub": "user-123"}
    client.cookies.set("onboarding_token", "valid.mock.jwt")

    with patch("routes.onboarding.verify_onboarding_token", return_value=mock_claims), \
         patch("routes.onboarding.check_login_status", new_callable=AsyncMock) as mock_status:
        mock_status.return_value = {
            "success": True,
            "data": {
                "is_logged_in": True,
                "current_url": "https://www.digitalinvoicingsoftware.com/dashboard",
                "is_on_dashboard": True,
                "page_title": "Dashboard"
            },
            "tenant_id": "verified-tenant-abc",
            "duration_ms": 1200
        }

        res = client.post("/onboarding/test-connection")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["is_logged_in"] is True
        assert data["is_on_dashboard"] is True


def test_connect_page_renders_guides_and_disclaimers(client):
    mock_claims = {"tenant_id": "verified-tenant-abc", "sub": "user-123"}
    client.cookies.set("onboarding_token", "valid.mock.jwt")

    with patch("routes.onboarding.verify_onboarding_token", return_value=mock_claims):
        res = client.get("/onboarding/connect")
        assert res.status_code == 200
        html = res.text

        # 1. No API key needed callout
        assert "No API Key Needed" in html
        assert "OAuth 2.1 authentication" in html

        # 2. Server URL and Copy
        assert "/mcp" in html

        # 3. Per-LLM sections
        assert "Claude / Desktop" in html
        assert "Claude Code (CLI)" in html
        assert "claude mcp add --transport http digital-invoice-web" in html
        assert "ChatGPT" in html
        assert "Cursor / Antigravity" in html

        # 4. Screenshot placeholders
        assert "<!-- TODO: screenshot -->" in html

        # 5. Required disclaimer on all sections
        disclaimer = "Steps may change as the provider updates their product — verify before publishing."
        assert disclaimer in html
        # Appears across all 4 client sections
        assert html.count(disclaimer) == 4


def test_rate_limiting_on_credentials_submission(client):
    mock_claims = {"tenant_id": "rate-limit-tenant", "sub": "user-123"}
    client.cookies.set("onboarding_token", "valid.mock.jwt")

    with patch("routes.onboarding.verify_onboarding_token", return_value=mock_claims), \
         patch("routes.onboarding.db_service.save_tenant_credentials", new_callable=AsyncMock) as mock_save:
        mock_save.return_value = True

        for i in range(5):
            res = client.post("/onboarding/credentials", data={
                "company_name": f"Co {i}",
                "email": f"co{i}@example.com",
                "password": "pass"
            })
            assert res.status_code == 200

        # 6th attempt should be blocked by rate limiter
        res = client.post("/onboarding/credentials", data={
            "company_name": "Blocked Co",
            "email": "blocked@example.com",
            "password": "pass"
        })
        assert res.status_code == 429
        assert "Too many credential submissions" in res.text


def test_logout_clears_cookie(client):
    client.cookies.set("onboarding_token", "valid.mock.jwt")
    res = client.get("/onboarding/logout", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/onboarding/login"
    assert 'onboarding_token=""' in res.headers["set-cookie"] or 'Max-Age=0' in res.headers["set-cookie"]
