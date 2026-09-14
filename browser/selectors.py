"""
Centralized Route Registry and Locator Reference for Digital Invoicing Software.
Portal URL: https://www.digitalinvoicingsoftware.com

VERIFIED via live authenticated browsing (Claude in Chrome) on 2026-09-14
against the sandbox tenant "Farooq Steel Industries (Private) Limited".

IMPORTANT ARCHITECTURE NOTE:
This site is Next.js + Tailwind CSS with NO semantic class names and NO
data-testid attributes. All CSS-class-based selectors from the previous
version of this file were unverified guesses and are considered unreliable.

Use Playwright's role/text/placeholder-based locators instead, e.g.:
    page.get_by_role("button", name="New Invoice")
    page.get_by_placeholder("Enter email address")
    page.get_by_role("link", name="Reports")
These match the ACTUAL accessibility tree confirmed below and are far more
resistant to visual/styling changes than class selectors.

STILL NOT VERIFIED (do not assume, verify before relying on):
- Full list of Invoice Studio fields below the fold.
- Bulk-select checkboxes for invoices (none were found in the default view —
  bulk_validate_invoices needs re-scoping, possibly to a per-row "Validate"
  action called in a loop instead of a true multi-select).
"""

class PortalRoutes:
    LOGIN = "/login"  # VERIFIED
    DASHBOARD = "/dashboard"
    SCENARIOS_TESTING = "/scenarios-testing"
    BUYERS = "/buyers"
    INVOICES = "/invoices"
    # There is no separate failed/draft invoices page. Filter the same
    # Invoices page via query params instead:
    INVOICES_FAILED = "/invoices?status=failed,validation_failed"
    INVOICES_DRAFT = "/invoices?status=draft"
    REPORTS = "/dashboard/reports"  # NOT "/reports" — verified real path
    USERS = "/users"
    ROLES = "/roles"
    SETTINGS = "/settings"
    SETTINGS_CHANGE_PASSWORD = "/settings/change-password"
    DOCS = "/docs"


class LoginLocators:
    """Confirmed on /login (logged-out state, incognito screenshot). Simple, no surprises."""
    HEADING_TEXT = "Login"
    SUBTITLE_TEXT = "Enter your credentials to access your account"
    EMAIL_INPUT_PLACEHOLDER = "Enter your email"
    PASSWORD_INPUT_PLACEHOLDER = "Enter your pa..."  # visually confirmed as starting "Enter your pa" — almost certainly "Enter your password"; verify exact string when convenient, low risk since placeholder-substring match works either way
    SUBMIT_BUTTON_TEXT = "Login"
    FORGOT_PASSWORD_LINK_TEXT = "Forgot password?"  # partially visible ("...ssword?") next to Password label
    # On successful login, the app redirects to PortalRoutes.DASHBOARD ("/dashboard")
    # — confirmed via a second screenshot showing the Dashboard immediately after submit.
    POST_LOGIN_REDIRECT = "/dashboard"
    # Session-persistence note: after login, use context.storage_state() to capture
    # cookies/localStorage per Section 4 of the build spec — do NOT re-run this
    # login flow on every tool call.


class NavLocators:
    """Sidebar navigation — confirmed via accessibility tree as <a> links with these exact accessible names."""
    DASHBOARD = ("link", "Dashboard")
    SCENARIOS_TESTING = ("link", "Scenarios Testing")
    BUYERS = ("link", "Buyers")
    INVOICES = ("link", "Invoices")
    REPORTS = ("link", "Reports")
    USERS = ("link", "Users")
    ROLES = ("link", "Roles")
    SETTINGS = ("link", "Settings")
    CHANGE_PASSWORD = ("link", "Change Password")
    DOCS = ("link", "Docs")


class DashboardLocators:
    """Confirmed strings on /dashboard — use get_by_text / get_by_role(name=...)."""
    QUICK_ACTION_CREATE_INVOICES = ("link", "Create / view invoices")
    QUICK_ACTION_REPORTS = ("link", "Reports")
    QUICK_ACTION_FAILED = "Failed"  # button text is "Failed (N)" — match with substring/regex
    STAT_TOTAL_INVOICES = "Total Invoices"
    STAT_TOTAL_DRAFT_INVOICES = "Total Draft Invoices"
    STAT_TOTAL_VALIDATED_INVOICES = "Total Validated Invoices"
    STAT_TOTAL_SUBMITTED_INVOICES = "Total Submitted Invoices"
    REFRESH_BUTTON = ("button", "Refresh dashboard")
    FAILED_INVOICES_LINK = ("link", "View failed invoices")  # in Alerts section


class InvoiceListLocators:
    """Confirmed on /invoices — table has NO row checkboxes in default view."""
    IMPORT_BUTTON = ("button", "Import")
    NEW_INVOICE_BUTTON = ("button", "New Invoice")
    REFRESH_BUTTON = ("button", "Refresh")
    DATE_RANGE_COMBOBOX = ("combobox", "All Time")  # opens duration picker, same as Reports
    STATUS_FILTER_COMBOBOX_DEFAULT_TEXT = "All Status"  # shows "N statuses" once changed
    SEARCH_INPUT_PLACEHOLDER = "Search by invoice id, date, type, buyer business name..."
    TABLE_COLUMNS = ["Sr #", "Invoice ID", "Date", "Type", "Buyer", "Invoice Amount", "Status", "Actions"]
    ROW_ACTIONS_BUTTON_TEXT = "Actions"  # one per row, opens a menu
    # Row actions menu items (confirmed exact set — NO "Duplicate" option exists):
    ACTION_MENU_VIEW_DETAILS = "View Details"
    ACTION_MENU_EDIT_INVOICE = "Edit Invoice"
    ACTION_MENU_DELETE_INVOICE = "Delete Invoice"
    ACTION_MENU_VALIDATE = "Validate"


class InvoiceStudioLocators:
    """Confirmed on Edit Invoice ('Invoice Studio') — fields above the fold only."""
    INVOICE_TYPE_DROPDOWN = ("combobox", "Invoice type")  # e.g. current value "Sale Invoice"
    INVOICE_DATE_INPUT = "input[type=date]"  # native date input — the one CSS selector safe to keep, since <input type=date> is a stable HTML semantic, not a styling class
    TODAY_BUTTON = ("button", "Today")
    REFERENCE_NO_INPUT_PLACEHOLDER = "Enter reference number"
    GENERATE_REFERENCE_BUTTON = ("button", "Generate")
    PO_NUMBER_INPUT_PLACEHOLDER = "Enter P.O number"
    MIV_NUMBER_INPUT_PLACEHOLDER = "Enter MIV number"  # placeholder text truncated in captured view — verify exact string before use
    VENDOR_CODE_INPUT_PLACEHOLDER = "Enter vendor code"
    DC_NUMBER_INPUT_PLACEHOLDER = "Enter delivery challan"
    STATUS_BADGE_TEXT_WHILE_EDITING = "Editing draft"
    SAVE_BUTTON = ("button", "Save")


class ReportsLocators:
    """Confirmed on /dashboard/reports."""
    ADVANCED_FILTERS_BUTTON = ("button", "Advanced Filters")
    QUICK_SEARCH_BUTTON = ("button", "Quick Search")
    PRINT_REPORT_BUTTON = ("button", "Print Report")
    EXPORT_CSV_BUTTON = ("button", "Export CSV")
    SELECT_DURATION_BUTTON = ("button", "Select duration")
    CLEAR_SELECTED_DATES_BUTTON = ("button", "Clear selected dates")
    LOAD_REPORTS_BUTTON = ("button", "Load Reports")
    GROUPING_BUTTONS = ["No Grouping", "Date", "Voucher No.", "Invoice #", "Customer", "Sale Type", "Item Name"]

    # Date-range calendar dialog: opens after clicking SELECT_DURATION_BUTTON.
    # Each day cell is a <button> with a fully-spelled accessible name, e.g.:
    #   "Monday, 7 September 2026" (unselected)
    #   "Tuesday, 1 September 2026, selected" (currently in range)
    #   "Today, Monday, 14 September 2026, selected" (today, in range)
    # To pick a date in Playwright:
    #   page.get_by_role("button", name=re.compile(r"7 September 2026"))
    # This is extremely reliable — no class/id guessing needed at all.
    CALENDAR_PREV_MONTH_BUTTON = ("button", "Go to the Previous Month")
    CALENDAR_NEXT_MONTH_BUTTON = ("button", "Go to the Next Month")
    CALENDAR_CLEAR_RANGE_BUTTON = ("button", "Clear range")
    CALENDAR_DAY_NAME_FORMAT = "%A, %-d %B %Y"  # e.g. "Monday, 7 September 2026" — match as substring since ", selected" may be appended


class UsersLocators:
    """Confirmed Add User modal — real fields differ substantially from original assumptions."""
    ADD_USER_BUTTON = ("button", "Add User")
    SEARCH_PLACEHOLDER = "Search users by name, email, or username..."
    # Modal dialog fields (all confirmed via accessibility tree, role=dialog):
    USERNAME_INPUT_PLACEHOLDER = "Enter username"
    FULL_NAME_INPUT_PLACEHOLDER = "Enter full name"
    EMAIL_INPUT_PLACEHOLDER = "Enter email address"       # type=email
    PASSWORD_INPUT_PLACEHOLDER = "Enter secure password"  # type=password — NOT in original spec, admin sets it directly
    COMPANY_COMBOBOX_INDEX = 0   # first combobox in dialog
    ROLE_COMBOBOX_INDEX = 1      # second combobox in dialog
    ACCOUNT_STATUS_SWITCH = ("switch", "Account Status")
    # Submit button text not yet confirmed — was below the fold in captured view; verify before use.
    CONFIRM_BUTTON = ("button", "Create User")


class RolesLocators:
    """Confirmed on /roles."""
    NEW_ROLE_BUTTON = ("button", "New Role")
    TABLE_COLUMNS = ["Role", "Permissions", "Users", "Actions"]
    BUILTIN_ROLE_NAME = "Company Admin"
    BUILTIN_ROLE_BADGE_TEXT = "Built-in"


class SettingsLocators:
    """Confirmed on /settings (Company tab, default view). Products tab exists but not yet inspected."""
    TAB_COMPANY = ("button", "Company")
    TAB_PRODUCTS = ("button", "Products")
    NAME_INPUT_PLACEHOLDER = "Registered business name"
    NTN_INPUT_PLACEHOLDER = "National Tax Number"
    STRN_INPUT_PLACEHOLDER = "Sales Tax Registration No. (STRN)"
    CONTACT_INPUT_PLACEHOLDER = "Phone and email"
    UPLOAD_IMAGE_BUTTON = ("button", "Upload image")
    ADDRESS_INPUT_PLACEHOLDER = "Street, city"
    # Below-the-fold fields confirmed present via get_page_text but not yet
    # matched to exact input placeholders: Province, Further Tax %,
    # Environment, Token, Bank Account Number, Account title, Bank Name,
    # Bank Address, extra-field toggles (Tax Withheld / Extra Tax / Discount /
    # FED Payable / SRO Schedule / SRO Item), FBR given scenarios multi-select,
    # Save button.


class BuyersLocators:
    """Confirmed on /buyers — NOT in the original 7 tool categories; new candidate scope."""
    ADD_NEW_BUYER_BUTTON = ("button", "Add New Buyer")
    TABLE_COLUMNS = ["Business Name", "Address", "Registration Type", "NTN/CNIC", "STRN", "Province", "Status", "Edit"]


# ---------------------------------------------------------------------------
# KNOWN GAPS vs. original planned scope (Category 1-7) — flag before building:
# ---------------------------------------------------------------------------
# 1. duplicate_invoice: NO "Duplicate" action exists anywhere in the Invoices
#    Actions menu (View Details / Edit Invoice / Delete Invoice / Validate
#    only). This tool has no corresponding UI feature — recommend dropping
#    it from scope entirely, unless a "duplicate" flow is found elsewhere
#    (not yet located).
# 2. bulk_validate_invoices: NO row checkboxes were found in the default
#    Invoices table view. Needs re-verification — may require a different
#    view/mode, or may need to be re-scoped to loop the per-row "Validate"
#    action across multiple invoices sequentially instead of a true
#    multi-select bulk action.
# 3. add_new_user: original spec assumed only name/email/role. Real form
#    also requires username, password, and company — the tool's parameter
#    list and Supabase logging schema should be updated accordingly.
#
# LOGIN: fully verified, no surprises. Simple 2-field form (email, password),
# a "Login" submit button, and a "Forgot password?" link. Redirects to
# /dashboard on success — use this to detect a successful check_login_status.
