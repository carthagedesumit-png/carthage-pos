"""Customer relationship, loyalty, wallet, and credit services."""

from app.customers.customer_service import (
    assign_customer_group,
    create_customer,
    create_customer_group,
    deactivate_customer,
    get_customer_by_id,
    reactivate_customer,
    search_customers,
    search_customer_groups,
    update_customer,
    update_customer_group,
)
from app.customers.credit_service import get_credit_outstanding, make_credit_payment, set_credit_terms
from app.customers.loyalty_service import adjust_loyalty_points, get_loyalty_balance, redeem_loyalty_points
from app.customers.wallet_service import adjust_wallet, deposit_wallet, get_wallet_balance, withdraw_wallet

__all__ = [
    "adjust_loyalty_points", "adjust_wallet", "assign_customer_group",
    "create_customer", "create_customer_group", "deactivate_customer",
    "deposit_wallet", "get_credit_outstanding", "get_customer_by_id",
    "get_loyalty_balance", "get_wallet_balance", "make_credit_payment",
    "reactivate_customer", "redeem_loyalty_points", "search_customer_groups",
    "search_customers", "set_credit_terms", "update_customer",
    "update_customer_group", "withdraw_wallet",
]
