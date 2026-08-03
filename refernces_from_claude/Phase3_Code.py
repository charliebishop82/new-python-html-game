################################################################################
# PHASE 3 CODE — Core Non-Combat Actions
# BBS-Inspired Multiplayer Dueling Game
#
# Files included:
#   1. routes/actions.py      — Tavern handler + boss/pvp stubs
#   2. routes/shop.py         — Full buy/sell implementation
#   3. routes/blacksmith.py   — Full repair implementation
#   4. routes/character.py    — Equip/unequip/drop/preference + stat preview
#   5. routes/combat.py       — Stubs (Phase 5)
#      routes/scoreboards.py  — Stubs (Phase 9)
#   6. templates/             — All Phase 3 templates
#
# Requires Phase 1 + Phase 2 files to already be in place.
#
# Queue handlers registered in this phase:
#   tavern_heal, shop_buy, shop_sell, blacksmith_repair,
#   equip, unequip, drop_item, set_preference
################################################################################

################################################################################
# FILE: routes/actions.py
################################################################################

# routes/actions.py
# Terminal-fragment POST routes for AP actions.
# All return rendered HTML fragments appended to #terminal by terminal.js.
# Boss/PvP flows are stubs here — full implementation in Phase 5/6.

import math
import logging
from datetime import datetime

from flask import Blueprint, render_template, request, session, g
from database import (execute, execute_one, execute_write,
                      exclusive_transaction, get_all_settings)
from queue_handler import enqueue_and_process, register_handler
import config_defaults as cfg

bp = Blueprint("actions", __name__)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _error_fragment(message: str) -> str:
    """Return a terminal error fragment."""
    return render_template("fragments/error.html", message=message)


def _check_ap(player: dict, cost: int) -> str | None:
    """Return an error fragment if player can't afford the AP cost, else None."""
    if player["current_ap"] < cost:
        return _error_fragment(f"Not enough AP. Need {cost}, have {player['current_ap']}.")
    return None


def _deduct_ap_and_regen(player_id: int, player: dict, cost: int, settings: dict):
    """Deduct AP cost and apply passive HP regen. Called inside exclusive_transaction."""
    ap_regen    = settings.get("AP_PASSIVE_HP_REGEN", cfg.AP_PASSIVE_HP_REGEN)
    end_divisor = settings.get("END_HP_REGEN_DIVISOR", cfg.END_HP_REGEN_DIVISOR)
    hp_regen    = ap_regen + math.floor(player["end_stat"] / end_divisor)

    # Check for equipped special item HP regen bonus
    if player.get("equipped_special_id"):
        special_inv = execute_one(
            "SELECT item_id FROM inventory_items WHERE id = ?",
            (player["equipped_special_id"],)
        )
        if special_inv:
            special = execute_one(
                "SELECT hp_regen_bonus FROM special_items WHERE id = ?",
                (special_inv["item_id"],)
            )
            if special:
                hp_regen += special["hp_regen_bonus"]

    max_hp = player["max_hp"]
    new_ap = player["current_ap"] - cost
    new_hp = min(player["current_hp"] + hp_regen, max_hp)

    execute_write(
        "UPDATE players SET current_ap = ?, current_hp = ? WHERE id = ?",
        (new_ap, new_hp, player_id)
    )
    return new_ap, new_hp


# ─────────────────────────────────────────────────────────────────────────────
# TAVERN
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/action/tavern", methods=["POST"])
def action_tavern():
    player   = g.player
    settings = get_all_settings()
    cost_ap  = settings.get("AP_COST_TAVERN",   cfg.AP_COST_TAVERN)
    cost_cr  = settings.get("TAVERN_HEAL_COST", cfg.TAVERN_HEAL_COST)

    if player["current_hp"] >= player["max_hp"]:
        return _error_fragment("You are already at full health.")
    if err := _check_ap(player, cost_ap):
        return err
    if player["credits"] < cost_cr:
        return _error_fragment(f"Not enough credits. Need {cost_cr}.")

    result = enqueue_and_process(
        player["id"], "tavern_heal",
        {"cost_ap": cost_ap, "cost_cr": cost_cr}
    )
    return render_template("fragments/tavern_result.html", **result)


@register_handler("tavern_heal")
def handle_tavern_heal(player_id: int, payload: dict) -> dict:
    settings    = get_all_settings()
    cost_ap     = payload["cost_ap"]
    cost_cr     = payload["cost_cr"]
    heal_pct    = settings.get("TAVERN_HEAL_PERCENT", cfg.TAVERN_HEAL_PERCENT)

    player = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))
    max_hp = 10 + player["end_stat"] + (5 * player["level"])
    missing = max_hp - player["current_hp"]

    if missing <= 0:
        raise ValueError("Already at full health.")
    if player["credits"] < cost_cr:
        raise ValueError("Not enough credits.")
    if player["current_ap"] < cost_ap:
        raise ValueError("Not enough AP.")

    heal_amount = max(1, int(missing * heal_pct))
    new_hp = min(player["current_hp"] + heal_amount, max_hp)

    with exclusive_transaction():
        new_ap, new_hp_after_regen = _deduct_ap_and_regen(
            player_id, player, cost_ap, settings
        )
        # Tavern heal stacks on top of passive regen already applied
        final_hp = min(new_hp_after_regen + heal_amount, max_hp)
        execute_write(
            "UPDATE players SET current_hp = ?, credits = credits - ? WHERE id = ?",
            (final_hp, cost_cr, player_id)
        )
        new_credits = player["credits"] - cost_cr

    logger.info("Player %d used Tavern: healed %d HP, spent %d credits",
                player_id, heal_amount, cost_cr)
    return {
        "heal_amount": heal_amount,
        "new_hp":      final_hp,
        "max_hp":      max_hp,
        "new_ap":      new_ap,
        "max_ap":      player["max_ap"],
        "new_credits": new_credits,
        "cost_cr":     cost_cr,
    }


# ─────────────────────────────────────────────────────────────────────────────
# BOSS FIGHT — stub (full implementation Phase 5)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/action/boss", methods=["POST"])
def action_boss():
    player   = g.player
    settings = get_all_settings()
    cost_ap  = settings.get("AP_COST_BOSS", cfg.AP_COST_BOSS)

    if player["in_combat"]:
        return _error_fragment("You are already in combat.")
    if g.get("blackout"):
        return _error_fragment("Combat unavailable — midnight reset approaching.")
    if err := _check_ap(player, cost_ap):
        return err

    # Phase 5: random event check, boss/minion roll, PER check, level warning
    return _error_fragment("Boss fights coming in Phase 5.")


@bp.route("/action/boss/confirm", methods=["POST"])
def action_boss_confirm():
    return _error_fragment("Boss fights coming in Phase 5.")


# ─────────────────────────────────────────────────────────────────────────────
# PVP — stub (full implementation Phase 6)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/action/pvp", methods=["POST"])
def action_pvp():
    player   = g.player
    settings = get_all_settings()
    cost_ap  = settings.get("AP_COST_PVP", cfg.AP_COST_PVP)

    if player["in_combat"]:
        return _error_fragment("You are already in combat.")
    if g.get("blackout"):
        return _error_fragment("Combat unavailable — midnight reset approaching.")
    if err := _check_ap(player, cost_ap):
        return err

    # Phase 6: random event check, opponent list
    return _error_fragment("PvP coming in Phase 6.")


@bp.route("/action/pvp/fight", methods=["POST"])
def action_pvp_fight():
    return _error_fragment("PvP coming in Phase 6.")


################################################################################
# FILE: routes/shop.py
################################################################################

# routes/shop.py
# Full-page shop. Players buy from daily rotation and player-sold listings,
# and sell unequipped gear back. Every transaction redirects back to GET /shop.

import math
import logging
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, session, g
from database import (execute, execute_one, execute_write,
                      exclusive_transaction, get_all_settings)
from queue_handler import enqueue_and_process, register_handler
import config_defaults as cfg

bp = Blueprint("shop", __name__)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# GET /shop
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/shop")
def index():
    player   = g.player
    settings = get_all_settings()

    # Calculate player's effective discount
    per_discount = math.floor(player["per_stat"] / 2) / 100
    special_discount = _get_special_shop_discount(player)
    max_discount = settings.get("SHOP_DISCOUNT_MAX", cfg.SHOP_DISCOUNT_MAX)
    discount = min(per_discount + special_discount, max_discount)

    # Load all current shop listings with content detail
    listings = _get_listings_with_detail(discount)

    # Load player's unequipped inventory for the sell panel
    sellable = _get_sellable_items(player)

    # Check if player spent AP to enter (AP deducted on first visit each session)
    # For simplicity: AP is deducted when the player clicks Shop from the dashboard.
    # The dashboard action_shop POST (handled here via redirect) deducts AP.

    return render_template(
        "shop/shop.html",
        listings=listings,
        sellable=sellable,
        discount_pct=int(discount * 100),
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
        detail = _get_item_detail(row["item_type"], row["item_id"])
        if detail is None:
            continue
        discounted_price = max(0, int(row["price"] * (1 - discount)))
        result.append({**row, **detail,
                       "discounted_price": discounted_price,
                       "listing_id": row["id"]})
    return result


def _get_item_detail(item_type: str, item_id: int) -> dict | None:
    table = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}.get(item_type)
    if not table:
        return None
    return execute_one(f"SELECT * FROM {table} WHERE id = ?", (item_id,))


def _get_sellable_items(player: dict) -> list[dict]:
    """Return inventory items that can be sold (unequipped, active content)."""
    equipped_ids = {
        player.get("equipped_weapon_id"),
        player.get("equipped_armor_id"),
        player.get("equipped_special_id"),
    } - {None}

    items = execute(
        "SELECT * FROM inventory_items WHERE player_id = ?", (player["id"],)
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
    if not player.get("equipped_special_id"):
        return 0.0
    inv = execute_one(
        "SELECT item_id FROM inventory_items WHERE id = ?",
        (player["equipped_special_id"],)
    )
    if not inv:
        return 0.0
    s = execute_one("SELECT shop_discount FROM special_items WHERE id = ?", (inv["item_id"],))
    return s["shop_discount"] if s else 0.0


def _get_special_sell_bonus(player: dict) -> float:
    if not player.get("equipped_special_id"):
        return 0.0
    inv = execute_one(
        "SELECT item_id FROM inventory_items WHERE id = ?",
        (player["equipped_special_id"],)
    )
    if not inv:
        return 0.0
    s = execute_one("SELECT sell_bonus FROM special_items WHERE id = ?", (inv["item_id"],))
    return s["sell_bonus"] if s else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# POST /shop/buy
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/shop/buy", methods=["POST"])
def buy():
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
    listing_id = payload["listing_id"]
    settings   = get_all_settings()
    player     = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))

    listing = execute_one("SELECT * FROM shop_listings WHERE id = ?", (listing_id,))
    if listing is None:
        raise ValueError("Item is no longer available.")

    # Calculate discounted price
    per_discount     = math.floor(player["per_stat"] / 2) / 100
    special_discount = 0.0
    if player.get("equipped_special_id"):
        inv = execute_one(
            "SELECT item_id FROM inventory_items WHERE id = ?",
            (player["equipped_special_id"],)
        )
        if inv:
            s = execute_one("SELECT shop_discount FROM special_items WHERE id = ?", (inv["item_id"],))
            if s:
                special_discount = s["shop_discount"]
    max_discount     = settings.get("SHOP_DISCOUNT_MAX", cfg.SHOP_DISCOUNT_MAX)
    discount         = min(per_discount + special_discount, max_discount)
    final_price      = max(0, int(listing["price"] * (1 - discount)))

    if player["credits"] < final_price:
        raise ValueError(f"Not enough credits. Need {final_price}.")

    # Check inventory limit — buying always allowed but check for over-encumbered flag
    inv_limit = settings.get("INVENTORY_LIMIT", cfg.INVENTORY_LIMIT) + \
                math.floor(player["str_stat"] / 2)

    with exclusive_transaction():
        # Re-check listing still exists (race condition guard)
        listing = execute_one("SELECT * FROM shop_listings WHERE id = ?", (listing_id,))
        if listing is None:
            raise ValueError("Item was purchased by another player.")

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
    return {"success": True}


# ─────────────────────────────────────────────────────────────────────────────
# POST /shop/sell
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/shop/sell", methods=["POST"])
def sell():
    inv_id = request.form.get("inv_id", type=int)
    if not inv_id:
        return redirect(url_for("shop.index", error="Invalid item."))

    try:
        enqueue_and_process(session["player_id"], "shop_sell", {"inv_id": inv_id})
        return redirect(url_for("shop.index", feedback="Item listed for sale."))
    except RuntimeError as e:
        return redirect(url_for("shop.index", error=str(e)))


@register_handler("shop_sell")
def handle_shop_sell(player_id: int, payload: dict) -> dict:
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

    # Cannot sell equipped items
    equipped = {player.get("equipped_weapon_id"),
                player.get("equipped_armor_id"),
                player.get("equipped_special_id")}
    if inv_id in equipped:
        raise ValueError("Unequip the item before selling it.")

    detail    = _get_item_detail(inv["item_type"], inv["item_id"])
    if detail is None:
        raise ValueError("Item content not found.")

    # Apply sell bonus from special item
    sell_bonus = _get_special_sell_bonus(player)
    final_pct  = min(sell_pct + sell_bonus, 1.0)
    sell_price = max(0, int(detail["credit_cost"] * final_pct))

    with exclusive_transaction():
        # Delete from inventory
        execute_write("DELETE FROM inventory_items WHERE id = ?", (inv_id,))
        # Credit player
        execute_write(
            "UPDATE players SET credits = credits + ? WHERE id = ?",
            (sell_price, player_id)
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
        # If special item: update registry to IN_SHOP
        if inv["item_type"] == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry
                   SET status = 'IN_SHOP', current_owner_player_id = NULL,
                       inventory_item_id = NULL, shop_listing_price = ?,
                       last_released_method = 'SOLD', updated_at = ?
                   WHERE special_item_id = ?""",
                (sell_price, datetime.utcnow().isoformat(), inv["item_id"])
            )

    logger.info("Player %d sold item %s/%d for %d credits",
                player_id, inv["item_type"], inv["item_id"], sell_price)
    return {"success": True, "sell_price": sell_price}


def _get_item_name(item_type: str, item_id: int) -> str:
    detail = _get_item_detail(item_type, item_id)
    return detail["name"] if detail else "Unknown Item"


################################################################################
# FILE: routes/blacksmith.py
################################################################################

# routes/blacksmith.py
# Full-page repair interface. Players select damaged items to repair,
# pay credits per item, with a LCK bonus roll for enhanced restoration.

import math
import logging
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, session, g
from database import (execute, execute_one, execute_write,
                      exclusive_transaction, get_all_settings)
from queue_handler import enqueue_and_process, register_handler
import config_defaults as cfg
import random

bp = Blueprint("blacksmith", __name__)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# GET /blacksmith
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/blacksmith")
def index():
    player   = g.player
    settings = get_all_settings()

    if player["credits"] == 0:
        return render_template("blacksmith/blacksmith.html",
                               items=[], blocked=True,
                               blocked_reason="You have no credits.",
                               feedback=request.args.get("feedback"),
                               error=request.args.get("error"))

    items = _get_repairable_items(player, settings)

    all_full = all(i["current_durability"] >= 100 for i in items)
    if all_full:
        return render_template("blacksmith/blacksmith.html",
                               items=[], blocked=True,
                               blocked_reason="All your items are at full durability.",
                               feedback=request.args.get("feedback"),
                               error=request.args.get("error"))

    return render_template("blacksmith/blacksmith.html",
                           items=items,
                           blocked=False,
                           feedback=request.args.get("feedback"),
                           error=request.args.get("error"))


def _get_repairable_items(player: dict, settings: dict) -> list[dict]:
    """Load player inventory with repair cost calculated per item."""
    repair_cost_pct = settings.get("REPAIR_COST_PERCENT", cfg.REPAIR_COST_PERCENT)
    items = execute(
        "SELECT * FROM inventory_items WHERE player_id = ?", (player["id"],)
    )
    result = []
    for inv in items:
        if inv["current_durability"] >= 100:
            continue  # skip fully repaired items
        detail = _get_item_detail(inv["item_type"], inv["item_id"])
        if detail is None:
            continue
        missing_dur = 100 - inv["current_durability"]
        # Cost = credit_cost * REPAIR_COST_PERCENT * (missing_dur / 100)
        # Free if credit_cost is 0
        repair_cost = max(0, int(
            detail["credit_cost"] * repair_cost_pct * (missing_dur / 100)
        ))
        equipped = inv["id"] in {
            player.get("equipped_weapon_id"),
            player.get("equipped_armor_id"),
            player.get("equipped_special_id"),
        }
        result.append({
            **inv, **detail,
            "inv_id":      inv["id"],
            "repair_cost": repair_cost,
            "missing_dur": missing_dur,
            "is_equipped": equipped,
        })
    return result


def _get_item_detail(item_type: str, item_id: int) -> dict | None:
    table = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}.get(item_type)
    if not table:
        return None
    return execute_one(f"SELECT * FROM {table} WHERE id = ?", (item_id,))


# ─────────────────────────────────────────────────────────────────────────────
# POST /blacksmith/repair
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/blacksmith/repair", methods=["POST"])
def repair():
    # inv_ids is a list of inventory item IDs the player wants to repair
    inv_ids = request.form.getlist("inv_ids", type=int)
    repair_mode = request.form.get("mode", "selected")  # selected / equipped / all

    try:
        result = enqueue_and_process(
            session["player_id"], "blacksmith_repair",
            {"inv_ids": inv_ids, "mode": repair_mode}
        )
        feedback = f"Repaired {result['items_repaired']} item(s). Spent {result['total_cost']} credits."
        return redirect(url_for("blacksmith.index", feedback=feedback))
    except RuntimeError as e:
        return redirect(url_for("blacksmith.index", error=str(e)))


@register_handler("blacksmith_repair")
def handle_blacksmith_repair(player_id: int, payload: dict) -> dict:
    settings    = get_all_settings()
    repair_base = settings.get("REPAIR_BASE_PERCENT",    cfg.REPAIR_BASE_PERCENT)
    lck_mult    = settings.get("REPAIR_LCK_MULTIPLIER",  cfg.REPAIR_LCK_MULTIPLIER)
    lck_cap     = settings.get("REPAIR_LCK_CAP",         cfg.REPAIR_LCK_CAP)
    cost_pct    = settings.get("REPAIR_COST_PERCENT",    cfg.REPAIR_COST_PERCENT)
    ap_cost     = settings.get("AP_COST_BLACKSMITH",     cfg.AP_COST_BLACKSMITH)

    player  = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))
    if player["credits"] == 0:
        raise ValueError("You have no credits.")
    if player["current_ap"] < ap_cost:
        raise ValueError(f"Not enough AP. Need {ap_cost}.")

    inv_ids = payload.get("inv_ids", [])
    mode    = payload.get("mode", "selected")

    # Build list of items to repair based on mode
    all_items = execute(
        "SELECT * FROM inventory_items WHERE player_id = ?", (player_id,)
    )
    equipped_ids = {
        player.get("equipped_weapon_id"),
        player.get("equipped_armor_id"),
        player.get("equipped_special_id"),
    } - {None}

    to_repair = []
    for inv in all_items:
        if inv["current_durability"] >= 100:
            continue
        if mode == "equipped" and inv["id"] not in equipped_ids:
            continue
        if mode == "selected" and inv["id"] not in inv_ids:
            continue
        detail = _get_item_detail(inv["item_type"], inv["item_id"])
        if detail is None:
            continue
        missing = 100 - inv["current_durability"]
        cost    = max(0, int(detail["credit_cost"] * cost_pct * (missing / 100)))
        to_repair.append({**inv, "detail": detail, "repair_cost": cost, "missing": missing})

    if not to_repair:
        raise ValueError("No items selected for repair.")

    total_cost = sum(i["repair_cost"] for i in to_repair)
    if player["credits"] < total_cost:
        raise ValueError(f"Not enough credits. Need {total_cost}, have {player['credits']}.")

    lck = player["lck_stat"]
    lck_roll_chance = math.floor(lck / 2) * 0.05  # 5% per floor(LCK/2)
    results = []

    with exclusive_transaction():
        # Deduct AP (no passive regen on blacksmith entry)
        execute_write(
            "UPDATE players SET current_ap = current_ap - ? WHERE id = ?",
            (ap_cost, player_id)
        )
        # Deduct total credit cost
        execute_write(
            "UPDATE players SET credits = credits - ? WHERE id = ?",
            (total_cost, player_id)
        )

        for item in to_repair:
            # Base repair
            base_restore = int(item["missing"] * repair_base)

            # LCK bonus roll
            lck_bonus_applied = False
            if random.random() < lck_roll_chance:
                lck_cap_restore = int(item["missing"] * min(0.50 + (lck * lck_mult / 100), lck_cap))
                final_restore   = max(base_restore, lck_cap_restore)
                lck_bonus_applied = True
            else:
                final_restore = base_restore

            new_durability = min(item["current_durability"] + final_restore, 100)
            execute_write(
                "UPDATE inventory_items SET current_durability = ? WHERE id = ?",
                (new_durability, item["id"])
            )
            results.append({
                "name":             item["detail"]["name"],
                "restored":         final_restore,
                "new_durability":   new_durability,
                "lck_bonus":        lck_bonus_applied,
            })

    logger.info("Player %d repaired %d items for %d credits",
                player_id, len(results), total_cost)
    return {
        "items_repaired": len(results),
        "total_cost":     total_cost,
        "results":        results,
    }


################################################################################
# FILE: routes/character.py
################################################################################

# routes/character.py
# Full-page character sheet with inventory management.
# Equip, unequip, drop items. Update combat preference.
# Live stat preview via lightweight JSON endpoint.

import math
import logging
from datetime import datetime

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, g, jsonify)
from database import (execute, execute_one, execute_write,
                      exclusive_transaction, get_all_settings)
from queue_handler import enqueue_and_process, register_handler
import config_defaults as cfg

bp = Blueprint("character", __name__)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# GET /character
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/character")
def index():
    player   = g.player
    settings = get_all_settings()

    inventory = _get_full_inventory(player)
    equipped  = {
        "weapon":  _find_equipped(inventory, player.get("equipped_weapon_id")),
        "armor":   _find_equipped(inventory, player.get("equipped_armor_id")),
        "special": _find_equipped(inventory, player.get("equipped_special_id")),
    }
    derived = _calc_derived_stats(player, equipped, settings)
    active_effects = _get_active_effects(player["id"])

    return render_template(
        "character/character.html",
        inventory=inventory,
        equipped=equipped,
        derived=derived,
        active_effects=active_effects,
        preferences=["Aggressive", "Defensive", "Opportunist", "Balanced"],
        feedback=request.args.get("feedback"),
        error=request.args.get("error"),
    )


def _get_active_effects(player_id: int) -> list[dict]:
    """Build readable character-sheet entries for midnight status effects."""
    rows = execute(
        "SELECT effect_type, value FROM status_effects WHERE player_id = ? ORDER BY id",
        (player_id,)
    )
    stat_names = {
        "STAT_BOOST_STR": "Strength", "STAT_BOOST_END": "Endurance",
        "STAT_BOOST_AGI": "Agility", "STAT_BOOST_LCK": "Luck",
        "STAT_BOOST_PER": "Perception", "STAT_BOOST_INITIATIVE": "Initiative",
        "STAT_PENALTY_STR": "Strength", "STAT_PENALTY_END": "Endurance",
        "STAT_PENALTY_AGI": "Agility", "STAT_PENALTY_LCK": "Luck",
        "STAT_PENALTY_PER": "Perception", "STAT_PENALTY_INITIATIVE": "Initiative",
    }
    effects = []
    for row in rows:
        effect_type, value = row["effect_type"], row["value"]
        if effect_type == "CURSED":
            description, is_good = f"Daily AP award -{int(round(value * 100))}%", False
        elif effect_type in stat_names:
            description, is_good = f"{stat_names[effect_type]} {int(value):+d}", value > 0
        else:
            description, is_good = effect_type.replace("_", " ").title(), value >= 0
        effects.append({"description": description, "is_good": is_good, "expires": "Midnight reset"})
    return effects


def _get_full_inventory(player: dict) -> list[dict]:
    equipped_ids = {
        player.get("equipped_weapon_id"),
        player.get("equipped_armor_id"),
        player.get("equipped_special_id"),
    } - {None}

    rows = execute(
        "SELECT * FROM inventory_items WHERE player_id = ? ORDER BY item_type, acquired_at",
        (player["id"],)
    )
    result = []
    for inv in rows:
        detail = _get_item_detail(inv["item_type"], inv["item_id"])
        if detail is None:
            continue
        result.append({
            **inv, **detail,
            "inv_id":     inv["id"],
            "is_equipped": inv["id"] in equipped_ids,
        })
    return result


def _find_equipped(inventory: list, inv_id) -> dict | None:
    if inv_id is None:
        return None
    return next((i for i in inventory if i["inv_id"] == inv_id), None)


def _get_item_detail(item_type: str, item_id: int) -> dict | None:
    table = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}.get(item_type)
    if not table:
        return None
    return execute_one(f"SELECT * FROM {table} WHERE id = ?", (item_id,))


def _calc_derived_stats(player: dict, equipped: dict, settings: dict) -> dict:
    """Compute all derived stats for display on character sheet."""
    w = equipped.get("weapon")
    a = equipped.get("armor")
    s = equipped.get("special")

    str_total = player["str_stat"] + (w.get("str_bonus", 0) if w else 0) + \
                (a.get("str_bonus", 0) if a else 0) + (s.get("str_bonus", 0) if s else 0)
    end_total = player["end_stat"] + (w.get("end_bonus", 0) if w else 0) + \
                (a.get("end_bonus", 0) if a else 0) + (s.get("end_bonus", 0) if s else 0)
    agi_total = player["agi_stat"] + (w.get("agi_bonus", 0) if w else 0) + \
                (a.get("agi_bonus", 0) if a else 0) + (s.get("agi_bonus", 0) if s else 0)
    lck_total = player["lck_stat"] + (w.get("lck_bonus", 0) if w else 0) + \
                (a.get("lck_bonus", 0) if a else 0) + (s.get("lck_bonus", 0) if s else 0)
    per_total = player["per_stat"] + (w.get("per_bonus", 0) if w else 0) + \
                (a.get("per_bonus", 0) if a else 0) + (s.get("per_bonus", 0) if s else 0)

    ac_bonus     = (a.get("ac_bonus", 0) if a else 0) + (s.get("ac_bonus", 0) if s else 0)
    ac           = 10 + math.floor(agi_total / 2) + ac_bonus
    max_hp       = 10 + end_total + (5 * player["level"])
    inv_limit    = settings.get("INVENTORY_LIMIT", cfg.INVENTORY_LIMIT) + \
                   math.floor(str_total / 2)
    crit_thresh  = max(
        settings.get("CRIT_MIN_THRESHOLD", cfg.CRIT_MIN_THRESHOLD),
        settings.get("CRIT_BASE_THRESHOLD", cfg.CRIT_BASE_THRESHOLD) -
        math.floor(lck_total / settings.get("CRIT_LCK_DIVISOR", cfg.CRIT_LCK_DIVISOR))
    )
    if s:
        crit_thresh = max(
            settings.get("CRIT_MIN_THRESHOLD", cfg.CRIT_MIN_THRESHOLD),
            crit_thresh - int(s.get("crit_chance_bonus", 0))
        )
    shop_discount= min(
        math.floor(per_total / 2) + int((s.get("shop_discount", 0) if s else 0) * 100),
        int(settings.get("SHOP_DISCOUNT_MAX", cfg.SHOP_DISCOUNT_MAX) * 100)
    )
    daily_ap     = settings.get("BASE_DAILY_AP", cfg.BASE_DAILY_AP) + \
                   math.floor(end_total / 2) + (s.get("bonus_ap", 0) if s else 0)
    passive_regen= settings.get("AP_PASSIVE_HP_REGEN", cfg.AP_PASSIVE_HP_REGEN) + \
                   math.floor(end_total / settings.get("END_HP_REGEN_DIVISOR", cfg.END_HP_REGEN_DIVISOR)) + \
                   (s.get("hp_regen_bonus", 0) if s else 0)

    return {
        "str": str_total, "end": end_total, "agi": agi_total,
        "lck": lck_total, "per": per_total,
        "ac": ac, "max_hp": max_hp, "inv_limit": inv_limit,
        "crit_threshold": crit_thresh, "shop_discount_pct": shop_discount,
        "daily_ap": daily_ap, "passive_regen": passive_regen,
        "extra_attack": bool(s.get("extra_attack")) if s else False,
        "xp_multiplier_pct": int((s.get("xp_multiplier", 0) if s else 0) * 100),
        "credit_multiplier_pct": int((s.get("credit_multiplier", 0) if s else 0) * 100),
    }


# ─────────────────────────────────────────────────────────────────────────────
# STAT PREVIEW (live AJAX — the third JS feature)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/character/preview")
def preview():
    """Return JSON of derived stats for a hypothetical equipment loadout.
    Used by character.html JS for live stat preview on equip/unequip changes."""
    player   = g.player
    settings = get_all_settings()

    def load_equipped(inv_id_str):
        if not inv_id_str or inv_id_str == "none":
            return None
        try:
            inv_id = int(inv_id_str)
        except ValueError:
            return None
        inv = execute_one(
            "SELECT * FROM inventory_items WHERE id = ? AND player_id = ?",
            (inv_id, player["id"])
        )
        if not inv:
            return None
        detail = _get_item_detail(inv["item_type"], inv["item_id"])
        return {**(detail or {}), "current_durability": inv["current_durability"]}

    equipped = {
        "weapon":  load_equipped(request.args.get("weapon")),
        "armor":   load_equipped(request.args.get("armor")),
        "special": load_equipped(request.args.get("special")),
    }
    derived = _calc_derived_stats(player, equipped, settings)
    return jsonify(derived)


# ─────────────────────────────────────────────────────────────────────────────
# POST /character/equip
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/character/equip", methods=["POST"])
def equip():
    inv_id = request.form.get("inv_id", type=int)
    try:
        enqueue_and_process(session["player_id"], "equip", {"inv_id": inv_id})
        return redirect(url_for("character.index", feedback="Item equipped."))
    except RuntimeError as e:
        return redirect(url_for("character.index", error=str(e)))


@register_handler("equip")
def handle_equip(player_id: int, payload: dict) -> dict:
    inv_id = payload["inv_id"]
    player = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))
    inv    = execute_one(
        "SELECT * FROM inventory_items WHERE id = ? AND player_id = ?",
        (inv_id, player_id)
    )
    if inv is None:
        raise ValueError("Item not found in your inventory.")

    # Determine correct slot column
    slot_col = {
        "WEAPON":  "equipped_weapon_id",
        "ARMOR":   "equipped_armor_id",
        "SPECIAL": "equipped_special_id",
    }.get(inv["item_type"])
    if slot_col is None:
        raise ValueError("Unknown item type.")

    with exclusive_transaction():
        execute_write(
            f"UPDATE players SET {slot_col} = ? WHERE id = ?",
            (inv_id, player_id)
        )
    return {"success": True}


# ─────────────────────────────────────────────────────────────────────────────
# POST /character/unequip
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/character/unequip", methods=["POST"])
def unequip():
    slot = request.form.get("slot")  # weapon / armor / special
    try:
        enqueue_and_process(session["player_id"], "unequip", {"slot": slot})
        return redirect(url_for("character.index", feedback="Item unequipped."))
    except RuntimeError as e:
        return redirect(url_for("character.index", error=str(e)))


@register_handler("unequip")
def handle_unequip(player_id: int, payload: dict) -> dict:
    slot = payload.get("slot", "").lower()
    slot_col = {
        "weapon":  "equipped_weapon_id",
        "armor":   "equipped_armor_id",
        "special": "equipped_special_id",
    }.get(slot)
    if not slot_col:
        raise ValueError("Invalid slot.")

    with exclusive_transaction():
        execute_write(
            f"UPDATE players SET {slot_col} = NULL WHERE id = ?",
            (player_id,)
        )
    return {"success": True}


# ─────────────────────────────────────────────────────────────────────────────
# POST /character/drop
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/character/drop", methods=["POST"])
def drop():
    inv_id = request.form.get("inv_id", type=int)
    try:
        enqueue_and_process(session["player_id"], "drop_item", {"inv_id": inv_id})
        return redirect(url_for("character.index", feedback="Item dropped."))
    except RuntimeError as e:
        return redirect(url_for("character.index", error=str(e)))


@register_handler("drop_item")
def handle_drop_item(player_id: int, payload: dict) -> dict:
    inv_id = payload["inv_id"]
    player = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))
    inv    = execute_one(
        "SELECT * FROM inventory_items WHERE id = ? AND player_id = ?",
        (inv_id, player_id)
    )
    if inv is None:
        raise ValueError("Item not found.")

    # Cannot drop equipped items
    equipped = {player.get("equipped_weapon_id"),
                player.get("equipped_armor_id"),
                player.get("equipped_special_id")}
    if inv_id in equipped:
        raise ValueError("Unequip the item before dropping it.")

    detail = _get_item_detail(inv["item_type"], inv["item_id"])
    item_name = detail["name"] if detail else "Unknown Item"

    with exclusive_transaction():
        execute_write("DELETE FROM inventory_items WHERE id = ?", (inv_id,))
        execute_write(
            """INSERT INTO item_history
               (player_id, item_type, item_id, item_name, event_type)
               VALUES (?, ?, ?, ?, 'DROPPED')""",
            (player_id, inv["item_type"], inv["item_id"], item_name)
        )
        # If special: return to pool
        if inv["item_type"] == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry
                   SET status = 'IN_POOL', current_owner_player_id = NULL,
                       inventory_item_id = NULL, last_released_method = 'DROPPED',
                       updated_at = ?
                   WHERE special_item_id = ?""",
                (datetime.utcnow().isoformat(), inv["item_id"])
            )
            # Global feed: special item returned to pool
            execute_write(
                """INSERT INTO daily_feed
                   (feed_scope, player_id, flavor_text, event_category)
                   VALUES ('GLOBAL', NULL, ?, 'ITEM')""",
                (f"{item_name} has returned to the loot pool.",)
            )
    return {"success": True}


# ─────────────────────────────────────────────────────────────────────────────
# POST /character/preference
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/character/preference", methods=["POST"])
def preference():
    pref = request.form.get("preference", "")
    try:
        enqueue_and_process(session["player_id"], "set_preference", {"preference": pref})
        return redirect(url_for("character.index", feedback=f"Combat preference set to {pref}."))
    except RuntimeError as e:
        return redirect(url_for("character.index", error=str(e)))


@register_handler("set_preference")
def handle_set_preference(player_id: int, payload: dict) -> dict:
    pref = payload.get("preference", "")
    valid = {"Aggressive", "Defensive", "Opportunist", "Balanced"}
    if pref not in valid:
        raise ValueError(f"Invalid preference. Choose from: {', '.join(valid)}")
    with exclusive_transaction():
        execute_write(
            "UPDATE players SET combat_preference = ? WHERE id = ?",
            (pref, player_id)
        )
    return {"success": True}


################################################################################
# FILE: routes/combat.py + routes/scoreboards.py (stubs)
################################################################################

# routes/combat.py
# All in-combat terminal-fragment POST routes.
# Full implementation in Phase 5 (boss/minion) and Phase 6 (PvP).
# Stubs here so the app runs cleanly during Phase 3.

from flask import Blueprint, render_template
from routes.actions import _error_fragment

bp = Blueprint("combat", __name__)


@bp.route("/combat/action", methods=["POST"])
def action():
    return _error_fragment("Combat coming in Phase 5.")


@bp.route("/combat/steal", methods=["POST"])
def steal():
    return _error_fragment("Combat coming in Phase 5.")


@bp.route("/combat/steal/confirm", methods=["POST"])
def steal_confirm():
    return _error_fragment("Combat coming in Phase 5.")


@bp.route("/combat/extend", methods=["POST"])
def extend():
    return _error_fragment("Combat coming in Phase 6.")


@bp.route("/combat/resolve", methods=["POST"])
def resolve():
    return _error_fragment("Combat coming in Phase 6.")


################################################################################
# routes/scoreboards.py
# Full-page leaderboards. All data computed via live DB queries.
# Full implementation in Phase 9 — stub here so blueprint registers cleanly.
################################################################################

from flask import Blueprint as _Blueprint, render_template as _render_template, g as _g
from database import execute as _execute

scoreboards_bp = _Blueprint("scoreboards", __name__)


@scoreboards_bp.route("/scoreboards")
def index():
    # Stubs — full queries in Phase 9
    return _render_template("scoreboards/scoreboards.html",
                            top_level=[],
                            top_pvp_kills=[],
                            top_boss_kills=[],
                            top_credits=[],
                            shame_board=[])


################################################################################
# FILE: templates/fragments/error.html + tavern_result.html + shop/shop.html + blacksmith/blacksmith.html + character/character.html + scoreboards/scoreboards.html
################################################################################

<!-- ============================================================ -->
<!-- FILE: templates/fragments/error.html                       -->
<!-- ============================================================ -->
<div class="fragment term-error"
     data-hp="{{ player.current_hp if player else '' }}"
     data-max-hp="{{ player.max_hp if player else '' }}"
     data-ap="{{ player.current_ap if player else '' }}"
     data-max-ap="{{ player.max_ap if player else '' }}"
     data-credits="{{ player.credits if player else '' }}">
    ⚠ {{ message }}
</div>


<!-- ============================================================ -->
<!-- FILE: templates/fragments/tavern_result.html               -->
<!-- ============================================================ -->
<div class="fragment"
     data-hp="{{ new_hp }}"
     data-max-hp="{{ max_hp }}"
     data-ap="{{ new_ap }}"
     data-max-ap="{{ player.max_ap }}"
     data-credits="{{ new_credits }}">
    <div class="term-line term-good">
        ═══ TAVERN ════════════════════════════════════════════════
    </div>
    <div class="term-line term-good">
        The barkeep patches you up. +{{ heal_amount }} HP restored.
    </div>
    <div class="term-line term-system">
        HP: {{ new_hp }}/{{ max_hp }} &nbsp;|&nbsp;
        Credits: {{ new_credits }} (-{{ cost_cr }}) &nbsp;|&nbsp;
        AP: {{ new_ap }}
    </div>
</div>


<!-- ============================================================ -->
<!-- FILE: templates/shop/shop.html                             -->
<!-- ============================================================ -->
{% extends "base.html" %}
{% block title %}Shop{% endblock %}
{% block content %}
<div id="page-content">
    <a href="{{ url_for('dashboard.index') }}" class="back-link">← Back to Dashboard</a>
    <h2 class="page-title">⚔ THE SHOP</h2>

    <div id="terminal-output">
        {% if feedback %}<span class="term-good">{{ feedback }}</span>{% endif %}
        {% if error %}<span class="term-error">⚠ {{ error }}</span>{% endif %}
    </div>

    {% if discount_pct > 0 %}
    <p class="term-good" style="margin-bottom:12px;">
        Your discount: {{ discount_pct }}% (PER bonus + gear)
    </p>
    {% endif %}

    <!-- BUY PANEL -->
    <h3 style="color:var(--amber);margin-bottom:8px;">Available Items</h3>
    {% if listings %}
    <table>
        <tr>
            <th>Name</th><th>Type</th><th>Level</th><th>Details</th>
            <th>Durability</th><th>Price</th><th></th>
        </tr>
        {% for item in listings %}
        <tr>
            <td>{{ item.name }}</td>
            <td>
                {% if item.item_type == 'WEAPON' %}
                    {{ item.weapon_type }} · {{ item.damage_die }} {{ item.damage_type }}
                {% elif item.item_type == 'ARMOR' %}
                    Armor · AC+{{ item.ac_bonus }}
                {% else %}
                    <span style="color:var(--amber)">★ Special</span>
                {% endif %}
            </td>
            <td>{{ item.level }}</td>
            <td style="font-size:11px;color:var(--grey);">
                {% if item.item_type == 'WEAPON' %}
                    {% if item.str_bonus %}STR+{{ item.str_bonus }} {% endif %}
                    {% if item.agi_bonus %}AGI+{{ item.agi_bonus }} {% endif %}
                {% elif item.item_type == 'ARMOR' %}
                    {% for dtype in ['blade','blunt','ballistic','energy','arcane','explosive','venom'] %}
                        {% if item['res_' + dtype] %}{{ dtype[:3].upper() }}✓ {% endif %}
                    {% endfor %}
                {% endif %}
            </td>
            <td>
                {% if item.durability_at_listing %}
                    {{ item.durability_at_listing }}%
                {% else %}
                    100%
                {% endif %}
            </td>
            <td>
                {% if item.discounted_price < item.price %}
                    <span style="text-decoration:line-through;color:var(--grey)">{{ item.price }}</span>
                    <span class="term-good">{{ item.discounted_price }}</span>
                {% else %}
                    {{ item.price }}
                {% endif %}
            </td>
            <td>
                <form method="POST" action="{{ url_for('shop.buy') }}">
                    <input type="hidden" name="listing_id" value="{{ item.listing_id }}">
                    <button type="submit" class="btn-small">Buy</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color:var(--grey)">Shop is empty — restocks at midnight.</p>
    {% endif %}

    <!-- SELL PANEL -->
    <h3 style="color:var(--amber);margin:20px 0 8px;">Sell Items</h3>
    {% if sellable %}
    <table>
        <tr>
            <th>Name</th><th>Type</th><th>Durability</th><th>Sell Price</th><th></th>
        </tr>
        {% for item in sellable %}
        <tr>
            <td>{{ item.name }}</td>
            <td>
                {% if item.item_type == 'SPECIAL' %}
                    <span style="color:var(--amber)">★ Special</span>
                {% else %}
                    {{ item.item_type|title }}
                {% endif %}
            </td>
            <td>{{ item.current_durability }}%</td>
            <td>
                {% if item.sell_price == 0 %}
                    <span style="color:var(--red)">0 credits</span>
                {% else %}
                    {{ item.sell_price }} credits
                {% endif %}
            </td>
            <td>
                <form method="POST" action="{{ url_for('shop.sell') }}"
                      {% if item.sell_price == 0 %}
                      onsubmit="return confirm('Sell {{ item.name }} for 0 credits?');"
                      {% endif %}>
                    <input type="hidden" name="inv_id" value="{{ item.inv_id }}">
                    <button type="submit" class="btn-small {% if item.sell_price == 0 %}danger{% endif %}">
                        Sell
                    </button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color:var(--grey)">No unequipped items to sell.</p>
    {% endif %}
</div>
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/blacksmith/blacksmith.html                 -->
<!-- ============================================================ -->
{% extends "base.html" %}
{% block title %}Blacksmith{% endblock %}
{% block content %}
<div id="page-content">
    <a href="{{ url_for('dashboard.index') }}" class="back-link">← Back to Dashboard</a>
    <h2 class="page-title">🔧 BLACKSMITH</h2>

    <div id="terminal-output">
        {% if feedback %}<span class="term-good">{{ feedback }}</span>{% endif %}
        {% if error %}<span class="term-error">⚠ {{ error }}</span>{% endif %}
    </div>

    {% if blocked %}
    <p style="color:var(--grey)">{{ blocked_reason }}</p>
    {% else %}
    <form method="POST" action="{{ url_for('blacksmith.repair') }}">
        <table>
            <tr>
                <th><input type="checkbox" id="select-all"> All</th>
                <th>Item</th><th>Type</th><th>Durability</th>
                <th>Repair Cost</th><th>Equipped</th>
            </tr>
            {% for item in items %}
            <tr>
                <td>
                    <input type="checkbox" name="inv_ids" value="{{ item.inv_id }}"
                           class="item-checkbox" data-cost="{{ item.repair_cost }}">
                </td>
                <td>{{ item.name }}</td>
                <td>{{ item.item_type|title }}</td>
                <td>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <div style="width:80px;height:6px;background:var(--border);position:relative;">
                            <div class="dur-bar {% if item.current_durability < 25 %}low{% elif item.current_durability < 60 %}medium{% endif %}"
                                 style="width:{{ item.current_durability }}%"></div>
                        </div>
                        {{ item.current_durability }}%
                    </div>
                </td>
                <td>{{ item.repair_cost }} cr</td>
                <td>{% if item.is_equipped %}<span class="term-good">✓</span>{% endif %}</td>
            </tr>
            {% endfor %}
        </table>

        <div style="margin:12px 0;color:var(--amber);">
            Selected total: <span id="total-cost">0</span> credits
        </div>

        <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <button type="submit" name="mode" value="selected" class="auth-btn" style="width:auto;padding:8px 16px;">
                Repair Selected
            </button>
            <button type="submit" name="mode" value="equipped" class="auth-btn" style="width:auto;padding:8px 16px;">
                Repair Equipped Only
            </button>
            <button type="submit" name="mode" value="all" class="auth-btn" style="width:auto;padding:8px 16px;">
                Repair Everything
            </button>
        </div>
    </form>
    {% endif %}
</div>
{% endblock %}
{% block scripts %}
<script>
// Select-all checkbox
document.getElementById('select-all')?.addEventListener('change', function() {
    document.querySelectorAll('.item-checkbox').forEach(cb => cb.checked = this.checked);
    updateTotal();
});
// Running cost total
function updateTotal() {
    let total = 0;
    document.querySelectorAll('.item-checkbox:checked').forEach(cb => {
        total += parseInt(cb.dataset.cost) || 0;
    });
    document.getElementById('total-cost').textContent = total;
}
document.querySelectorAll('.item-checkbox').forEach(cb =>
    cb.addEventListener('change', updateTotal));
</script>
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/character/character.html                   -->
<!-- ============================================================ -->
{% extends "base.html" %}
{% block title %}Character Sheet{% endblock %}
{% block content %}
<div id="page-content">
    <a href="{{ url_for('dashboard.index') }}" class="back-link">← Back to Dashboard</a>
    <h2 class="page-title">📋 CHARACTER SHEET</h2>

    <div id="terminal-output">
        {% if feedback %}<span class="term-good">{{ feedback }}</span>{% endif %}
        {% if error %}<span class="term-error">⚠ {{ error }}</span>{% endif %}
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px;">

        <!-- LEFT: Core stats -->
        <div>
            <h3 style="color:var(--amber);margin-bottom:10px;">Stats</h3>
            <table>
                <tr><th>Stat</th><th>Base</th><th>With Gear</th></tr>
                <tr><td>STR</td><td>{{ player.str_stat }}</td><td id="d-str">{{ derived.str }}</td></tr>
                <tr><td>END</td><td>{{ player.end_stat }}</td><td id="d-end">{{ derived.end }}</td></tr>
                <tr><td>AGI</td><td>{{ player.agi_stat }}</td><td id="d-agi">{{ derived.agi }}</td></tr>
                <tr><td>LCK</td><td>{{ player.lck_stat }}</td><td id="d-lck">{{ derived.lck }}</td></tr>
                <tr><td>PER</td><td>{{ player.per_stat }}</td><td id="d-per">{{ derived.per }}</td></tr>
            </table>

            <h3 style="color:var(--amber);margin:14px 0 10px;">Derived</h3>
            <table>
                <tr><td>Armor Class</td><td id="d-ac">{{ derived.ac }}</td></tr>
                <tr><td>Max HP</td><td id="d-maxhp">{{ derived.max_hp }}</td></tr>
                <tr><td>Crit Threshold</td><td id="d-crit">{{ derived.crit_threshold }}+</td></tr>
                <tr><td>Inventory Limit</td><td id="d-invlimit">{{ derived.inv_limit }}</td></tr>
                <tr><td>Daily AP</td><td id="d-ap">{{ derived.daily_ap }}</td></tr>
                <tr><td>HP Regen/AP</td><td id="d-regen">{{ derived.passive_regen }}</td></tr>
                <tr><td>Shop Discount</td><td id="d-discount">{{ derived.shop_discount_pct }}%</td></tr>
                {% if derived.extra_attack %}
                <tr><td colspan="2" class="term-amber">★ Extra Attack active</td></tr>
                {% endif %}
            </table>
        </div>

        <!-- RIGHT: Combat preference + Equipment -->
        <div>
            <h3 style="color:var(--amber);margin-bottom:10px;">Combat Preference</h3>
            <form method="POST" action="{{ url_for('character.preference') }}">
                <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:14px;">
                    {% for pref in preferences %}
                    <label style="cursor:pointer;">
                        <input type="radio" name="preference" value="{{ pref }}"
                               {% if player.combat_preference == pref %}checked{% endif %}>
                        <span style="color:{% if player.combat_preference == pref %}var(--green){% else %}var(--grey){% endif %}">
                            {{ pref }}
                        </span>
                    </label>
                    {% endfor %}
                </div>
                <button type="submit" class="btn-small">Update</button>
            </form>

            <h3 style="color:var(--amber);margin:14px 0 10px;">Equipped</h3>
            {% for slot, item in equipped.items() %}
            <div style="margin-bottom:8px;padding:6px;background:var(--bg-input);border:1px solid var(--border);">
                <span style="color:var(--grey);font-size:11px;">{{ slot|upper }}</span>
                {% if item %}
                <div>{{ item.name }}
                    <span style="color:var(--grey);font-size:11px;">({{ item.current_durability }}%)</span>
                </div>
                <form method="POST" action="{{ url_for('character.unequip') }}" style="display:inline">
                    <input type="hidden" name="slot" value="{{ slot }}">
                    <button type="submit" class="btn-small">Unequip</button>
                </form>
                {% else %}
                <div style="color:var(--dim)">— empty —</div>
                {% endif %}
            </div>
            {% endfor %}
        </div>
    </div>

    <section class="active-effects-panel" aria-labelledby="active-effects-title">
        <h3 id="active-effects-title">Active Effects</h3>
        {% if active_effects %}
        <div class="active-effects-list">
            {% for effect in active_effects %}
            <div class="active-effect {{ 'effect-good' if effect.is_good else 'effect-bad' }}">
                <span>{{ effect.description }}</span>
                <span class="active-effect-duration">Until {{ effect.expires }}</span>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <p class="active-effects-empty">No temporary effects are currently active.</p>
        {% endif %}
    </section>

    <!-- INVENTORY TABLE -->
    <h3 style="color:var(--amber);margin-bottom:10px;">
        Inventory
        <span style="font-size:12px;color:{% if player.is_overencumbered %}var(--red){% else %}var(--grey){% endif %}">
            ({{ player.inventory_count }}/{{ player.inventory_limit }}
            {% if player.is_overencumbered %} — OVER ENCUMBERED{% endif %})
        </span>
    </h3>
    {% if inventory %}
    <table>
        <tr>
            <th>Name</th><th>Type</th><th>Durability</th>
            <th>Equipped</th><th colspan="2">Actions</th>
        </tr>
        {% for item in inventory %}
        <tr id="item-row-{{ item.inv_id }}">
            <td>
                {% if item.item_type == 'SPECIAL' %}
                <span style="color:var(--amber)">★ </span>
                {% endif %}
                {{ item.name }}
            </td>
            <td style="font-size:11px;color:var(--grey);">
                {% if item.item_type == 'WEAPON' %}
                    {{ item.weapon_type }} {{ item.damage_die }} {{ item.damage_type }}
                {% elif item.item_type == 'ARMOR' %}
                    Armor AC+{{ item.ac_bonus }}
                {% else %}
                    Special
                {% endif %}
            </td>
            <td>
                <div style="display:flex;align-items:center;gap:6px;">
                    <div style="width:60px;height:5px;background:var(--border);">
                        <div class="dur-bar {% if item.current_durability < 25 %}low{% elif item.current_durability < 60 %}medium{% endif %}"
                             style="width:{{ item.current_durability }}%"></div>
                    </div>
                    {{ item.current_durability }}%
                </div>
            </td>
            <td>{% if item.is_equipped %}<span class="term-good">✓</span>{% endif %}</td>
            <td>
                {% if not item.is_equipped %}
                <form method="POST" action="{{ url_for('character.equip') }}"
                      data-inv-id="{{ item.inv_id }}"
                      data-item-type="{{ item.item_type }}"
                      class="equip-form">
                    <input type="hidden" name="inv_id" value="{{ item.inv_id }}">
                    <button type="submit" class="btn-small">Equip</button>
                </form>
                {% endif %}
            </td>
            <td>
                {% if not item.is_equipped %}
                <form method="POST" action="{{ url_for('character.drop') }}"
                      onsubmit="return confirm('Permanently drop {{ item.name }}?');">
                    <input type="hidden" name="inv_id" value="{{ item.inv_id }}">
                    <button type="submit" class="btn-small danger">Drop</button>
                </form>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color:var(--grey)">Your inventory is empty.</p>
    {% endif %}
</div>
{% endblock %}

{% block scripts %}
<script>
// Live stat preview on equip form submission
// Intercept equip form, fetch /character/preview with new loadout, update stat display
const previewUrl = "{{ url_for('character.preview') }}";

document.querySelectorAll('.equip-form').forEach(form => {
    form.addEventListener('submit', async (e) => {
        // Let the form submit normally for the actual equip
        // but also fetch preview to update stats live
        const invId    = form.dataset.invId;
        const itemType = form.dataset.itemType;
        // No need to prevent default — we let the server redirect handle it
        // The stat preview feature is for interactive checkbox-style UX in future;
        // for now equip always does a full redirect back to /character
    });
});
</script>
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/scoreboards/scoreboards.html               -->
<!-- ============================================================ -->
{% extends "base.html" %}
{% block title %}Scoreboards{% endblock %}
{% block content %}
<div id="page-content">
    <a href="{{ url_for('dashboard.index') }}" class="back-link">← Back to Dashboard</a>
    <h2 class="page-title">🏆 SCOREBOARDS</h2>
    <p style="color:var(--grey)">Full leaderboards coming in Phase 9.</p>
</div>
{% endblock %}

