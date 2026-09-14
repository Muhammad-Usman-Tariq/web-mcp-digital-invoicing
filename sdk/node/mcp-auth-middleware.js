/**
 * Universal MCP Authentication Middleware (Node.js)
 * 
 * DESIGN PRINCIPLE:
 * This middleware is 100% LLM-agnostic. It does not know or care whether
 * Claude Desktop, Cursor, ChatGPT, Gemini, or a custom agent is calling.
 * 
 * Works identically for:
 * - Mode 1: Dynamic OAuth 2.1 tokens
 * - Mode 2: Static long-lived API key tokens
 * 
 * ZERO EXTERNAL DEPENDENCIES:
 * Built purely on Node.js standard modules (`crypto`, `http`, `https`).
 */

const crypto = require('crypto');
const http = require('http');
const https = require('https');
const { URL } = require('url');

/**
 * Creates the MCP Authentication Middleware for Express / Connect / HTTP servers.
 *
 * @param {Object} options
 * @param {string} options.jwksUri - Full URL to central auth server JWKS endpoint (e.g. 'http://localhost:3000/.well-known/jwks.json')
 * @param {string} options.audience - Expected audience for this MCP server (e.g. 'mcp-invoicing')
 * @param {string} [options.revocationsUri] - Optional URL to revocation list endpoint (e.g. 'http://localhost:3000/revocations')
 * @param {number} [options.jwksCacheTtlMs=300000] - JWKS cache TTL (default 5 minutes)
 * @param {number} [options.revocationCacheTtlMs=30000] - Revocation list cache TTL (default 30 seconds)
 * @param {number} [options.clockSkewSeconds=60] - Allowed clock skew for expiration
 */
function createMcpAuthMiddleware(options) {
  if (!options || !options.jwksUri || !options.audience) {
    throw new Error('[McpAuth] Both `jwksUri` and `audience` options are required.');
  }

  const {
    jwksUri,
    audience,
    revocationsUri = options.jwksUri.replace('/.well-known/jwks.json', '/revocations'),
    jwksCacheTtlMs = 5 * 60 * 1000,
    revocationCacheTtlMs = 30 * 1000,
    clockSkewSeconds = 60
  } = options;

  let keyCache = {
    keys: new Map(),
    expiresAt: 0
  };

  let revocationCache = {
    revokedClientIds: new Set(),
    revokedJtis: new Set(),
    expiresAt: 0
  };

  // HTTP GET JSON Helper (Standard Library only)
  function fetchJson(urlStr) {
    return new Promise((resolve, reject) => {
      const url = new URL(urlStr);
      const client = url.protocol === 'https:' ? https : http;

      const req = client.get(url, (res) => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          return reject(new Error(`HTTP ${res.statusCode} fetching ${urlStr}`));
        }
        let raw = '';
        res.on('data', (chunk) => (raw += chunk));
        res.on('end', () => {
          try {
            resolve(JSON.parse(raw));
          } catch (e) {
            reject(new Error(`Failed to parse JSON response from ${urlStr}`));
          }
        });
      });

      req.on('error', reject);
      req.setTimeout(5000, () => {
        req.destroy();
        reject(new Error(`Timeout fetching ${urlStr}`));
      });
    });
  }

  // Refresh JWKS Public Key Cache
  async function getPublicKey(kid) {
    const now = Date.now();
    if (now < keyCache.expiresAt && keyCache.keys.has(kid)) {
      return keyCache.keys.get(kid);
    }

    try {
      const jwks = await fetchJson(jwksUri);
      if (!jwks || !Array.isArray(jwks.keys)) {
        throw new Error('Invalid JWKS payload');
      }

      keyCache.keys.clear();
      for (const jwk of jwks.keys) {
        if (jwk.kty === 'RSA') {
          const keyObject = crypto.createPublicKey({ key: jwk, format: 'jwk' });
          keyCache.keys.set(jwk.kid, keyObject);
        }
      }
      keyCache.expiresAt = now + jwksCacheTtlMs;

      if (kid && keyCache.keys.has(kid)) {
        return keyCache.keys.get(kid);
      }
      // If no kid match, return first key as fallback if single key
      if (keyCache.keys.size === 1) {
        return keyCache.keys.values().next().value;
      }
      return null;
    } catch (err) {
      console.error('[McpAuth] Failed to refresh JWKS:', err.message);
      return keyCache.keys.get(kid) || null;
    }
  }

  // Refresh Revocation Cache
  async function refreshRevocations() {
    if (!revocationsUri) return;
    const now = Date.now();

    if (now >= revocationCache.expiresAt) {
      try {
        const data = await fetchJson(revocationsUri);
        if (data) {
          if (Array.isArray(data.revoked_client_ids)) {
            revocationCache.revokedClientIds = new Set(data.revoked_client_ids);
          }
          if (Array.isArray(data.revoked_jtis)) {
            revocationCache.revokedJtis = new Set(data.revoked_jtis);
          }
          revocationCache.expiresAt = now + revocationCacheTtlMs;
        }
      } catch (err) {
        // Soft fail on network issue, preserve existing cache
      }
    }
  }

  async function isClientRevoked(clientId) {
    if (!clientId) return false;
    await refreshRevocations();
    return revocationCache.revokedClientIds.has(clientId);
  }

  async function isJtiRevoked(jti) {
    if (!jti) return false;
    await refreshRevocations();
    return revocationCache.revokedJtis.has(jti);
  }

  // Pure Node JWT Verification
  async function verifyJwt(token) {
    const parts = token.split('.');
    if (parts.length !== 3) {
      throw new Error('Malformed token structure');
    }

    const [headerB64, payloadB64, signatureB64] = parts;

    // Decode Header & Payload
    let header, payload;
    try {
      header = JSON.parse(Buffer.from(headerB64, 'base64url').toString('utf8'));
      payload = JSON.parse(Buffer.from(payloadB64, 'base64url').toString('utf8'));
    } catch (e) {
      throw new Error('Invalid token JSON encoding');
    }

    if (header.alg !== 'RS256') {
      throw new Error(`Unsupported signature algorithm: ${header.alg}. Only RS256 is accepted.`);
    }

    // Retrieve public key from JWKS
    const publicKey = await getPublicKey(header.kid);
    if (!publicKey) {
      throw new Error(`Public key not found in JWKS for kid: ${header.kid}`);
    }

    // Verify RS256 signature
    const verifier = crypto.createVerify('RSA-SHA256');
    verifier.update(`${headerB64}.${payloadB64}`);
    const signature = Buffer.from(signatureB64, 'base64url');

    const isValid = verifier.verify(publicKey, signature);
    if (!isValid) {
      throw new Error('Invalid token cryptographic signature');
    }

    // Verify Audience
    const aud = payload.aud;
    const audMatches = Array.isArray(aud) ? aud.includes(audience) : aud === audience;
    if (!audMatches) {
      throw new Error(`Audience mismatch. Token aud: "${aud}", expected: "${audience}"`);
    }

    // Verify Expiration
    const nowSeconds = Math.floor(Date.now() / 1000);
    if (payload.exp && (nowSeconds - clockSkewSeconds) > payload.exp) {
      throw new Error(`Token expired at ${new Date(payload.exp * 1000).toISOString()}`);
    }

    // Verify Revocation (Client-level and JTI-level)
    const clientId = payload.client_id || payload.sub;
    if (await isClientRevoked(clientId)) {
      throw new Error(`Client "${clientId}" has been revoked by the administrator`);
    }

    if (payload.jti && await isJtiRevoked(payload.jti)) {
      throw new Error('Token has been revoked or rotated');
    }

    return payload;
  }

  // Return Express / Connect Middleware
  return async function mcpAuthMiddleware(req, res, next) {
    let token = null;

    // 1. Check standard Authorization: Bearer <token>
    const authHeader = req.headers.authorization || req.headers.Authorization;
    if (authHeader) {
      const parts = authHeader.split(' ');
      if (parts.length === 2 && parts[0].toLowerCase() === 'bearer') {
        token = parts[1].trim();
      }
    }

    // 2. Fallback: Check static x-api-key / x-mcp-api-key headers (Mode 2)
    if (!token) {
      token = req.headers['x-api-key'] || req.headers['x-mcp-api-key'];
    }

    // 3. Fallback: URL query parameter for SSE or Stream transports
    if (!token && req.query && req.query.access_token) {
      token = req.query.access_token;
    }

    if (!token) {
      res.setHeader('WWW-Authenticate', `Bearer realm="${audience}", error="unauthorized"`);
      return res.status(401).json({
        error: 'unauthorized',
        error_description: 'Missing authentication token. Provide Bearer token or x-api-key header.'
      });
    }

    try {
      const payload = await verifyJwt(token);
      // Attach verified auth context to request object
      req.auth = payload;
      req.mcpClient = {
        clientId: payload.client_id || payload.sub,
        audience: payload.aud,
        authMode: payload.auth_mode,
        jti: payload.jti
      };
      next();
    } catch (err) {
      res.setHeader('WWW-Authenticate', `Bearer realm="${audience}", error="invalid_token", error_description="${err.message}"`);
      return res.status(401).json({
        error: 'invalid_token',
        error_description: err.message
      });
    }
  };
}

module.exports = {
  createMcpAuthMiddleware
};
