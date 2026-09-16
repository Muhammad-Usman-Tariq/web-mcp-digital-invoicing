import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from starlette.testclient import TestClient
from server import app, _sse_session_tenants, sse_transport
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
        assert "mcp_api_key" in data
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

@pytest.mark.asyncio
async def test_sse_handshake_establishes_session_and_records_tenant():
    """
    Test: GET /sse/{url_token} with valid auth establishes a session and the
    session's tenant is recorded correctly (mock db_service.get_tenant_id_by_url_token,
    inspect _sse_session_tenants after connecting).
    """
    mock_claims = {"sub": "user_1", "aud": "digital-invoice-web", "tenant_id": "claims-tid"}
    resolved_tenant = "tenant-sse-handshake-123"

    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims), \
         patch("server.db_service.get_tenant_id_by_url_token", new_callable=AsyncMock) as mock_lookup:
        mock_lookup.return_value = resolved_tenant

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/sse/valid-sse-token",
            "raw_path": b"/sse/valid-sse-token",
            "query_string": b"",
            "headers": [
                (b"authorization", b"Bearer test-valid-token"),
                (b"host", b"testserver"),
            ]
        }

        async def receive():
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        task = asyncio.create_task(app(scope, receive, send))
        try:
            for _ in range(20):
                await asyncio.sleep(0.01)
                if any(t == resolved_tenant for t in _sse_session_tenants.values()):
                    break

            matching_sessions = [s for s, t in _sse_session_tenants.items() if t == resolved_tenant]
            assert len(matching_sessions) == 1
            session_id = matching_sessions[0]
            assert _sse_session_tenants[session_id] == resolved_tenant
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, BaseException):
                pass

@pytest.mark.asyncio
async def test_sse_multi_tenant_isolation_post_messages(mcp_test_client):
    """
    Test: two different url_tokens resolving to two different tenant_ids, each
    connecting their own SSE session, then each POSTing a message via
    /messages/?session_id=<their own> — assert get_current_tenant_id() (captured
    via a spy) is DIFFERENT and correct for each, never cross-contaminated.
    """
    url_tokens = {
        "token-tenant-alpha": "tenant-alpha-uuid",
        "token-tenant-beta": "tenant-beta-uuid"
    }

    async def mock_lookup(token):
        return url_tokens.get(token)

    captured_tenants = []
    async def spy_handle_post_message(scope, receive, send):
        captured_tenants.append(get_current_tenant_id())
        response_start = {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")]
        }
        await send(response_start)
        await send({"type": "http.response.body", "body": b"{}"})

    mock_claims = {"sub": "user_1", "aud": "digital-invoice-web", "tenant_id": "claims-tid"}
    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims), \
         patch("server.db_service.get_tenant_id_by_url_token", side_effect=mock_lookup), \
         patch.object(sse_transport, "handle_post_message", side_effect=spy_handle_post_message):

        async def connect_client(token):
            scope = {
                "type": "http",
                "method": "GET",
                "path": f"/sse/{token}",
                "raw_path": f"/sse/{token}".encode(),
                "query_string": b"",
                "headers": [
                    (b"authorization", b"Bearer test-valid-token"),
                    (b"host", b"testserver"),
                ]
            }
            async def rec():
                await asyncio.Event().wait()
                return {"type": "http.disconnect"}
            async def snd(msg):
                pass
            return asyncio.create_task(app(scope, rec, snd))

        task1 = await connect_client("token-tenant-alpha")
        task2 = await connect_client("token-tenant-beta")

        try:
            for _ in range(20):
                await asyncio.sleep(0.01)
                has_alpha = any(t == "tenant-alpha-uuid" for t in _sse_session_tenants.values())
                has_beta = any(t == "tenant-beta-uuid" for t in _sse_session_tenants.values())
                if has_alpha and has_beta:
                    break

            session_alpha = next(s for s, t in _sse_session_tenants.items() if t == "tenant-alpha-uuid")
            session_beta = next(s for s, t in _sse_session_tenants.items() if t == "tenant-beta-uuid")

            headers = {
                "Authorization": "Bearer test-valid-token",
                "Content-Type": "application/json"
            }

            # Post for tenant alpha
            res1 = mcp_test_client.post(f"/messages/?session_id={session_alpha}", headers=headers, json={"id": 1})
            assert res1.status_code == 200
            assert captured_tenants[-1] == "tenant-alpha-uuid"

            # Post for tenant beta
            res2 = mcp_test_client.post(f"/messages/?session_id={session_beta}", headers=headers, json={"id": 2})
            assert res2.status_code == 200
            assert captured_tenants[-1] == "tenant-beta-uuid"

            # Assert they are different and isolated
            assert captured_tenants == ["tenant-alpha-uuid", "tenant-beta-uuid"]
            assert captured_tenants[0] != captured_tenants[1]
        finally:
            task1.cancel()
            task2.cancel()
            try:
                await task1
                await task2
            except (asyncio.CancelledError, BaseException):
                pass

def test_post_messages_unknown_or_expired_session_returns_401(mcp_test_client):
    """
    Test: POST /messages/?session_id=<unknown-or-expired> -> 401, same error
    shape as other 401s (no leak of whether the session_id format was almost right).
    """
    no_auth_res = mcp_test_client.get("/mcp")
    expected_body = no_auth_res.json()

    mock_claims = {
        "sub": "user_123",
        "aud": "digital-invoice-web",
        "tenant_id": "claims-tenant-uuid"
    }
    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims):

        headers = {
            "Authorization": "Bearer mock-valid-token",
            "Content-Type": "application/json"
        }

        # Unknown / non-existent session_id
        res_unknown = mcp_test_client.post("/messages/?session_id=unknown-session-hex-12345", json={}, headers=headers)
        assert res_unknown.status_code == 401
        assert res_unknown.json() == expected_body
        assert res_unknown.json()["error"] == "unauthorized"

        # Missing session_id query param
        res_missing = mcp_test_client.post("/messages/", json={}, headers=headers)
        assert res_missing.status_code == 401
        assert res_missing.json() == expected_body
        assert res_missing.json()["error"] == "unauthorized"

@pytest.mark.asyncio
async def test_sse_cleanup_on_disconnect_makes_session_stale(mcp_test_client):
    """
    Test: after an SSE connection closes, its session_id no longer resolves a
    tenant (entry cleaned up) -> subsequent POST to that stale session_id -> 401.
    """
    no_auth_res = mcp_test_client.get("/mcp")
    expected_body = no_auth_res.json()

    mock_claims = {"sub": "user_1", "aud": "digital-invoice-web", "tenant_id": "claims-tid"}
    resolved_tenant = "tenant-disconnect-test"

    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims), \
         patch("server.db_service.get_tenant_id_by_url_token", new_callable=AsyncMock) as mock_lookup:
        mock_lookup.return_value = resolved_tenant

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/sse/valid-token-for-cleanup",
            "raw_path": b"/sse/valid-token-for-cleanup",
            "query_string": b"",
            "headers": [
                (b"authorization", b"Bearer test-valid-token"),
                (b"host", b"testserver"),
            ]
        }

        async def receive():
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        task = asyncio.create_task(app(scope, receive, send))

        # Wait for session to be registered
        for _ in range(20):
            await asyncio.sleep(0.01)
            if any(t == resolved_tenant for t in _sse_session_tenants.values()):
                break

        matching = [s for s, t in _sse_session_tenants.items() if t == resolved_tenant]
        assert len(matching) == 1
        stale_session_id = matching[0]

        # Cancel / close the connection
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, BaseException):
            pass

        # Wait for cleanup
        for _ in range(20):
            await asyncio.sleep(0.01)
            if stale_session_id not in _sse_session_tenants:
                break

        # Confirm session_id removed from in-memory map
        assert stale_session_id not in _sse_session_tenants

        # Subsequent POST with this stale session_id must return 401 (same shape)
        headers = {
            "Authorization": "Bearer test-valid-token",
            "Content-Type": "application/json"
        }
        res = mcp_test_client.post(f"/messages/?session_id={stale_session_id}", headers=headers, json={})
        assert res.status_code == 401
        assert res.json() == expected_body

@pytest.mark.asyncio
async def test_sse_concurrent_connect_race_condition_regression():
    """
    Regression test for the connect_sse session_id capture race condition:
    Patches transport's _security.validate_request to await asyncio.sleep(...)
    for the first of two concurrent connect calls, runs two concurrent
    /sse/{url_token} connections for two different tenants, and asserts both
    end up in _sse_session_tenants with their CORRECT tenant_id.
    """
    url_tokens = {
        "token-tenant-concurrent-1": "tenant-concurrent-1-uuid",
        "token-tenant-concurrent-2": "tenant-concurrent-2-uuid"
    }

    async def mock_lookup(token):
        return url_tokens.get(token)

    call_count = 0
    orig_validate = sse_transport._security.validate_request
    async def delayed_validate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        current = call_count
        if current == 1:
            # Inject delay during first connection's validate_request
            await asyncio.sleep(0.05)
        return await orig_validate(*args, **kwargs)

    mock_claims = {"sub": "user_1", "aud": "digital-invoice-web", "tenant_id": "claims-tid"}
    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims), \
         patch("server.db_service.get_tenant_id_by_url_token", side_effect=mock_lookup), \
         patch.object(sse_transport._security, "validate_request", side_effect=delayed_validate):

        async def connect(token):
            scope = {
                "type": "http",
                "method": "GET",
                "path": f"/sse/{token}",
                "raw_path": f"/sse/{token}".encode(),
                "query_string": b"",
                "headers": [
                    (b"authorization", b"Bearer test-valid-token"),
                    (b"host", b"testserver"),
                ]
            }
            async def rec():
                await asyncio.Event().wait()
                return {"type": "http.disconnect"}
            async def snd(msg):
                pass
            return asyncio.create_task(app(scope, rec, snd))

        task1 = await connect("token-tenant-concurrent-1")
        # Start task2 while task1 is sleeping in validate_request
        await asyncio.sleep(0.01)
        task2 = await connect("token-tenant-concurrent-2")

        try:
            # Wait until both sessions are registered
            for _ in range(30):
                await asyncio.sleep(0.01)
                has_1 = any(t == "tenant-concurrent-1-uuid" for t in _sse_session_tenants.values())
                has_2 = any(t == "tenant-concurrent-2-uuid" for t in _sse_session_tenants.values())
                if has_1 and has_2:
                    break

            # Both tenants must be present and mapped to different sessions
            tenants_in_map = set(_sse_session_tenants.values())
            assert "tenant-concurrent-1-uuid" in tenants_in_map
            assert "tenant-concurrent-2-uuid" in tenants_in_map

            # Confirm mapping is distinct and isolated
            s1 = [s for s, t in _sse_session_tenants.items() if t == "tenant-concurrent-1-uuid"]
            s2 = [s for s, t in _sse_session_tenants.items() if t == "tenant-concurrent-2-uuid"]
            assert len(s1) == 1
            assert len(s2) == 1
            assert s1[0] != s2[0]
        finally:
            task1.cancel()
            task2.cancel()
            try:
                await task1
            except (asyncio.CancelledError, BaseException):
                pass
            try:
                await task2
            except (asyncio.CancelledError, BaseException):
                pass


