import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from starlette.testclient import TestClient
from server import app
from core.context import set_current_tenant_id, get_current_tenant_id
from db.supabase_client import SupabaseService
from routes.onboarding import verify_tenant_credentials

@pytest.fixture
def mcp_test_client():
    with patch("server.browser_manager.start", new_callable=AsyncMock), \
         patch("server.browser_manager.stop", new_callable=AsyncMock):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

def test_mcp_unauthenticated_requests_return_401_not_404(mcp_test_client):
    """Confirm /mcp, /sse, and parameterized paths are protected by auth middleware (401, not 404)."""
    # GET /mcp
    res_get = mcp_test_client.get("/mcp")
    assert res_get.status_code == 401
    assert res_get.json()["error"] == "unauthorized"

    # POST /mcp
    res_post = mcp_test_client.post("/mcp", json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    })
    assert res_post.status_code == 401
    assert res_post.json()["error"] == "unauthorized"

    # GET /sse
    res_sse = mcp_test_client.get("/sse")
    assert res_sse.status_code == 401
    assert res_sse.json()["error"] == "unauthorized"

    # GET /mcp/{url_token} without auth
    res_token_get = mcp_test_client.get("/mcp/any-token-123")
    assert res_token_get.status_code == 401
    assert res_token_get.json()["error"] == "unauthorized"

    # POST /mcp/{url_token} without auth
    res_token_post = mcp_test_client.post("/mcp/any-token-123", json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    })
    assert res_token_post.status_code == 401
    assert res_token_post.json()["error"] == "unauthorized"

def test_mcp_post_with_valid_auth_and_valid_url_token(mcp_test_client):
    """
    Confirm POST /mcp/{url_token} with verified auth claims and valid url_token
    returns a valid JSON-RPC response, and get_current_tenant_id() equals the
    tenant_id that url_token maps to (winning over JWT claims).
    """
    mock_claims = {
        "sub": "user_123",
        "aud": "digital-invoice-web",
        "tenant_id": "claims-tenant-uuid"
    }
    resolved_tenant = "resolved-url-tenant-uuid"

    captured_tenants = []
    orig_set_tenant = set_current_tenant_id
    def spy_set_tenant(tid):
        captured_tenants.append(tid)
        orig_set_tenant(tid)

    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims), \
         patch("server.db_service.get_tenant_id_by_url_token", new_callable=AsyncMock) as mock_lookup, \
         patch("server.set_current_tenant_id", side_effect=spy_set_tenant):
        mock_lookup.return_value = resolved_tenant
        headers = {
            "Authorization": "Bearer mock-valid-token",
            "Content-Type": "application/json"
        }
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        }
        res = mcp_test_client.post("/mcp/valid-token-xyz", json=payload, headers=headers)
        assert res.status_code == 200

        # Verify tenant resolved by url_token was set and won over claims
        mock_lookup.assert_called_once_with("valid-token-xyz")
        assert resolved_tenant in captured_tenants
        assert captured_tenants[-1] == resolved_tenant

        content_type = res.headers.get("content-type", "")
        if "application/json" in content_type:
            data = res.json()
        else:
            data = None
            for line in res.text.splitlines():
                if line.startswith("data:"):
                    data = json.loads(line[len("data:"):].strip())
                    break

        assert data is not None, f"Expected JSON-RPC body in response: {res.text}"
        assert data.get("jsonrpc") == "2.0"
        assert data.get("id") == 1
        assert "result" in data
        assert data["result"]["serverInfo"]["name"] == "digital-invoice-web"
        assert "capabilities" in data["result"]

def test_mcp_valid_auth_with_unknown_url_token_returns_401(mcp_test_client):
    """
    Confirm valid JWT + UNKNOWN url_token returns 401 with exact same error body shape
    as the existing 'no auth header' 401 test.
    """
    no_auth_res = mcp_test_client.get("/mcp")
    expected_body = no_auth_res.json()

    mock_claims = {
        "sub": "user_123",
        "aud": "digital-invoice-web",
        "tenant_id": "test-tenant-uuid"
    }
    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims), \
         patch("server.db_service.get_tenant_id_by_url_token", new_callable=AsyncMock) as mock_lookup:
        mock_lookup.return_value = None
        headers = {
            "Authorization": "Bearer mock-valid-token",
            "Content-Type": "application/json"
        }
        res = mcp_test_client.post("/mcp/unknown-url-token", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        }, headers=headers)

        assert res.status_code == 401
        assert res.json() == expected_body
        assert res.json()["error"] == "unauthorized"

def test_mcp_valid_auth_with_inactive_tenant_returns_401(mcp_test_client):
    """
    Confirm valid JWT + valid url_token where tenant.is_active is False returns 401 (same shape).
    """
    no_auth_res = mcp_test_client.get("/mcp")
    expected_body = no_auth_res.json()

    mock_claims = {
        "sub": "user_123",
        "aud": "digital-invoice-web",
        "tenant_id": "test-tenant-uuid"
    }
    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims), \
         patch("server.db_service.get_tenant_id_by_url_token", new_callable=AsyncMock) as mock_lookup:
        # get_tenant_id_by_url_token returns None for inactive tenants
        mock_lookup.return_value = None
        headers = {"Authorization": "Bearer mock-valid-token"}

        res = mcp_test_client.get("/mcp/inactive-tenant-token", headers=headers)
        assert res.status_code == 401
        assert res.json() == expected_body
        assert res.json()["error"] == "unauthorized"

def test_mcp_get_with_valid_auth_probe(mcp_test_client):
    """
    Confirm GET /mcp/{url_token} with verified auth claims does not 404.
    Streamable HTTP GET requires a session ID, returning 400 Bad Request if absent.
    """
    mock_claims = {
        "sub": "user_123",
        "aud": "digital-invoice-web",
        "tenant_id": "test-tenant-uuid"
    }
    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims), \
         patch("server.db_service.get_tenant_id_by_url_token", new_callable=AsyncMock) as mock_lookup:
        mock_lookup.return_value = "test-tenant-uuid"
        headers = {"Authorization": "Bearer mock-valid-token"}
        res = mcp_test_client.get("/mcp/valid-token-abc", headers=headers)
        # Should NOT be 404
        assert res.status_code != 404
        # Returns 400 (Missing session ID query parameter)
        assert res.status_code == 400

def test_onboarding_regenerate_link_flow(mcp_test_client):
    """
    Test /onboarding/regenerate-link:
    - correct email/password -> 200 with new URL different from old one
    - wrong password -> generic error with identical status and shape as unknown email
    - unknown email -> generic error with identical status and shape
    """
    email = "admin@examplecompany.com"
    password = "CorrectPassword123!"
    old_token = "old_token_initial"
    new_token = "new_token_rotated_xyz"

    # 1. Successful rotation
    with patch("routes.onboarding.verify_tenant_credentials", new_callable=AsyncMock) as mock_verify, \
         patch("routes.onboarding.db_service.rotate_url_token", new_callable=AsyncMock) as mock_rotate:
        mock_verify.return_value = True
        mock_rotate.return_value = new_token

        res = mcp_test_client.post("/onboarding/regenerate-link", data={
            "email": email,
            "password": password
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["url_token"] == new_token
        assert f"/mcp/{new_token}" in data["mcp_server_url"]
        assert f"/sse/{new_token}" in data["sse_server_url"]
        assert old_token not in data["mcp_server_url"]

    # 2. Wrong password failure
    with patch("routes.onboarding.verify_tenant_credentials", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = False
        res_wrong_pw = mcp_test_client.post("/onboarding/regenerate-link", data={
            "email": email,
            "password": "WrongPassword!"
        })
        assert res_wrong_pw.status_code == 401
        wrong_pw_body = res_wrong_pw.json()
        assert wrong_pw_body == {"success": False, "error": "Invalid email or password"}

    # 3. Unknown email failure
    with patch("routes.onboarding.verify_tenant_credentials", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = False
        res_unknown_email = mcp_test_client.post("/onboarding/regenerate-link", data={
            "email": "nonexistent@company.com",
            "password": password
        })
        assert res_unknown_email.status_code == 401
        unknown_email_body = res_unknown_email.json()
        assert unknown_email_body == {"success": False, "error": "Invalid email or password"}

        # Indistinguishable status code and shape
        assert res_wrong_pw.status_code == res_unknown_email.status_code
        assert wrong_pw_body == unknown_email_body

@pytest.mark.asyncio
async def test_verify_tenant_credentials_logic():
    """Unit test for verify_tenant_credentials helper."""
    with patch("routes.onboarding.db_service.get_decrypted_credentials", new_callable=AsyncMock) as mock_creds:
        mock_creds.return_value = {
            "email": "test@domain.com",
            "password": "ExactPassword999!"
        }

        # Match (case-insensitive email, exact password)
        assert await verify_tenant_credentials("t-id", "TEST@domain.com", "ExactPassword999!") is True
        assert await verify_tenant_credentials("t-id", "test@domain.com", "ExactPassword999!") is True

        # Password mismatch
        assert await verify_tenant_credentials("t-id", "test@domain.com", "wrong-password") is False

        # Email mismatch
        assert await verify_tenant_credentials("t-id", "other@domain.com", "ExactPassword999!") is False

        # No record found
        mock_creds.return_value = None
        assert await verify_tenant_credentials("t-id", "test@domain.com", "ExactPassword999!") is False

@pytest.mark.asyncio
async def test_supabase_service_url_token_methods():
    """Unit test for get_tenant_id_by_url_token and rotate_url_token."""
    service = SupabaseService()
    mock_client = MagicMock()
    service._client = mock_client

    # Test get_tenant_id_by_url_token: active tenant
    table_mock = MagicMock()
    mock_client.table.return_value = table_mock
    table_mock.select.return_value = table_mock
    table_mock.eq.return_value = table_mock
    table_mock.execute.return_value = MagicMock(data=[{"id": "tenant-123", "is_active": True}])

    tid = await service.get_tenant_id_by_url_token("my-token")
    assert tid == "tenant-123"

    # Test get_tenant_id_by_url_token: inactive tenant returns None
    table_mock.execute.return_value = MagicMock(data=[{"id": "tenant-123", "is_active": False}])
    tid_inactive = await service.get_tenant_id_by_url_token("my-token")
    assert tid_inactive is None

    # Test rotate_url_token
    update_mock = MagicMock()
    mock_client.table.return_value = update_mock
    update_mock.update.return_value = update_mock
    update_mock.eq.return_value = update_mock
    update_mock.execute.return_value = MagicMock(data=[])

    new_token = await service.rotate_url_token("tenant-123")
    assert isinstance(new_token, str)
    assert len(new_token) >= 24
    update_mock.update.assert_called_once()
