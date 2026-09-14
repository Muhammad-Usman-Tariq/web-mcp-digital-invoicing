"""
Centralized DOM Selectors and Route Registry for Digital Invoicing Software.
Portal URL: https://www.digitalinvoicingsoftware.com

NOTE: Per specification, live selectors must be verified using the test/sandbox account.
Candidate selectors and accessibility fallbacks are structured here for easy refinement.
"""

class PortalRoutes:
    LOGIN = "/login"
    DASHBOARD = "/dashboard"
    INVOICES = "/invoices"
    FAILED_INVOICES = "/invoices/failed"
    DRAFT_INVOICES = "/invoices/draft"
    REPORTS = "/reports"
    USERS = "/users"
    SETTINGS = "/settings"

class LoginSelectors:
    # Multiple fallback candidates for robust matching
    EMAIL_INPUT = [
        "input[type='email']",
        "input[name='email']",
        "input#email",
        "input[placeholder*='email' i]",
        "input[name='username']",
        "#username"
    ]
    PASSWORD_INPUT = [
        "input[type='password']",
        "input[name='password']",
        "input#password",
        "input[placeholder*='password' i]"
    ]
    SUBMIT_BUTTON = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Log in')",
        "button:has-text('Sign in')",
        "button:has-text('Login')",
        ".login-btn",
        "#login-button"
    ]
    LOGIN_ERROR_MESSAGE = [
        ".alert-danger",
        ".error-message",
        "[role='alert']",
        ".toast-error",
        ".text-red-500",
        ".invalid-feedback"
    ]
    LOGGED_IN_INDICATOR = [
        "a[href*='logout']",
        "button:has-text('Log out')",
        "button:has-text('Logout')",
        ".user-profile",
        ".avatar",
        "#user-dropdown",
        "[data-testid='user-menu']"
    ]

class DashboardSelectors:
    METRIC_CARDS = [
        ".stat-card",
        ".metric-card",
        "[data-testid='metric-card']",
        ".dashboard-card",
        ".card"
    ]
    QUICK_LINKS = [
        ".quick-links a",
        ".dashboard-actions a",
        "nav a",
        ".sidebar a"
    ]
    ACTIVITY_FEED = [
        ".recent-activity",
        ".activity-list",
        "#recent-invoices"
    ]

class InvoiceSelectors:
    TABLE = [
        "table.invoices-table",
        "table[data-testid='invoices-table']",
        "table",
        "[role='table']"
    ]
    TABLE_ROWS = [
        "tbody tr",
        "[role='row']"
    ]
    FAILED_REASON = [
        ".error-reason",
        ".badge-danger",
        ".text-danger",
        "[data-col='error']",
        "td:nth-child(5)"
    ]
    ROW_CHECKBOX = [
        "input[type='checkbox']",
        ".row-selector input",
        "[data-testid='select-row']"
    ]
    BULK_VALIDATE_BUTTON = [
        "button:has-text('Validate Selected')",
        "button:has-text('Bulk Validate')",
        "button:has-text('Validate')",
        "#bulk-validate",
        "[data-testid='bulk-validate-btn']"
    ]
    DUPLICATE_ACTION_BUTTON = [
        "button:has-text('Duplicate')",
        "a:has-text('Duplicate')",
        "[title='Duplicate']",
        "[aria-label='Duplicate']"
    ]
    SAVE_INVOICE_BUTTON = [
        "button:has-text('Save')",
        "button:has-text('Save Draft')",
        "button[type='submit']",
        "#save-invoice"
    ]

class ReportSelectors:
    DATE_FROM_INPUT = [
        "input[name='from_date']",
        "input[name='start_date']",
        "input#from-date",
        "input#start-date",
        "input[placeholder*='from' i]",
        "input[placeholder*='start' i]"
    ]
    DATE_TO_INPUT = [
        "input[name='to_date']",
        "input[name='end_date']",
        "input#to-date",
        "input#end-date",
        "input[placeholder*='to' i]",
        "input[placeholder*='end' i]"
    ]
    APPLY_FILTER_BUTTON = [
        "button:has-text('Apply')",
        "button:has-text('Filter')",
        "button:has-text('Search')",
        "#filter-reports-btn"
    ]
    EXPORT_BUTTON = [
        "button:has-text('Export')",
        "a:has-text('Export')",
        "button:has-text('Download')",
        "#export-report"
    ]
    REPORT_TABLE = [
        "table.reports-table",
        "table",
        "[role='table']"
    ]

class UserSelectors:
    ADD_USER_BUTTON = [
        "button:has-text('Add User')",
        "a:has-text('Add User')",
        "button:has-text('New User')",
        "#add-user-btn"
    ]
    USER_NAME_INPUT = [
        "input[name='name']",
        "input[name='full_name']",
        "#user-name",
        "#name"
    ]
    USER_EMAIL_INPUT = [
        "input[name='email']",
        "input[type='email']",
        "#user-email",
        "#email"
    ]
    USER_ROLE_SELECT = [
        "select[name='role']",
        "#user-role",
        "select"
    ]
    CONFIRM_BUTTON = [
        "button:has-text('Confirm')",
        "button:has-text('Save')",
        "button:has-text('Create')",
        "button[type='submit']"
    ]
    CONFIRMATION_DIALOG = [
        "[role='dialog']",
        ".modal",
        ".swal2-modal",
        ".confirmation-dialog"
    ]
