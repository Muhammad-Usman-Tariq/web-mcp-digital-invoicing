-- ==============================================================================
-- Migration: 002_tenant_id_to_text.sql
-- Project: digital-invoice-web (Multi-Tenant Web-MCP Server)
-- Purpose: Change tenant_id / tenants.id column types from UUID to TEXT
--          to support Central Auth's custom sub claims (e.g. mcp_web-mcp-invoicin_...)
-- ==============================================================================

-- 1. Drop existing foreign key constraints
ALTER TABLE public.tenant_credentials DROP CONSTRAINT IF EXISTS tenant_credentials_tenant_id_fkey;
ALTER TABLE public.tenant_sessions DROP CONSTRAINT IF EXISTS tenant_sessions_tenant_id_fkey;
ALTER TABLE public.tool_call_logs DROP CONSTRAINT IF EXISTS tool_call_logs_tenant_id_fkey;

-- 2. Drop default UUID generator on tenants.id if present
ALTER TABLE public.tenants ALTER COLUMN id DROP DEFAULT;

-- 3. Alter column types from UUID to TEXT
ALTER TABLE public.tenants ALTER COLUMN id TYPE TEXT;
ALTER TABLE public.tenant_credentials ALTER COLUMN tenant_id TYPE TEXT;
ALTER TABLE public.tenant_sessions ALTER COLUMN tenant_id TYPE TEXT;
ALTER TABLE public.tool_call_logs ALTER COLUMN tenant_id TYPE TEXT;

-- 4. Recreate foreign key constraints with original CASCADE / SET NULL rules
ALTER TABLE public.tenant_credentials
    ADD CONSTRAINT tenant_credentials_tenant_id_fkey
    FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE public.tenant_sessions
    ADD CONSTRAINT tenant_sessions_tenant_id_fkey
    FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE public.tool_call_logs
    ADD CONSTRAINT tool_call_logs_tenant_id_fkey
    FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.tenants.id IS 'Arbitrary string identifier matching Central Auth sub/tenant_id claim.';
COMMENT ON COLUMN public.tenant_credentials.tenant_id IS 'Arbitrary string identifier matching Central Auth sub/tenant_id claim.';
