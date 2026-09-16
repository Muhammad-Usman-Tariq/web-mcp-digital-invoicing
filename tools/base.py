import time
import functools
import logging
from typing import Callable, Any, Dict
from core.context import get_current_tenant_id
from db.supabase_client import db_service

logger = logging.getLogger("digital-invoice-web.tools")

def mcp_tool_handler(tool_name: str):
    """
    Decorator that enforces:
    1. Tenant scoping verification
    2. Execution timing
    3. Structured JSON output (success=True/False)
    4. Graceful error handling (no stack traces, no leaked credentials)
    5. Asynchronous persistence to tool_call_logs table

    IMPORTANT ARCHITECTURAL NOTE:
    Each tool call operates on a fresh, isolated browser context — no navigation or
    page state persists between separate tool calls. Any tool that needs to read or
    act on a specific page must perform its own complete navigation internally;
    do not design tools that assume a previous tool call already navigated somewhere.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Dict[str, Any]:
            start_time = time.time()
            tenant_id = get_current_tenant_id()

            if not tenant_id:
                duration_ms = int((time.time() - start_time) * 1000)
                err_msg = "Unauthorized: No tenant_id resolved in authentication context."
                await db_service.log_tool_call(None, tool_name, "error", duration_ms, err_msg)
                return {
                    "success": False,
                    "error": err_msg,
                    "error_type": "UnauthorizedError",
                    "duration_ms": duration_ms
                }

            try:
                result = await func(*args, **kwargs)
                duration_ms = int((time.time() - start_time) * 1000)
                await db_service.log_tool_call(tenant_id, tool_name, "success", duration_ms)
                return {
                    "success": True,
                    "data": result,
                    "tenant_id": tenant_id,
                    "duration_ms": duration_ms
                }
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                error_type = type(e).__name__
                error_detail = str(e)
                # Strip out any possible credential leak in error string
                sanitized_detail = error_detail.replace("\n", " ").strip()
                logger.error(f"Tool '{tool_name}' failed for tenant {tenant_id}: {sanitized_detail}")
                await db_service.log_tool_call(tenant_id, tool_name, "error", duration_ms, sanitized_detail)
                return {
                    "success": False,
                    "error": sanitized_detail,
                    "error_type": error_type,
                    "tenant_id": tenant_id,
                    "duration_ms": duration_ms
                }
        return wrapper
    return decorator
