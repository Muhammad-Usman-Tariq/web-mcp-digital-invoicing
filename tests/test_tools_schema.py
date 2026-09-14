import pytest
from server import mcp
from core.context import clear_context, set_current_auth_claims
from tools.foundation import check_login_status

@pytest.mark.asyncio
async def test_all_12_tools_registered():
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    
    expected_tools = [
        "tool_check_login_status",
        "tool_navigate_to_section",
        "tool_get_page_text",
        "tool_take_screenshot",
        "tool_get_dashboard_snapshot",
        "tool_get_failed_invoices_details",
        "tool_filter_report_by_date_range",
        "tool_bulk_validate_invoices",
        "tool_edit_draft_invoice_field",
        "tool_add_new_user",
        "tool_duplicate_invoice",
        "tool_export_report_view"
    ]
    
    for tool_name in expected_tools:
        assert tool_name in tool_names, f"Expected tool {tool_name} not found in MCP server."

@pytest.mark.asyncio
async def test_tool_fails_cleanly_without_tenant():
    clear_context()
    # Call tool directly without setting tenant
    result = await check_login_status()
    assert result["success"] is False
    assert result["error_type"] == "UnauthorizedError"
    assert "No tenant_id resolved" in result["error"]
