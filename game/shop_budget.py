"""Per-player daily vendor-credit allowances for direct Shop sales.

The allowance limits how many credits the system shop will pay one character
per UTC day. Buying items never replenishes it, and player auctions do not use
it. Rows are lazily treated as reset when their date is stale, while the
midnight scheduler persists a fresh allowance for every player.
"""

from datetime import datetime

import config_defaults as cfg
from database import execute_one, execute_write, get_all_settings, exclusive_transaction


def daily_vendor_allowance(settings: dict | None = None) -> int:
    """Return the configured non-negative daily allowance."""
    settings = settings or get_all_settings()
    return max(0, int(settings.get(
        "SHOP_DAILY_VENDOR_CREDITS", cfg.SHOP_DAILY_VENDOR_CREDITS
    )))


def get_vendor_credit_balance(player_id: int, settings: dict | None = None) -> int:
    """Return today's remaining vendor credits without requiring a stored row."""
    settings = settings or get_all_settings()
    today = datetime.utcnow().date().isoformat()
    row = execute_one(
        "SELECT credits_remaining, reset_date FROM player_shop_budgets WHERE player_id=?",
        (player_id,),
    )
    if not row or row["reset_date"] != today:
        return daily_vendor_allowance(settings)
    return max(0, int(row["credits_remaining"]))


def debit_vendor_credits(player_id: int, amount: int, settings: dict | None = None) -> int:
    """Deduct a completed direct-sale payment and return the new balance.

    Call this while holding the same exclusive transaction that transfers the
    sold item. This keeps the allowance and inventory change together.
    """
    amount = max(0, int(amount))
    settings = settings or get_all_settings()
    today = datetime.utcnow().date().isoformat()
    allowance = daily_vendor_allowance(settings)
    execute_write(
        """INSERT INTO player_shop_budgets(player_id,credits_remaining,reset_date)
           VALUES(?,?,?)
           ON CONFLICT(player_id) DO UPDATE SET
             credits_remaining=CASE WHEN reset_date<>excluded.reset_date
                                    THEN excluded.credits_remaining
                                    ELSE player_shop_budgets.credits_remaining END,
             reset_date=excluded.reset_date""",
        (player_id, allowance, today),
    )
    balance = get_vendor_credit_balance(player_id, settings)
    if amount > balance:
        raise ValueError(
            f"Your shop vendor has only {balance} credits left today; "
            f"this sale requires {amount}. The allowance resets at midnight UTC."
        )
    execute_write(
        "UPDATE player_shop_budgets SET credits_remaining=credits_remaining-? WHERE player_id=?",
        (amount, player_id),
    )
    return balance - amount


def reset_all_vendor_credits(settings: dict | None = None) -> int:
    """Restore the full daily allowance for every current player and NPC."""
    settings = settings or get_all_settings()
    today = datetime.utcnow().date().isoformat()
    allowance = daily_vendor_allowance(settings)
    with exclusive_transaction():
        execute_write(
            """INSERT INTO player_shop_budgets(player_id,credits_remaining,reset_date)
               SELECT id,?,? FROM players WHERE 1
               ON CONFLICT(player_id) DO UPDATE SET
                 credits_remaining=excluded.credits_remaining,
                 reset_date=excluded.reset_date""",
            (allowance, today),
        )
    return allowance
