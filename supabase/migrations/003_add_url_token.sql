-- ==============================================================================
-- Migration: 003_add_url_token.sql
-- Project: digital-invoice-web (Multi-Tenant Web-MCP Server)
-- Purpose: Add rotatable url_token column to tenants table for per-customer MCP URL routing
-- ==============================================================================

-- 1. Add url_token column (nullable initially)
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS url_token TEXT;

-- 2. Add unique constraint on url_token
ALTER TABLE public.tenants DROP CONSTRAINT IF EXISTS tenants_url_token_unique;
ALTER TABLE public.tenants ADD CONSTRAINT tenants_url_token_unique UNIQUE (url_token);

-- 3. Create index for fast O(1) lookup during MCP request routing
CREATE INDEX IF NOT EXISTS idx_tenants_url_token ON public.tenants(url_token);

COMMENT ON COLUMN public.tenants.url_token IS 'Rotatable random URL token for customer MCP and SSE server routing.';
