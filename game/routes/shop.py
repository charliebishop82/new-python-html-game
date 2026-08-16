"""Shop listings plus queued purchases, sales, pricing, and unique-item transfers."""
# routes/shop.py
# Full-page shop. Players buy from daily rotation and player-sold listings,
# and sell unequipped gear back. Every transaction redirects back to GET /shop.

import math
import logging
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, session, g
from database import (execute, execute_one, execute_write,
                      exclusive_transaction, get_all_settings,
                      get_player_bonus_profile, get_player_equipped, get_player,
                      encumbered_ap_cost, equipped_special_ids)
from queue_handler import enqueue_and_process, register_handler
import config_defaults as cfg

bp = Blueprint("shop", __name__)
logger = logging.getLogger(__name__)


@bp.route("/shop/leave", methods=["POST"])
def leave():
    """Explicitly close a paid Shop visit before navigating elsewhere."""
    session.pop("shop_access_granted", None)
    return ("", 204)


# ─────────────────────────────────────────────────────────────────────────────
# GET /shop
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/shop/enter", methods=["POST"])
def enter():
    """Charge the one-time admission AP, then open a free trading visit."""
    try:
        player = get_player(session["player_id"])
        settings = get_all_settings()
        from routes.actions import begin_action_interruption, has_interrupted_ap_commitment
        admission = encumbered_ap_cost(
            player, settings.get("AP_COST_SHOP", cfg.AP_COST_SHOP), settings
        )
        if player["current_ap"] < admission and not has_interrupted_ap_commitment("SHOP"):
            return redirect(url_for(
                "dashboard.index", error=f"Not enough AP. Need {admission}."
            ))
        interruption = begin_action_interruption(
            player, "SHOP", settings=settings
        )
        if interruption and interruption["kind"] == "MINION":
            minion = interruption["minion"]
            from routes.actions import _minion_level_warning
            if _minion_level_warning(player, minion, settings):
                session["pending_minion_prompt"] = {
                    "minion_id": minion["id"], "check": interruption["check"]
                }
                return redirect(url_for("dashboard.index"))
            result = enqueue_and_process(
                player["id"], "start_boss_fight",
                {"opponent_id": minion["id"], "encounter_type": "MINION", "cost_ap": 0}
            )
            if result.get("error"):
                raise RuntimeError(result["error"])
            session["combat_session_id"] = result["session_id"]
            return redirect(url_for("dashboard.index"))
        from routes.actions import consume_interrupted_ap_commitment
        allow_shortfall = consume_interrupted_ap_commitment("SHOP")
        enqueue_and_process(
            session["player_id"], "shop_enter",
            {"allow_interruption_shortfall": allow_shortfall}
        )
        session["shop_access_granted"] = True
        feedback = None
        if interruption:
            reward = interruption["reward"]
            feedback = (
                f"Friendly interruption: {reward['protagonist']} gave you "
                f"{reward['item_name']}, {reward['xp_awarded']} XP, and "
                f"{reward['credits_awarded']} credits."
            )
        return redirect(url_for("shop.index", feedback=feedback) if feedback
                        else url_for("shop.index"))
    except RuntimeError as exc:
        return redirect(url_for("dashboard.index", error=str(exc)))


@register_handler("shop_enter")
def handle_shop_enter(player_id: int, payload: dict) -> dict:
    """Spend the configured Shop AP once; purchases and sales are then free."""
    settings = get_all_settings()
    ap_cost = settings.get("AP_COST_SHOP", cfg.AP_COST_SHOP)
    allow_shortfall = bool(payload.get("allow_interruption_shortfall"))
    player = get_player(player_id)
    if not player:
        raise ValueError("Player not found.")
    if player["in_combat"]:
        raise ValueError("The shop is unavailable during combat.")
    ap_cost = encumbered_ap_cost(player, ap_cost, settings)
    if player["current_ap"] < ap_cost and not allow_shortfall:
        raise ValueError(f"Not enough AP. Need {ap_cost}.")
    charged_ap = min(player["current_ap"], ap_cost) if allow_shortfall else ap_cost
    with exclusive_transaction():
        execute_write("UPDATE players SET current_ap=current_ap-? WHERE id=?", (charged_ap, player_id))
    return {"success": True, "ap_spent": charged_ap,
            "interruption_commitment": allow_shortfall}

@bp.route("/shop")
def index():
    """Handle the index workflow."""
    if not session.get("shop_access_granted"):
        return redirect(url_for(
            "dashboard.index", error="Enter the shop from the dashboard to spend its AP cost."
        ))
    player   = g.player
    settings = get_all_settings()

    # Calculate player's effective discount
    per_discount = math.floor(_effective_per(player) / 2) / 100
    special_discount = _get_special_shop_discount(player)
    max_discount = settings.get("SHOP_DISCOUNT_MAX", cfg.SHOP_DISCOUNT_MAX)
    discount = min(per_discount + special_discount, max_discount)

    # Load all current shop listings with content detail
    listings = _get_listings_with_detail(discount)
    _attach_loadout_comparisons(player, listings, settings)

    # Load player's unequipped inventory for the sell panel
    sellable = _get_sellable_items(player)
    from shop_budget import daily_vendor_allowance, get_vendor_credit_balance
    vendor_credit_limit = daily_vendor_allowance(settings)
    vendor_credits = get_vendor_credit_balance(player["id"], settings)

    # Check if player spent AP to enter (AP deducted on first visit each session)
    # For simplicity: AP is deducted when the player clicks Shop from the dashboard.
    # The dashboard action_shop POST (handled here via redirect) deducts AP.

    return render_template(
        "shop/shop.html",
        listings=listings,
        sellable=sellable,
        visit_ap_cost=encumbered_ap_cost(
            player, settings.get("AP_COST_SHOP", cfg.AP_COST_SHOP), settings
        ),
        discount_pct=int(discount * 100),
        vendor_credits=vendor_credits,
        vendor_credit_limit=vendor_credit_limit,
        feedback=request.args.get("feedback"),
        error=request.args.get("error"),
    )


def _get_listings_with_detail(discount: float) -> list[dict]:
    """Load shop_listings joined with content table for display."""
    rows = execute(
        """SELECT sl.*, sl.id as listing_id
           FROM shop_listings sl
           ORDER BY sl.item_type, sl.listed_at ASC"""
    )
    result = []
    for row in rows:
        detail = _get_item_detail(row["item_type"], row["item_id"], active_only=True)
        if detail is None:
            continue
        discounted_price = max(0, int(row["price"] * (1 - discount)))
        result.append({**row, **detail,
                       "discounted_price": discounted_price,
                       "listing_id": row["id"]})
    return result


def _attach_loadout_comparisons(player: dict, listings: list[dict],
                                settings: dict) -> None:
    """Annotate listings with a concise comparison to the equipped item.

    The comparison uses the same derived-stat calculator as the Character and
    Equipment screens. It therefore includes core-stat changes and their
    downstream effects instead of comparing only the item's printed AC or die.
    """
    from routes.character import _calc_derived_stats

    equipped = get_player_equipped(player)
    current = _calc_derived_stats(player, equipped, settings)
    slot_for_type = {"WEAPON": "weapon", "ARMOR": "armor", "SPECIAL": "special"}

    def delta_label(label: str, before: int | float, after: int | float,
                    suffix: str = "") -> tuple[str, float] | None:
        delta = after - before
        if abs(delta) < 0.001:
            return None
        shown = int(delta) if float(delta).is_integer() else round(delta, 1)
        return f"{label} {shown:+}{suffix}", float(delta)

    for listing in listings:
        slot = slot_for_type.get(listing["item_type"])
        if not slot:
            continue
        candidate_loadout = dict(equipped)
        candidate_loadout[slot] = {
            **listing,
            "current_durability": listing.get("durability_at_listing") or 100,
        }
        candidate = _calc_derived_stats(player, candidate_loadout, settings)
        gains, tradeoffs = [], []

        def record(label: str, key: str, suffix: str = "") -> float:
            result = delta_label(label, current[key], candidate[key], suffix)
            if not result:
                return 0.0
            text, delta = result
            (gains if delta > 0 else tradeoffs).append(text)
            return delta

        stat_delta = sum(record(stat.upper(), stat) for stat in
                         ("str", "end", "agi", "lck", "per"))
        hp_delta = record("Max HP", "max_hp")
        ac_delta = record("AC", "ac")
        attack_delta = record("Attack", "attack_modifier")
        initiative_delta = record("Initiative", "initiative_modifier")
        resistance_delta = record("Resistance sources", "resistance_sources")
        damage_min_delta = candidate["damage_min"] - current["damage_min"]
        damage_max_delta = record("Max damage", "damage_max")
        daily_ap_delta = record("Daily AP", "daily_ap")
        crit_delta = record("Critical chance", "crit_chance_pct", "%")

        if slot == "weapon":
            score_delta = ((damage_min_delta + damage_max_delta) * 1.5 +
                           attack_delta * 3 + initiative_delta + ac_delta * 2 +
                           hp_delta * 0.25 + resistance_delta * 3 + stat_delta * 0.5)
        elif slot == "armor":
            score_delta = (ac_delta * 5 + hp_delta * 0.35 + resistance_delta * 4 +
                           attack_delta * 2 + initiative_delta + stat_delta * 0.75)
        else:
            score_delta = ((damage_min_delta + damage_max_delta) + attack_delta * 2 +
                           ac_delta * 4 + hp_delta * 0.3 + resistance_delta * 4 +
                           initiative_delta + daily_ap_delta * 3 + crit_delta * 0.25 +
                           stat_delta * 0.75)

        current_item = equipped.get(slot)
        listing["is_loadout_upgrade"] = current_item is None or score_delta > 0.5
        listing["comparison_gains"] = gains[:4]
        listing["comparison_tradeoffs"] = tradeoffs[:3]
        listing["comparison_summary"] = (
            f"Fills your empty {slot} slot" if current_item is None
            else f"Compared with {current_item.get('name', 'equipped gear')}"
        )


def _get_item_detail(item_type: str, item_id: int, active_only: bool = False) -> dict | None:
    """Load item detail, optionally excluding content retired by a later import."""
    table = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}.get(item_type)
    if not table:
        return None
    active_clause = " AND is_active = 1" if active_only else ""
    return execute_one(f"SELECT * FROM {table} WHERE id = ?{active_clause}", (item_id,))


def _get_sellable_items(player: dict) -> list[dict]:
    """Return inventory items that can be sold (unequipped, active content)."""
    equipped_ids = {
        player.get("equipped_weapon_id"),
        player.get("equipped_armor_id"),
        *equipped_special_ids(player, unlocked_only=False),
    } - {None}

    items = execute(
        """SELECT * FROM inventory_items ii WHERE player_id = ?
           AND NOT EXISTS(SELECT 1 FROM auction_listings a
                          WHERE a.inventory_item_id=ii.id AND a.status='ACTIVE')""",
        (player["id"],)
    )
    result = []
    for inv in items:
        if inv["id"] in equipped_ids:
            continue
        detail = _get_item_detail(inv["item_type"], inv["item_id"])
        if detail is None:
            continue
        sell_price = _calc_sell_price(detail, player)
        result.append({**inv, **detail,
                       "inv_id": inv["id"],
                       "sell_price": sell_price})
    return result


def _calc_sell_price(item_detail: dict, player: dict) -> int:
    """Calculate sell price: credit_cost * SELL_PRICE_PERCENT, boosted by Sell Bonus."""
    settings     = get_all_settings()
    sell_pct     = settings.get("SELL_PRICE_PERCENT", cfg.SELL_PRICE_PERCENT)
    sell_bonus   = _get_special_sell_bonus(player)
    final_pct    = min(sell_pct + sell_bonus, 1.0)
    return max(0, int(item_detail["credit_cost"] * final_pct))


def _get_special_shop_discount(player: dict) -> float:
    """Load the combined equipped-special and permanent-perk shop discount."""
    return float(get_player_bonus_profile(player["id"]).get("shop_discount", 0) or 0)


def _get_special_sell_bonus(player: dict) -> float:
    """Load the combined equipped-special and permanent-perk sell bonus."""
    return float(get_player_bonus_profile(player["id"]).get("sell_bonus", 0) or 0)


def _effective_per(player: dict) -> int:
    """Return PER with weapon, outfit, equipped special, and perks applied."""
    equipped = get_player_equipped(player)
    profile = get_player_bonus_profile(player["id"], equipped.get("specials", []))
    return (int(player.get("per_stat", 0) or 0) +
            int((equipped.get("weapon") or {}).get("per_bonus", 0) or 0) +
            int((equipped.get("armor") or {}).get("per_bonus", 0) or 0) +
            int(profile.get("per_bonus", 0) or 0))


# ─────────────────────────────────────────────────────────────────────────────
# POST /shop/buy
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/shop/buy", methods=["POST"])
def buy():
    """Handle the buy workflow."""
    if not session.get("shop_access_granted"):
        return redirect(url_for("dashboard.index", error="Enter the shop before buying."))
    listing_id = request.form.get("listing_id", type=int)
    if not listing_id:
        return redirect(url_for("shop.index", error="Invalid listing."))

    try:
        enqueue_and_process(session["player_id"], "shop_buy", {"listing_id": listing_id})
        return redirect(url_for("shop.index", feedback="Purchase successful."))
    except RuntimeError as e:
        return redirect(url_for("shop.index", error=str(e)))


@register_handler("shop_buy")
def handle_shop_buy(player_id: int, payload: dict) -> dict:
    """Process the queued shop buy action against validated game state."""
    listing_id = payload["listing_id"]
    settings   = get_all_settings()
    player     = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))

    listing = execute_one("SELECT * FROM shop_listings WHERE id = ?", (listing_id,))
    if listing is None:
        raise ValueError("Item is no longer available.")
    if _get_item_detail(listing["item_type"], listing["item_id"], active_only=True) is None:
        raise ValueError("This item has been retired from the active catalog.")

    # Calculate discounted price
    per_discount     = math.floor(_effective_per(player) / 2) / 100
    special_discount = _get_special_shop_discount(player)
    max_discount     = settings.get("SHOP_DISCOUNT_MAX", cfg.SHOP_DISCOUNT_MAX)
    discount         = min(per_discount + special_discount, max_discount)
    final_price      = max(0, int(listing["price"] * (1 - discount)))

    if player["credits"] < final_price:
        raise ValueError(f"Not enough credits. Need {final_price}.")

    with exclusive_transaction():
        # Re-check listing still exists (race condition guard)
        listing = execute_one("SELECT * FROM shop_listings WHERE id = ?", (listing_id,))
        if listing is None:
            raise ValueError("Item was purchased by another player.")
        if _get_item_detail(listing["item_type"], listing["item_id"], active_only=True) is None:
            raise ValueError("This item has been retired from the active catalog.")

        durability = listing["durability_at_listing"] or 100
        inv_id = execute_write(
            """INSERT INTO inventory_items
               (player_id, item_type, item_id, current_durability, acquired_method)
               VALUES (?, ?, ?, ?, 'SHOP_PURCHASE')""",
            (player_id, listing["item_type"], listing["item_id"], durability)
        )
        execute_write("DELETE FROM shop_listings WHERE id = ?", (listing_id,))
        execute_write(
            "UPDATE players SET credits = credits - ? WHERE id = ?",
            (final_price, player_id)
        )
        execute_write(
            """INSERT INTO item_history
               (player_id, item_type, item_id, item_name, event_type, credit_amount)
               VALUES (?, ?, ?, ?, 'PURCHASED', ?)""",
            (player_id, listing["item_type"], listing["item_id"],
             _get_item_name(listing["item_type"], listing["item_id"]), final_price)
        )
        # If special item: update registry
        if listing["item_type"] == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry
                   SET status = 'IN_INVENTORY', current_owner_player_id = ?,
                       inventory_item_id = ?, last_acquired_method = 'SHOP_PURCHASE',
                       updated_at = ?
                   WHERE special_item_id = ?""",
                (player_id, inv_id, datetime.utcnow().isoformat(), listing["item_id"])
            )

    logger.info("Player %d bought item %s/%d for %d credits",
                player_id, listing["item_type"], listing["item_id"], final_price)
    return {"success": True, "credits_spent": final_price, "ap_spent": 0,
            "inventory_item_id": inv_id}


# ─────────────────────────────────────────────────────────────────────────────
# POST /shop/sell
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/shop/sell", methods=["POST"])
def sell():
    """Handle the sell workflow."""
    if not session.get("shop_access_granted"):
        return redirect(url_for("dashboard.index", error="Enter the shop before selling."))
    inv_id = request.form.get("inv_id", type=int)
    if not inv_id:
        return redirect(url_for("shop.index", error="Invalid item."))

    try:
        enqueue_and_process(session["player_id"], "shop_sell", {"inv_id": inv_id})
        return redirect(url_for("shop.index", feedback="Item sold to the shop."))
    except RuntimeError as e:
        return redirect(url_for("shop.index", error=str(e)))


@register_handler("shop_sell")
def handle_shop_sell(player_id: int, payload: dict) -> dict:
    """Process the queued shop sell action against validated game state."""
    inv_id   = payload["inv_id"]
    settings = get_all_settings()
    sell_pct = settings.get("SELL_PRICE_PERCENT", cfg.SELL_PRICE_PERCENT)
    player   = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))

    inv = execute_one(
        "SELECT * FROM inventory_items WHERE id = ? AND player_id = ?",
        (inv_id, player_id)
    )
    if inv is None:
        raise ValueError("Item not found in your inventory.")
    if execute_one(
        "SELECT 1 FROM auction_listings WHERE inventory_item_id=? AND status='ACTIVE'",
        (inv_id,)
    ):
        raise ValueError("That item is on auction hold and cannot be sold.")

    # Cannot sell equipped items
    equipped = {player.get("equipped_weapon_id"),
                player.get("equipped_armor_id"),
                *equipped_special_ids(player, unlocked_only=False)}
    if inv_id in equipped:
        raise ValueError("Unequip the item before selling it.")

    detail    = _get_item_detail(inv["item_type"], inv["item_id"])
    if detail is None:
        raise ValueError("Item content not found.")

    # Apply sell bonus from special item
    sell_bonus = _get_special_sell_bonus(player)
    final_pct  = min(sell_pct + sell_bonus, 1.0)
    sell_price = max(0, int(detail["credit_cost"] * final_pct))
    from shop_budget import get_vendor_credit_balance
    vendor_balance = get_vendor_credit_balance(player_id, settings)
    if sell_price > vendor_balance:
        raise ValueError(
            f"Your shop vendor has only {vendor_balance} credits left today; "
            f"this sale requires {sell_price}. The allowance resets at midnight UTC."
        )
    from crews import contribute_earnings
    _unused_xp, net_sell_price = contribute_earnings(player_id, 0, sell_price, "SHOP_SALE")

    with exclusive_transaction():
        from shop_budget import debit_vendor_credits
        vendor_remaining = debit_vendor_credits(player_id, sell_price, settings)
        # Release the unique-item registry foreign key before deleting its
        # inventory copy. SQLite rejects the inverse ordering.
        if inv["item_type"] == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry
                   SET status = 'IN_SHOP', current_owner_player_id = NULL,
                       inventory_item_id = NULL, shop_listing_price = ?,
                       last_released_method = 'SOLD', updated_at = ?
                   WHERE special_item_id = ?""",
                (sell_price, datetime.utcnow().isoformat(), inv["item_id"])
            )
        # Delete from inventory
        execute_write("DELETE FROM inventory_items WHERE id = ?", (inv_id,))
        # Credit player
        execute_write(
            "UPDATE players SET credits = credits + ? WHERE id = ?",
            (net_sell_price, player_id)
        )
        # Create shop listing
        listing_id = execute_write(
            """INSERT INTO shop_listings
               (item_type, item_id, listing_source, seller_player_id,
                durability_at_listing, price)
               VALUES (?, ?, 'PLAYER_SOLD', ?, ?, ?)""",
            (inv["item_type"], inv["item_id"], player_id,
             inv["current_durability"], detail["credit_cost"])
        )
        # Log to item_history
        execute_write(
            """INSERT INTO item_history
               (player_id, item_type, item_id, item_name, event_type, credit_amount)
               VALUES (?, ?, ?, ?, 'SOLD', ?)""",
            (player_id, inv["item_type"], inv["item_id"],
             detail["name"], sell_price)
        )
        from shop_stock import enforce_player_sold_listing_cap
        expired = enforce_player_sold_listing_cap(settings)
    logger.info("Player %d sold item %s/%d for %d credits",
                player_id, inv["item_type"], inv["item_id"], sell_price)
    return {"success": True, "sell_price": sell_price,
            "vendor_credits_remaining": vendor_remaining,
            "shop_listings_expired": len(expired), "ap_spent": 0}


def _get_item_name(item_type: str, item_id: int) -> str:
    """Load item name from current database state."""
    detail = _get_item_detail(item_type, item_id)
    return detail["name"] if detail else "Unknown Item"


################################################################################
