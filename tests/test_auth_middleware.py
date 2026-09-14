import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from sdk.python.mcp_auth_middleware import McpAuthMiddleware

def test_unauthenticated_request_returns_401():
    app = FastAPI()
    app.add_middleware(
        McpAuthMiddleware,
        jwks_uri="https://example.com/.well-known/jwks.json",
        audience="digital-invoice-web"
    )

    @app.get("/protected")
    def protected():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    client = TestClient(app)

    # 1. Unauthenticated request to protected endpoint -> 401
    res = client.get("/protected")
    assert res.status_code == 401
    data = res.json()
    assert data["error"] == "unauthorized"
    assert "WWW-Authenticate" in res.headers

    # 2. Unauthenticated request to exempt /health -> 200
    health_res = client.get("/health")
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "ok"
