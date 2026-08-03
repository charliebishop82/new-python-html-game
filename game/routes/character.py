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
        effect_type = row["effect_type"]
        value = row["value"]
        if effect_type == "CURSED":
            description = f"Daily AP award -{int(round(value * 100))}%"
            is_good = False
        elif effect_type in stat_names:
            description = f"{stat_names[effect_type]} {int(value):+d}"
            is_good = value > 0
        else:
            description = effect_type.replace("_", " ").title()
            is_good = value >= 0
        effects.append({
            "description": description,
            "is_good": is_good,
            "expires": "Midnight reset",
        })
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
