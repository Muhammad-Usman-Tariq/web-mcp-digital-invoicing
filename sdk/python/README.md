# Universal MCP Authentication Middleware (Python)

A drop-in verification middleware for Python MCP servers built with FastAPI, Starlette, or raw ASGI.

## Prerequisites
```bash
pip install PyJWT[crypto] requests
```

## Quickstart

Copy `mcp_auth_middleware.py` directly into your Python MCP project.

```python
from fastapi import FastAPI, Request
from mcp_auth_middleware import McpAuthMiddleware
import os

app = FastAPI()

# 1. ADD THIS ONE LINE OF MIDDLEWARE:
app.add_middleware(
    McpAuthMiddleware,
    jwks_uri=os.getenv("MCP_AUTH_JWKS_URI", "http://localhost:3000/.well-known/jwks.json"),
    audience="mcp-invoicing"  # Match your MCP audience identifier
)

# 2. YOUR MCP SERVER TOOLS (NO AUTH CODE NEEDED):
@app.post("/tools/list")
async def list_tools(request: Request):
    # request.state.auth contains verified JWT claims
    # request.state.mcp_client_id contains client identifier
    return {
        "tools": [
            {"name": "create_invoice", "description": "Creates an invoice"}
        ]
    }

@app.post("/tools/call")
async def call_tool(request: Request):
    return {"result": "OK"}
```

## Supported Inbound Tokens
- **Mode 1**: Header `Authorization: Bearer <oauth_jwt>`
- **Mode 2**: Header `x-api-key: <static_jwt>`
- **Stream / SSE**: Query parameter `?access_token=<jwt>`
