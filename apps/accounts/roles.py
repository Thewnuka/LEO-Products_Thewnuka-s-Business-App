"""
Roles and capabilities: the single source of truth for "who may do what".

Every user has exactly one primary role (User.role). Code never checks role
names directly to decide access; it asks for a *capability*:

    from apps.accounts.roles import Capability, has_capability
    if has_capability(request.user, Capability.MANAGE_STAFF): ...

Future phases add capabilities here (and grant them to roles below) when
they build each module. Capabilities listed now for modules that do not
exist yet only record the agreed boundaries; nothing uses them until
that module is built.
"""
from django.db import models


class Role(models.TextChoices):
    OWNER = "OWNER", "Owner"
    IT_ADMIN = "IT_ADMIN", "IT Admin"
    MANAGER = "MANAGER", "Manager"
    CASHIER = "CASHIER", "Cashier"
    CUSTOMER = "CUSTOMER", "Customer"


#: Roles that sign in through the staff portal.
STAFF_ROLES = frozenset({Role.OWNER, Role.IT_ADMIN, Role.MANAGER, Role.CASHIER})


class Capability:
    # Staff portal
    VIEW_STAFF_PORTAL = "staff_portal.view"
    VIEW_ALL_DASHBOARDS = "dashboards.view_all"

    # User management
    VIEW_STAFF = "staff.view"
    MANAGE_STAFF = "staff.manage"
    MANAGE_PERMISSIONS = "permissions.manage"

    # Settings & system
    MANAGE_BUSINESS_SETTINGS = "settings.business"
    MANAGE_TECHNICAL_SETTINGS = "settings.technical"
    SYSTEM_MAINTENANCE = "system.maintenance"
    VIEW_SECURITY_LOG = "security_log.view"

    # Operations (modules arrive in later phases)
    MANAGE_CATALOG = "catalog.manage"
    MANAGE_INVENTORY = "inventory.manage"
    MANAGE_SUPPLIERS = "suppliers.manage"
    MANAGE_PURCHASES = "purchases.manage"
    CONFIGURE_STOCK_RULES = "inventory.configure_rules"  # e.g. allow negative stock for an item
    MANAGE_ORDERS = "orders.manage"            # change order status, cancel orders
    VIEW_ORDERS = "orders.view"                # see orders (incl. cashiers at pickup)
    MANAGE_CUSTOMERS = "customers.manage"
    VIEW_OPERATIONAL_REPORTS = "reports.operational"

    # Money
    MANAGE_PAYMENTS = "payments.manage"        # payment configuration and refunds
    VERIFY_PAYMENTS = "payments.verify"        # approve / reject bank-transfer evidence
    RECORD_CASH_PAYMENTS = "payments.record_cash"
    MANAGE_FINANCE = "finance.manage"          # void expenses, supplier payments, stock costs, expense categories
    VIEW_FINANCE = "finance.view"              # finance dashboard, profit & loss, cash flow, balances, audit log
    RECORD_EXPENSES = "finance.record_expenses"
    VIEW_ALL_REPORTS = "reports.all"

    # Point of sale
    USE_POS = "pos.use"
    PROCESS_SALES = "pos.sell"
    ISSUE_RECEIPTS = "pos.receipts"
    TAKE_PAYMENTS = "pos.take_payment"
    VIEW_OWN_TRANSACTIONS = "pos.own_transactions"
    VIEW_POS_SALES = "pos.view_sales"          # every cashier's sales and receipts
    APPROVE_DISCOUNTS = "pos.approve_discounts"  # discounts above the cashier limit (up to the manager limit)
    UNLIMITED_DISCOUNTS = "pos.unlimited_discounts"
    MANAGE_SHIFTS = "pos.manage_shifts"        # review every shift, close a forgotten shift
    REFUND_POS_SALES = "pos.refund"            # void / refund an in-store sale

    # Activity, reviews (Phase 09)
    VIEW_ACTIVITY = "activity.view"            # business activity history
    MODERATE_REVIEWS = "reviews.moderate"      # approve / reject customer product reviews

    # Customer portal
    USE_CUSTOMER_PORTAL = "customer_portal.use"


_C = Capability

_OWNER = {
    _C.VIEW_STAFF_PORTAL, _C.VIEW_ALL_DASHBOARDS,
    _C.VIEW_STAFF, _C.MANAGE_STAFF, _C.MANAGE_PERMISSIONS,
    _C.MANAGE_BUSINESS_SETTINGS, _C.MANAGE_TECHNICAL_SETTINGS, _C.SYSTEM_MAINTENANCE, _C.VIEW_SECURITY_LOG,
    _C.MANAGE_CATALOG, _C.MANAGE_INVENTORY, _C.MANAGE_SUPPLIERS, _C.MANAGE_ORDERS, _C.MANAGE_CUSTOMERS,
    _C.MANAGE_PURCHASES, _C.CONFIGURE_STOCK_RULES, _C.VIEW_ORDERS,
    _C.VIEW_OPERATIONAL_REPORTS,
    _C.MANAGE_PAYMENTS, _C.VERIFY_PAYMENTS, _C.RECORD_CASH_PAYMENTS, _C.MANAGE_FINANCE, _C.VIEW_ALL_REPORTS,
    _C.VIEW_FINANCE, _C.RECORD_EXPENSES,
    _C.USE_POS, _C.PROCESS_SALES, _C.ISSUE_RECEIPTS, _C.TAKE_PAYMENTS, _C.VIEW_OWN_TRANSACTIONS,
    _C.VIEW_POS_SALES, _C.APPROVE_DISCOUNTS, _C.UNLIMITED_DISCOUNTS, _C.MANAGE_SHIFTS, _C.REFUND_POS_SALES,
    _C.VIEW_ACTIVITY, _C.MODERATE_REVIEWS,
}

ROLE_CAPABILITIES = {
    Role.OWNER: frozenset(_OWNER),
    # Technical and user administration, but no money and no business settings.
    Role.IT_ADMIN: frozenset({
        _C.VIEW_STAFF_PORTAL,
        _C.VIEW_STAFF, _C.MANAGE_STAFF,
        _C.MANAGE_TECHNICAL_SETTINGS, _C.SYSTEM_MAINTENANCE, _C.VIEW_SECURITY_LOG,
    }),
    Role.MANAGER: frozenset({
        _C.VIEW_STAFF_PORTAL,
        _C.MANAGE_CATALOG, _C.MANAGE_INVENTORY, _C.MANAGE_SUPPLIERS, _C.MANAGE_ORDERS, _C.MANAGE_CUSTOMERS,
        _C.MANAGE_PURCHASES,
        _C.VIEW_ORDERS, _C.VERIFY_PAYMENTS, _C.RECORD_CASH_PAYMENTS,
        _C.VIEW_OPERATIONAL_REPORTS,
        # Point of sale: oversight, not selling.
        _C.VIEW_POS_SALES, _C.APPROVE_DISCOUNTS, _C.MANAGE_SHIFTS, _C.REFUND_POS_SALES,
        # Finance: operational reports and recording expenses; no profit, cash flow or balances.
        _C.RECORD_EXPENSES,
        # Operational activity history (no account or finance entries) and review moderation.
        _C.VIEW_ACTIVITY, _C.MODERATE_REVIEWS,
    }),
    Role.CASHIER: frozenset({
        _C.VIEW_STAFF_PORTAL,
        _C.USE_POS, _C.PROCESS_SALES, _C.ISSUE_RECEIPTS, _C.TAKE_PAYMENTS, _C.VIEW_OWN_TRANSACTIONS,
        # Online orders: look them up and take cash at pickup; no status changes or verification.
        _C.VIEW_ORDERS, _C.RECORD_CASH_PAYMENTS,
    }),
    Role.CUSTOMER: frozenset({_C.USE_CUSTOMER_PORTAL}),
}

#: Which roles each role may give to accounts it manages.
#: OWNER accounts are never created or edited through the staff screens.
ASSIGNABLE_ROLES = {
    Role.OWNER: (Role.IT_ADMIN, Role.MANAGER, Role.CASHIER),
    Role.IT_ADMIN: (Role.MANAGER, Role.CASHIER),
}


def has_capability(user, capability):
    """True if the user is signed in, active and their role grants the capability."""
    if not (user and user.is_authenticated and user.is_active):
        return False
    return capability in ROLE_CAPABILITIES.get(user.role, frozenset())


def assignable_roles(user):
    """Roles this user may assign to other staff accounts."""
    if not has_capability(user, Capability.MANAGE_STAFF):
        return ()
    return ASSIGNABLE_ROLES.get(user.role, ())


def can_manage_user(actor, target):
    """
    Whether `actor` may edit, (de)activate or reset the password of `target`.

    Never yourself (so nobody can raise their own privileges), never the
    primary owner, and only accounts whose role the actor could assign.
    """
    if actor is None or target is None or actor.pk == target.pk:
        return False
    if target.is_primary_owner:
        return False
    return target.role in assignable_roles(actor)
