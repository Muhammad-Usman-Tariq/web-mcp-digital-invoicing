import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from starlette.testclient import TestClient
from server import app

@pytest.fixture
def mcp_test_client():
    with patch("server.browser_manager.start", new_callable=AsyncMock), \
         patch("server.browser_manager.stop", new_callable=AsyncMock):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

def test_mcp_unauthenticated_requests_return_401_not_404(mcp_test_client):
    """Confirm /mcp and /sse are registered and protected by auth middleware (401, not 404)."""
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

def test_mcp_post_with_valid_auth_returns_jsonrpc_initialize(mcp_test_client):
    """
    Confirm POST /mcp with verified auth claims returns a valid JSON-RPC response,
    NOT 404 and NOT 500.
    """
    mock_claims = {
        "sub": "user_123",
        "aud": "digital-invoice-web",
        "tenant_id": "test-tenant-uuid"
    }
    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims):
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
        res = mcp_test_client.post("/mcp", json=payload, headers=headers)
        assert res.status_code == 200

        # Streamable HTTP can return application/json or text/event-stream
        content_type = res.headers.get("content-type", "")
        if "application/json" in content_type:
            data = res.json()
        else:
            # Parse text/event-stream data line
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

def test_mcp_get_with_valid_auth_probe(mcp_test_client):
    """
    Confirm GET /mcp with verified auth claims does not 404.
    Streamable HTTP GET /mcp requires a session ID, returning 400 Bad Request if absent.
    """
    mock_claims = {
        "sub": "user_123",
        "aud": "digital-invoice-web",
        "tenant_id": "test-tenant-uuid"
    }
    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims):
        headers = {"Authorization": "Bearer mock-valid-token"}
        res = mcp_test_client.get("/mcp", headers=headers)
        # Should NOT be 404
        assert res.status_code != 404
        # Returns 400 (Missing session ID query parameter)
        assert res.status_code == 400
