"""Blacksmith display and queued durability-repair operations."""
# routes/blacksmith.py
# Full-page repair interface. Players select damaged items to repair,
# pay credits per item, with a LCK bonus roll for enhanced restoration.

import math
import logging
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, session, g
from database import (execute, execute_one, execute_write,
                      exclusive_transaction, get_all_settings, get_player,
                      encumbered_ap_cost)
from queue_handler import enqueue_and_process, register_handler
from combat import actions as combat_actions
import config_defaults as cfg
import random

bp = Blueprint("blacksmith", __name__)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# GET /blacksmith
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/blacksmith")
def index():
    """Handle the index workflow."""
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
    """Load item detail from current database state."""
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
    """Handle the repair workflow."""
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
    """Process the queued blacksmith repair action against validated game state."""
    settings    = get_all_settings()
    repair_base = settings.get("REPAIR_BASE_PERCENT",    cfg.REPAIR_BASE_PERCENT)
    lck_mult    = settings.get("REPAIR_LCK_MULTIPLIER",  cfg.REPAIR_LCK_MULTIPLIER)
    lck_cap     = settings.get("REPAIR_LCK_CAP",         cfg.REPAIR_LCK_CAP)
    cost_pct    = settings.get("REPAIR_COST_PERCENT",    cfg.REPAIR_COST_PERCENT)
    ap_cost     = settings.get("AP_COST_BLACKSMITH",     cfg.AP_COST_BLACKSMITH)

    player  = get_player(player_id)
    ap_cost = encumbered_ap_cost(player, ap_cost, settings)
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

    effective_player = combat_actions.apply_equipped_stat_bonuses(get_player(player_id))
    lck = effective_player["lck_stat"]
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
