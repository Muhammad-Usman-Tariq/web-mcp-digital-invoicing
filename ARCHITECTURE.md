# Architecture & Multi-Tenant Design

## Browser Automation & Context Isolation

The MCP server connects to the Digital Invoicing Software web portal using Playwright (`BrowserManager`).

### Isolated Browser Contexts per Tool Call
- **Fresh Context per Invocation**: Each tool invocation operates inside its own isolated Playwright `BrowserContext` created via `browser_manager.get_tenant_page()`.
- **No Shared Navigation State**: No navigation, DOM state, or page URLs persist between separate tool calls. For example, calling `tool_navigate_to_section` will not leave the browser on that page for a subsequent call to `tool_get_page_text`.
- **Self-Contained Navigation**: Any tool that needs to inspect or interact with a specific page must perform its own complete navigation internally (e.g. `await page.goto(target_url)`). Do not design or rely on tools assuming prior navigation state.

### Multi-Tenant Authentication & Session Reuse
- Tenants authenticate via Central Auth JWT tokens. The `tenant_id` is resolved from the token claims (`sub`).
- Playwright `storage_state` cookies and localStorage are securely encrypted at rest in Supabase and reused across calls for the same tenant.
- If a session expires, the `BrowserManager` automatically performs a seamless background re-login using the tenant's encrypted credentials.

### Draft Invoices Lookup
- In the portal UI, draft invoices do not have an FBR Invoice Number assigned yet (the `INVOICE ID` column is empty).
- Draft invoices are identified and matched by **`buyer_name`** and **`date`** (with **`amount`** as a tiebreaker/disambiguator).
- The `list_draft_invoices` tool should be invoked first to retrieve available draft invoices before editing.
