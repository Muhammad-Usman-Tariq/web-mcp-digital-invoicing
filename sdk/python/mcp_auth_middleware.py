"""
Universal MCP Authentication Middleware (Python / FastAPI / Starlette)

DESIGN PRINCIPLE:
This middleware is 100% LLM-agnostic. It does not know or care whether
Claude Desktop, Cursor, ChatGPT, Gemini, or a custom agent is calling.

Works identically for:
- Mode 1: Dynamic OAuth 2.1 tokens
- Mode 2: Static long-lived API key tokens

REQUIREMENTS:
pip install PyJWT[crypto] requests
"""

import time
import requests
import jwt
from jwt import PyJWKClient
from typing import Optional, Set
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

class McpAuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        jwks_uri: str,
        audience: str,
        revocations_uri: Optional[str] = None,
        jwks_cache_ttl: int = 300,
        revocation_cache_ttl: int = 30,
        clock_skew_seconds: int = 60,
        exempt_paths: Optional[list] = None
    ):
        super().__init__(app)
        self.jwks_uri = jwks_uri
        self.audience = audience
        self.revocations_uri = revocations_uri or jwks_uri.replace('/.well-known/jwks.json', '/revocations')
        self.clock_skew_seconds = clock_skew_seconds
        self.exempt_paths = set(exempt_paths) if exempt_paths else {"/health", "/healthz"}

        # PyJWKClient handles JWKS retrieval and caching
        self.jwks_client = PyJWKClient(jwks_uri, cache_keys=True, max_cached_keys=16)

        # Revocation cache
        self.revocation_cache_ttl = revocation_cache_ttl
        self.revocation_cache_expires_at = 0.0
        self.revoked_client_ids: Set[str] = set()
        self.revoked_jtis: Set[str] = set()

    def _refresh_revocations(self):
        now = time.time()
        if now >= self.revocation_cache_expires_at:
            try:
                resp = requests.get(self.revocations_uri, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    self.revoked_client_ids = set(data.get("revoked_client_ids", []))
                    self.revoked_jtis = set(data.get("revoked_jtis", []))
                    self.revocation_cache_expires_at = now + self.revocation_cache_ttl
            except Exception as e:
                # Retain old cache on transient network error
                pass

    def _is_revoked(self, client_id: str) -> bool:
        if not client_id:
            return False
        self._refresh_revocations()
        return client_id in self.revoked_client_ids

    def _is_jti_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        self._refresh_revocations()
        return jti in self.revoked_jtis

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path == ep or path.startswith(ep.rstrip("/") + "/") for ep in self.exempt_paths):
            return await call_next(request)

        token = None

        # 1. Check standard Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                token = parts[1].strip()

        # 2. Check static x-api-key header (Mode 2)
        if not token:
            token = request.headers.get("x-api-key") or request.headers.get("x-mcp-api-key")

        # 3. Check query param (for SSE / Stream transport)
        if not token and "access_token" in request.query_params:
            token = request.query_params["access_token"]

        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "error_description": "Missing authentication token. Provide Bearer or x-api-key header."
                },
                headers={"WWW-Authenticate": f'Bearer realm="{self.audience}", error="unauthorized"'}
            )

        try:
            # 1. Fetch matching signing key from JWKS
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)

            # 2. Verify RS256 signature, audience, and expiration
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                leeway=self.clock_skew_seconds
            )

            # 3. Check revocation status (client-level and individual token JTI)
            client_id = payload.get("client_id") or payload.get("sub")
            if self._is_revoked(client_id):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "invalid_token",
                        "error_description": f'Client "{client_id}" has been revoked.'
                    },
                    headers={"WWW-Authenticate": f'Bearer realm="{self.audience}", error="invalid_token"'}
                )

            jti = payload.get("jti")
            if self._is_jti_revoked(jti):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "invalid_token",
                        "error_description": "Token has been revoked or rotated."
                    },
                    headers={"WWW-Authenticate": f'Bearer realm="{self.audience}", error="invalid_token"'}
                )

            # Attach auth state to request
            request.state.auth = payload
            request.state.mcp_client_id = client_id

            return await call_next(request)

        except jwt.ExpiredSignatureError:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "error_description": "Token has expired."},
                headers={"WWW-Authenticate": f'Bearer realm="{self.audience}", error="invalid_token"'}
            )
        except jwt.InvalidAudienceError:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "error_description": f'Audience mismatch. Expected "{self.audience}".'},
                headers={"WWW-Authenticate": f'Bearer realm="{self.audience}", error="invalid_token"'}
            )
        except Exception as e:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "error_description": str(e)},
                headers={"WWW-Authenticate": f'Bearer realm="{self.audience}", error="invalid_token"'}
            )
