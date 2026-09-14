# `digital-invoice-web` — Independent Web-MCP Server

A standalone, multi-tenant Model Context Protocol (MCP) server that automates UI-only operations on [Digital Invoicing Software](https://www.digitalinvoicingsoftware.com) using Playwright browser automation, FastAPI, and Central Auth token verification.

---

## 1. Architectural Highlights

- **Zero Coupling**: Operates completely independently from any backend invoicing API servers. No shared databases, imports, or session states.
- **Strict Multi-Tenancy**: Every tool call resolves the calling tenant strictly from the Central Auth JWT `tenant_id` claim. Browser contexts, cookies, and credentials are completely isolated per tenant.
- **Session Caching**: Playwright `storage_state` (cookies and localStorage) is encrypted at rest in Supabase (`AES-256-GCM`), reusing authenticated sessions to eliminate repetitive logins while falling back cleanly to UI login on session expiration.
- **Concurrency & Resource Protection**: Limits active concurrent browser contexts via an asyncio semaphore to protect VPS RAM and CPU.

---

## 2. Registering Audience with Central Auth

This server sits behind the Central Auth server and verifies incoming JWT tokens using the official drop-in `McpAuthMiddleware`.

1. Open your **Central Auth Server Admin Console** (or API).
2. Register a new MCP Server:
   - **Server Name**: `Digital Invoice Web MCP`
   - **Audience**: `digital-invoice-web` *(must match `MCP_AUTH_AUDIENCE` in your `.env`)*
   - **Server URL**: `https://web-mcp.<your-domain>/sse` (or Streamable HTTP `/mcp`)
   - **Required Token Claims**: Ensure `tenant_id` is included in token payloads.
3. Keep the audience distinct from any other server (e.g. `digital-invoice-api`) to prevent cross-token usage.

---

## 3. Required Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Server & Port
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO

# Central Auth (JWKS)
JWKS_URI=https://t91cvjn5boilhilaixggt5y9.s0226.digitalsofts.com/.well-known/jwks.json
MCP_AUTH_AUDIENCE=digital-invoice-web
REVOCATIONS_URI=https://t91cvjn5boilhilaixggt5y9.s0226.digitalsofts.com/revocations

# Supabase (Database & RLS)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key

# Cryptography (AES-256-GCM)
# Generate with: python scripts/generate_master_key.py
ENCRYPTION_MASTER_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
CURRENT_KEY_VERSION=1

# Playwright Browser Automation
PORTAL_BASE_URL=https://www.digitalinvoicingsoftware.com
HEADLESS=true
MAX_CONCURRENT_BROWSERS=3
NAVIGATION_TIMEOUT_MS=20000
ACTION_TIMEOUT_MS=15000
SESSION_TTL_HOURS=24
```

---

## 4. Supabase Database Setup

Run the SQL migration in your Supabase SQL Editor:

- File: [`supabase/migrations/001_initial_schema.sql`](supabase/migrations/001_initial_schema.sql)

This script provisions:
1. `tenants`: Registered organizations and active kill-switch status.
2. `tenant_credentials`: AES-256-GCM encrypted portal login credentials.
3. `tenant_sessions`: Encrypted Playwright `storage_state` caching.
4. `tool_call_logs`: Execution audit and diagnostic error logging.
5. Row-Level Security (RLS) policies on all tables.

---

## 5. Onboarding a New Tenant's Credentials

Use the provided CLI onboarding utility:

```bash
# 1. Generate an encryption master key (if not already set in .env):
python scripts/generate_master_key.py

# 2. Add tenant credentials to Supabase:
python scripts/add_tenant.py \
  --tenant-id "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11" \
  --company-name "Acme Logistics Inc" \
  --email "billing@acme.com" \
  --password "SecurePassword123!"
```

*(You can also run `python scripts/add_tenant.py` without arguments for interactive masked input).*

---

## 6. Local Development & Testing

```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate

# 2. Install dependencies & Playwright browser
pip install -r requirements.txt
playwright install --with-deps chromium

# 3. Run automated tests
python -m pytest -v tests

# 4. Start local server
python main.py
```

Server endpoints:
- **SSE Stream**: `http://localhost:8000/sse`
- **SSE Messages**: `http://localhost:8000/messages`
- **Streamable HTTP**: `http://localhost:8000/mcp`
- **Health Check**: `http://localhost:8000/health` (unauthenticated)

---

## 7. Deployment on Coolify (VPS)

1. Create a new service in your Coolify dashboard: **Application -> Dockerfile**.
2. Point Coolify to this repository.
3. Set your custom subdomain (e.g. `web-mcp.yourdomain.com`).
4. Paste all environment variables from Section 3 into Coolify's **Environment Variables** tab.
5. Deploy. The Dockerfile automatically handles:
   - System Chromium dependencies (`playwright install --with-deps chromium`).
   - Unprivileged user permissions.
   - Built-in container health checks on `/health`.

---

## 8. Exposed MCP Tools

| Tool | Category | Description |
|---|---|---|
| `tool_check_login_status` | Plumbing | Verifies active session on portal |
| `tool_navigate_to_section` | Plumbing | Direct navigation to portal sections |
| `tool_get_page_text` | Diagnostic | Returns visible DOM text for element discovery |
| `tool_take_screenshot` | Diagnostic | Returns base64 PNG data URL of current view |
| `tool_get_dashboard_snapshot` | High | Scrapes overview metrics and quick links |
| `tool_get_failed_invoices_details` | High | Extracts failed invoices with error reasons |
| `tool_filter_report_by_date_range` | High | Applies date-picker filters and returns report table |
| `tool_bulk_validate_invoices` | Medium | Checks invoice checkboxes and triggers validation |
| `tool_edit_draft_invoice_field` | Medium | Edits specified draft invoice field and saves |
| `tool_add_new_user` | Medium | Fills add-user form and handles confirmation dialog |
| `tool_duplicate_invoice` | Low | Triggers invoice duplicate action |
| `tool_export_report_view` | Low | Triggers UI export and captures file download |

---

## 9. DOM Selectors & Discovery Workflow

All selectors are isolated in [`browser/selectors.py`](browser/selectors.py). 

When testing with a live sandbox account:
1. Call `tool_check_login_status` to ensure login is operational.
2. If any element differs from candidate selectors, use `tool_get_page_text` and `tool_take_screenshot` to inspect the live markup.
3. Update [`browser/selectors.py`](browser/selectors.py) with the exact attributes discovered.
