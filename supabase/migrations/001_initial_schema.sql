-- ==============================================================================
-- Migration: 001_initial_schema.sql
-- Project: digital-invoice-web (Multi-Tenant Web-MCP Server)
-- ==============================================================================

-- 1. Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Create tenants table
CREATE TABLE IF NOT EXISTS public.tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.tenants IS 'Stores registered tenant companies matching the tenant_id claim in Central Auth JWTs.';

-- 3. Create tenant_credentials table (AES-256-GCM encrypted credentials)
CREATE TABLE IF NOT EXISTS public.tenant_credentials (
    tenant_id UUID PRIMARY KEY REFERENCES public.tenants(id) ON DELETE CASCADE,
    encrypted_email TEXT NOT NULL,
    encrypted_password TEXT NOT NULL,
    encryption_key_version INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.tenant_credentials IS 'AES-256-GCM encrypted login credentials per tenant. Keys never reside in DB.';

-- 4. Create tenant_sessions table (Playwright storage_state cache)
CREATE TABLE IF NOT EXISTS public.tenant_sessions (
    tenant_id UUID PRIMARY KEY REFERENCES public.tenants(id) ON DELETE CASCADE,
    storage_state JSONB NOT NULL,
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE public.tenant_sessions IS 'Playwright browser storage states (cookies + localStorage) per tenant to skip re-login.';

-- 5. Create tool_call_logs table (Diagnostics & Audit)
CREATE TABLE IF NOT EXISTS public.tool_call_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID REFERENCES public.tenants(id) ON DELETE SET NULL,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'error')),
    duration_ms INT NOT NULL,
    error_detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.tool_call_logs IS 'Diagnostic logs for MCP tool executions, execution times, and errors.';

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_tenant_credentials_tenant_id ON public.tenant_credentials(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_sessions_expires_at ON public.tenant_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_tool_call_logs_tenant_id ON public.tool_call_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tool_call_logs_created_at ON public.tool_call_logs(created_at DESC);

-- Automatic updated_at trigger for credentials
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tenant_credentials_updated_at ON public.tenant_credentials;
CREATE TRIGGER trg_tenant_credentials_updated_at
    BEFORE UPDATE ON public.tenant_credentials
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==============================================================================
-- Row-Level Security (RLS) Configuration
-- ==============================================================================
-- Enable RLS on all tenant-specific tables to enforce strict data isolation.
-- The MCP server connects with the Supabase service_role key which bypasses RLS,
-- but public/anon/authenticated roles will have zero access by default.

ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tool_call_logs ENABLE ROW LEVEL SECURITY;

-- Explicitly deny public / anon access
REVOKE ALL ON public.tenants FROM anon, authenticated;
REVOKE ALL ON public.tenant_credentials FROM anon, authenticated;
REVOKE ALL ON public.tenant_sessions FROM anon, authenticated;
REVOKE ALL ON public.tool_call_logs FROM anon, authenticated;
