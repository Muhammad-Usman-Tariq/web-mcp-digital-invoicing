# Universal MCP Authentication Middleware (Node.js)

A standalone, drop-in verification middleware for any Node.js MCP server (Express, Fastify, Connect, or raw HTTP).

## Core Principle
**Zero LLM-Specific Code**: Your MCP server code NEVER changes regardless of whether Claude Desktop, Cursor, ChatGPT, Gemini, or a custom agent is calling. The central auth server absorbs all flow variations.

## Key Features
- **Zero External Dependencies**: Built entirely on Node.js standard library (`crypto`, `http`, `https`, `url`).
- **Dual Mode Support**:
  - Mode 1: OAuth 2.1 RS256 Bearer tokens.
  - Mode 2: Static long-lived API key tokens via `x-api-key` header.
- **Local JWKS Verification**: Verifies tokens locally using public RS256 keys cached from `/.well-known/jwks.json`.
- **Instant Revocation Check**: Caches the central auth server's revocation list to reject revoked tokens immediately.

## Quickstart

Copy `mcp-auth-middleware.js` directly into your MCP project.

```javascript
const express = require('express');
const { createMcpAuthMiddleware } = require('./mcp-auth-middleware');

const app = express();
app.use(express.json());

// 1. ADD THIS ONE LINE OF MIDDLEWARE:
app.use(createMcpAuthMiddleware({
  jwksUri: process.env.MCP_AUTH_JWKS_URI || 'http://localhost:3000/.well-known/jwks.json',
  audience: 'mcp-invoicing' // Match your MCP audience identifier
}));

// 2. YOUR MCP SERVER TOOLS & ROUTES (NO AUTH CODE NEEDED):
app.post('/tools/list', (req, res) => {
  // req.mcpClient is populated automatically:
  // { clientId: '...', audience: 'mcp-invoicing', authMode: 'oauth2_code' | 'static_token', jti: '...' }
  res.json({
    tools: [
      { name: 'create_invoice', description: 'Creates an invoice' }
    ]
  });
});

app.post('/tools/call', (req, res) => {
  res.json({ result: 'OK' });
});

app.listen(4000);
```

## Options Reference

| Option | Type | Default | Description |
|---|---|---|---|
| `jwksUri` | `string` | **Required** | URL to Central Auth Server's JWKS endpoint (e.g. `https://auth.domain.com/.well-known/jwks.json`) |
| `audience` | `string` | **Required** | The unique audience string identifying your MCP service (e.g. `mcp-invoicing`) |
| `revocationsUri` | `string` | Auto-derived from `jwksUri` | URL to `/revocations` endpoint for instant revocation checking |
| `jwksCacheTtlMs` | `number` | `300000` (5 min) | JWKS public key cache lifetime in milliseconds |
| `revocationCacheTtlMs` | `number` | `30000` (30 sec) | Revocation list cache lifetime in milliseconds |
| `clockSkewSeconds` | `number` | `60` | Allowed clock skew for expiration checking |
