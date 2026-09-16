import pytest
from server import mcp
from core.context import clear_context, set_current_auth_claims
from tools.foundation import check_login_status

@pytest.mark.asyncio
async def test_all_tools_registered():
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    
    expected_tools = [
        "tool_check_login_status",
        "tool_navigate_to_section",
        "tool_get_page_text",
        "tool_take_screenshot",
        "tool_get_dashboard_snapshot",
        "tool_list_draft_invoices",
        "tool_get_failed_invoices_details",
        "tool_filter_report_by_date_range",
        "tool_bulk_validate_invoices",
        "tool_edit_draft_invoice_field",
        "tool_add_new_user",
        "tool_duplicate_invoice",
        "tool_export_report_view",
        "tool_list_buyers"
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

@pytest.mark.asyncio
async def test_duplicate_invoice_reports_feature_not_supported():
    from tools.invoices import duplicate_invoice
    set_current_auth_claims({"tenant_id": "test-tenant-123"})
    res = await duplicate_invoice(invoice_id="INV-999")
    assert res["success"] is False
    assert res["error_type"] == "NotImplementedError"
    assert "not supported in the portal UI" in res["error"]
    clear_context()

def test_calendar_date_formatter():
    from tools.reports import _format_calendar_date
    assert _format_calendar_date("2026-09-07") == "7 September 2026"
    assert _format_calendar_date("2026-09-14") == "14 September 2026"


def test_middleware_order_resolves_tenant_id_from_auth_state():
    """
    Regression test for middleware ordering:
    Asserts that when an authenticated request passes through the app middleware stack,
    McpAuthMiddleware sets request.state.auth BEFORE extract_tenant_context runs,
    allowing get_current_tenant_id() to resolve the value from the token's claims.
    """
    from server import app
    from core.context import get_current_tenant_id
    from starlette.testclient import TestClient
    from unittest.mock import MagicMock, patch

    captured_tenant_id = None

    @app.get("/_test_middleware_order")
    async def _test_handler():
        nonlocal captured_tenant_id
        captured_tenant_id = get_current_tenant_id()
        return {"resolved_tenant_id": captured_tenant_id}

    mock_claims = {
        "sub": "some-client-id",
        "aud": "digital-invoice-web"
    }

    with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=MagicMock(key="fake-key")), \
         patch("jwt.decode", return_value=mock_claims):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/_test_middleware_order", headers={"Authorization": "Bearer mock-token"})
        assert response.status_code == 200
        assert captured_tenant_id == "some-client-id"
        assert response.json()["resolved_tenant_id"] == "some-client-id"


@pytest.mark.asyncio
async def test_close_blocking_overlays_handles_frames_and_dismissal():
    from unittest.mock import AsyncMock, MagicMock
    from browser.manager import close_blocking_overlays

    mock_page = MagicMock()
    mock_frame = MagicMock()
    mock_frame.url = "https://example.com/widget"
    mock_frame.name = "scenario-frame"
    mock_page.frames = [mock_frame]

    # Overlay heading inside frame
    mock_frame_overlay = AsyncMock()
    mock_frame_overlay.is_visible.return_value = True
    mock_frame.get_by_text.return_value.first = mock_frame_overlay

    mock_frame_close = AsyncMock()
    mock_frame_close.is_visible.return_value = True
    mock_frame.locator.return_value.first = mock_frame_close

    # Top level overlay heading not visible
    mock_top_overlay = AsyncMock()
    mock_top_overlay.is_visible.return_value = False
    mock_page.get_by_text.return_value.first = mock_top_overlay

    mock_page.wait_for_timeout = AsyncMock()

    await close_blocking_overlays(mock_page)

    mock_frame_close.click.assert_awaited_once_with(force=True)


def test_draft_invoice_helpers():
    from tools.invoices import _date_matches, _amount_matches

    # Date matching across formats
    assert _date_matches("2026-09-07", "07-Sep-2026") is True
    assert _date_matches("07-Sep-2026", "07-Sep-2026") is True
    assert _date_matches("7-Sep-2026", "07-Sep-2026") is True
    assert _date_matches("2026-09-04", "04-Sep-2026") is True
    assert _date_matches("2026-09-01", "04-Sep-2026") is False

    # Amount matching with float tolerance
    assert _amount_matches(42480.0, "42480.00") is True
    assert _amount_matches(42480, "42,480.00") is True
    assert _amount_matches(1180.0, "1180.00") is True
    assert _amount_matches(500.0, "1180.00") is False
    assert _amount_matches(None, "1180.00") is True

