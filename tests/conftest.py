import os

# Ensure test environment variables are set before any application module import
os.environ.setdefault("MCP_AUTH_AUDIENCE", "digital-invoice-web-test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key-12345")
os.environ.setdefault("ENCRYPTION_MASTER_KEY", "a" * 64)
