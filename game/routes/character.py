"""Character sheet, inventory equipment, item dropping, and combat preferences."""
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
                      exclusive_transaction, get_all_settings,
                      get_player_bonus_profile, get_player_perks)
from queue_handler import enqueue_and_process, register_handler
from combat import engine
import config_defaults as cfg

bp = Blueprint("character", __name__)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# GET /character
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/character")
def index():
    """Handle the index workflow."""
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
    level_history = execute(
        """SELECT level_reached, stat_increased, timestamp
           FROM level_up_history WHERE player_id = ? ORDER BY level_reached DESC, id DESC""",
        (player["id"],)
    )
    perks = get_player_perks(player["id"])

    return render_template(
        "character/character.html",
        inventory=inventory,
        equipped=equipped,
        derived=derived,
        active_effects=active_effects,
        level_history=level_history,
        perks=perks,
        preferences=["Aggressive", "Defensive", "Opportunist", "Balanced"],
        feedback=request.args.get("feedback"),
        error=request.args.get("error"),
    )


@bp.route("/equipment")
def equipment():
    """Render the dedicated equipment comparison and loadout screen."""
    player = g.player
    if player.get("in_combat"):
        return redirect(url_for("dashboard.index"))
    inventory = _get_full_inventory(player)
    equipped = {
        "weapon": _find_equipped(inventory, player.get("equipped_weapon_id")),
        "armor": _find_equipped(inventory, player.get("equipped_armor_id")),
        "special": _find_equipped(inventory, player.get("equipped_special_id")),
    }
    return render_template(
        "character/equipment.html",
        inventory=inventory,
        equipped=equipped,
        derived=_calc_derived_stats(player, equipped, get_all_settings()),
        feedback=request.args.get("feedback"),
        error=request.args.get("error"),
    )


def _management_redirect(**values):
    """Return to the equipment screen only when that form requested it."""
    endpoint = "character.equipment" if request.form.get("return_to") == "equipment" else "character.index"
    return redirect(url_for(endpoint, **values))


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
    """Load full inventory from current database state."""
    # Use the Shop's authoritative resale calculation so the equipment screen
    # never advertises a different value than the player will actually receive.
    from routes.shop import _calc_sell_price
    equipped_ids = {
        player.get("equipped_weapon_id"),
        player.get("equipped_armor_id"),
        player.get("equipped_special_id"),
    } - {None}

    rows = execute(
        """SELECT ii.*,EXISTS(SELECT 1 FROM auction_listings a
                              WHERE a.inventory_item_id=ii.id AND a.status='ACTIVE') AS is_on_auction
           FROM inventory_items ii WHERE player_id = ? ORDER BY item_type, acquired_at""",
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
            "sell_price": _calc_sell_price(detail, player),
        })
    return result


def _find_equipped(inventory: list, inv_id) -> dict | None:
    """Provide the internal find equipped operation used by this module."""
    if inv_id is None:
        return None
    return next((i for i in inventory if i["inv_id"] == inv_id), None)


def _get_item_detail(item_type: str, item_id: int) -> dict | None:
    """Load item detail from current database state."""
    table = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}.get(item_type)
    if not table:
        return None
    return execute_one(f"SELECT * FROM {table} WHERE id = ?", (item_id,))


def _calc_derived_stats(player: dict, equipped: dict, settings: dict) -> dict:
    """Compute the same loadout-derived values that combat will use."""
    w = equipped.get("weapon")
    a = equipped.get("armor")
    s = equipped.get("special")
    b = get_player_bonus_profile(player["id"], s)

    str_total = player["str_stat"] + (w.get("str_bonus", 0) if w else 0) + \
                (a.get("str_bonus", 0) if a else 0) + int(b.get("str_bonus", 0) or 0)
    end_total = player["end_stat"] + (w.get("end_bonus", 0) if w else 0) + \
                (a.get("end_bonus", 0) if a else 0) + int(b.get("end_bonus", 0) or 0)
    agi_total = player["agi_stat"] + (w.get("agi_bonus", 0) if w else 0) + \
                (a.get("agi_bonus", 0) if a else 0) + int(b.get("agi_bonus", 0) or 0)
    lck_total = player["lck_stat"] + (w.get("lck_bonus", 0) if w else 0) + \
                (a.get("lck_bonus", 0) if a else 0) + int(b.get("lck_bonus", 0) or 0)
    per_total = player["per_stat"] + (w.get("per_bonus", 0) if w else 0) + \
                (a.get("per_bonus", 0) if a else 0) + int(b.get("per_bonus", 0) or 0)

    ac_bonus     = (a.get("ac_bonus", 0) if a else 0) + int(b.get("ac_bonus", 0) or 0)
    ac           = 10 + math.floor(agi_total / 2) + ac_bonus
    max_hp       = 10 + end_total + (5 * player["level"])
    inv_limit    = settings.get("INVENTORY_LIMIT", cfg.INVENTORY_LIMIT) + \
                   math.floor(str_total / 2)
    crit_thresh  = max(
        settings.get("CRIT_MIN_THRESHOLD", cfg.CRIT_MIN_THRESHOLD),
        settings.get("CRIT_BASE_THRESHOLD", cfg.CRIT_BASE_THRESHOLD) -
        math.floor(lck_total / settings.get("CRIT_LCK_DIVISOR", cfg.CRIT_LCK_DIVISOR))
    )
    if b:
        crit_thresh = max(
            settings.get("CRIT_MIN_THRESHOLD", cfg.CRIT_MIN_THRESHOLD),
            crit_thresh - int(round(float(b.get("crit_chance_bonus", 0) or 0) * 20))
        )
    shop_discount= min(
        math.floor(per_total / 2) + int(float(b.get("shop_discount", 0) or 0) * 100),
        int(settings.get("SHOP_DISCOUNT_MAX", cfg.SHOP_DISCOUNT_MAX) * 100)
    )
    daily_ap     = settings.get("BASE_DAILY_AP", cfg.BASE_DAILY_AP) + \
                   math.floor(end_total / 2) + int(b.get("bonus_ap", 0) or 0)
    passive_regen= settings.get("AP_PASSIVE_HP_REGEN", cfg.AP_PASSIVE_HP_REGEN) + \
                   math.floor(end_total / settings.get("END_HP_REGEN_DIVISOR", cfg.END_HP_REGEN_DIVISOR)) + \
                   int(b.get("hp_regen_bonus", 0) or 0)

    # Show a pre-resistance range rather than a misleading average. Actual
    # damage can still change through criticals, resistances, weaknesses,
    # temporary effects, and encounter balance scaling.
    weapon_name = w.get("name") if w else "Fists"
    weapon_type = w.get("weapon_type", "Melee") if w else "Melee"
    damage_die = w.get("damage_die", "d4") if w else "d4"
    damage_type = w.get("damage_type", "Blunt") if w else "Blunt"
    try:
        count_text, sides_text = str(damage_die).lower().split("d", 1)
        die_count = int(count_text or 1)
        die_sides = int(sides_text)
        if die_count < 1 or die_sides < 1:
            raise ValueError
    except (TypeError, ValueError):
        die_count, die_sides = 1, 4
    attack_stat = str_total if weapon_type == "Melee" else agi_total
    attack_modifier = math.floor(attack_stat / 2)
    attack_roll_modifier = attack_modifier + engine.proficiency_bonus(player["level"])
    initiative_modifier = math.floor(agi_total / 2) + \
                          int(b.get("initiative_bonus", 0) or 0)
    opposed_modifier = math.floor(agi_total / 2) + math.floor(lck_total / 2)
    steal_roll_bonus = int(float(b.get("steal_bonus", 0) or 0) * 20)
    steal_modifier = opposed_modifier + steal_roll_bonus
    escape_modifier = opposed_modifier
    observe_modifier = opposed_modifier + math.floor(per_total / 2)
    components = b.get("bonus_damage_components", [])
    bonus_damage = sum(int(part.get("amount", 0)) for part in components)
    bonus_damage_type = ", ".join(dict.fromkeys(part.get("type", "") for part in components if part.get("type")))
    damage_min = die_count + attack_modifier + bonus_damage
    damage_max = (die_count * die_sides) + attack_modifier + bonus_damage
    damage_types = [damage_type]
    for component in components:
        component_type = component.get("type")
        if component_type and component_type not in damage_types:
            damage_types.append(component_type)

    # Armor and specials are independent resistance sources. Preserve the
    # count because combat treats two matching sources as stacked resistance.
    resistance_counts = {}
    for resistance_type in ("Blade", "Blunt", "Ballistic", "Energy",
                            "Arcane", "Explosive", "Venom"):
        column = f"res_{resistance_type.lower()}"
        sources = int(bool(a and a.get(column))) + int(b.get(column, 0) or 0)
        if sources:
            resistance_counts[resistance_type] = sources
    resistances = [
        f"{name} ×{count}" if count > 1 else name
        for name, count in resistance_counts.items()
    ]

    crit_chance_pct = max(0, min(100, (21 - crit_thresh) * 5))
    sell_bonus_pct = int(float(b.get("sell_bonus", 0) or 0) * 100)
    durability_reduction_pct = int(float(b.get("durability_reduction", 0) or 0) * 100)
    encounter_bonus_pct = int(float(b.get("encounter_bonus", 0) or 0) * 100)
    brace_heal_pct = int(settings.get("BRACE_HEAL_PERCENT", cfg.BRACE_HEAL_PERCENT) * 100)
    tavern_heal_pct = int(settings.get("TAVERN_HEAL_PERCENT", cfg.TAVERN_HEAL_PERCENT) * 100)
    inventory_count = int(player.get("inventory_count", 0) or 0)
    special_effects = []
    if b:
        if b.get("extra_attack"): special_effects.append("Extra attack enabled")
        if bonus_damage: special_effects.append(f"+{bonus_damage} {bonus_damage_type or 'bonus'} damage")
        if b.get("bonus_ap"): special_effects.append(f"+{int(b['bonus_ap'])} daily AP")
        if b.get("hp_regen_bonus"): special_effects.append(f"+{int(b['hp_regen_bonus'])} HP regeneration per AP")
        if durability_reduction_pct: special_effects.append(f"{durability_reduction_pct}% less durability loss")
        if b.get("xp_multiplier"): special_effects.append(f"+{int(b['xp_multiplier'] * 100)}% XP rewards")
        if b.get("credit_multiplier"): special_effects.append(f"+{int(b['credit_multiplier'] * 100)}% credit rewards")

    return {
        "str": str_total, "end": end_total, "agi": agi_total,
        "lck": lck_total, "per": per_total,
        "ac": ac, "max_hp": max_hp, "inv_limit": inv_limit,
        "crit_threshold": crit_thresh, "crit_chance_pct": crit_chance_pct,
        "crit_range": f"{crit_thresh}-20" if crit_thresh < 20 else "20",
        "shop_discount_pct": shop_discount,
        "daily_ap": daily_ap, "passive_regen": passive_regen,
        "weapon_name": weapon_name, "weapon_type": weapon_type,
        "damage_die": damage_die, "damage_type": damage_type,
        "attack_modifier": attack_roll_modifier,
        "initiative_modifier": initiative_modifier,
        "steal_modifier": steal_modifier, "steal_roll_bonus": steal_roll_bonus,
        "escape_modifier": escape_modifier, "observe_modifier": observe_modifier,
        "damage_min": damage_min, "damage_max": damage_max,
        "crit_damage_min": int(damage_min * 2 * (1 + float(b.get("crit_dmg_multiplier", 0) or 0))),
        "crit_damage_max": int(damage_max * 2 * (1 + float(b.get("crit_dmg_multiplier", 0) or 0))),
        "bonus_damage": bonus_damage, "bonus_damage_type": bonus_damage_type,
        "damage_types": damage_types, "resistances": resistances,
        "resistance_counts": resistance_counts,
        "resistance_sources": sum(resistance_counts.values()),
        "extra_attack": bool(b.get("extra_attack")),
        "xp_multiplier_pct": int(float(b.get("xp_multiplier", 0) or 0) * 100),
        "credit_multiplier_pct": int(float(b.get("credit_multiplier", 0) or 0) * 100),
        "sell_bonus_pct": sell_bonus_pct,
        "durability_reduction_pct": durability_reduction_pct,
        "encounter_bonus_pct": encounter_bonus_pct,
        "brace_heal_pct": brace_heal_pct, "tavern_heal_pct": tavern_heal_pct,
        "inventory_count": inventory_count, "is_overencumbered": inventory_count > inv_limit,
        "overencumbered_ap_multiplier": settings.get("OVERENCUMBERED_AP_MULTIPLIER", cfg.OVERENCUMBERED_AP_MULTIPLIER),
        "overencumbered_ac_penalty": settings.get("OVERENCUMBERED_AC_PENALTY", cfg.OVERENCUMBERED_AC_PENALTY),
        "overencumbered_attack_penalty": settings.get("OVERENCUMBERED_ATTACK_PENALTY", cfg.OVERENCUMBERED_ATTACK_PENALTY),
        "special_effects": special_effects,
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
        """Handle the load equipped workflow."""
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
    """Handle the equip workflow."""
    inv_id = request.form.get("inv_id", type=int)
    try:
        enqueue_and_process(session["player_id"], "equip", {"inv_id": inv_id})
        return _management_redirect(feedback="Item equipped.")
    except RuntimeError as e:
        return _management_redirect(error=str(e))


@register_handler("equip")
def handle_equip(player_id: int, payload: dict) -> dict:
    """Process the queued equip action against validated game state."""
    inv_id = payload["inv_id"]
    player = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))
    if player["in_combat"]:
        raise ValueError("Use Change Equipment on the combat screen while a fight is active.")
    inv    = execute_one(
        "SELECT * FROM inventory_items WHERE id = ? AND player_id = ?",
        (inv_id, player_id)
    )
    if inv is None:
        raise ValueError("Item not found in your inventory.")
    if execute_one(
        "SELECT 1 FROM auction_listings WHERE inventory_item_id=? AND status='ACTIVE'",
        (inv_id,)
    ):
        raise ValueError("That item is on auction hold and cannot be equipped.")

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
    """Handle the unequip workflow."""
    slot = request.form.get("slot")  # weapon / armor / special
    try:
        enqueue_and_process(session["player_id"], "unequip", {"slot": slot})
        return _management_redirect(feedback="Item unequipped.")
    except RuntimeError as e:
        return _management_redirect(error=str(e))


@register_handler("unequip")
def handle_unequip(player_id: int, payload: dict) -> dict:
    """Process the queued unequip action against validated game state."""
    slot = payload.get("slot", "").lower()
    player = execute_one("SELECT * FROM players WHERE id=?", (player_id,))
    if player["in_combat"]:
        raise ValueError("Equipment cannot be unequipped outside the combat turn system during a fight.")
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
    """Handle the drop workflow."""
    inv_id = request.form.get("inv_id", type=int)
    try:
        enqueue_and_process(session["player_id"], "drop_item", {"inv_id": inv_id})
        return _management_redirect(feedback="Item dropped.")
    except RuntimeError as e:
        return _management_redirect(error=str(e))


@register_handler("drop_item")
def handle_drop_item(player_id: int, payload: dict) -> dict:
    """Process the queued drop item action against validated game state."""
    inv_id = payload["inv_id"]
    player = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))
    if player["in_combat"]:
        raise ValueError("Items cannot be dropped during combat.")
    inv    = execute_one(
        "SELECT * FROM inventory_items WHERE id = ? AND player_id = ?",
        (inv_id, player_id)
    )
    if inv is None:
        raise ValueError("Item not found.")
    if execute_one(
        "SELECT 1 FROM auction_listings WHERE inventory_item_id=? AND status='ACTIVE'",
        (inv_id,)
    ):
        raise ValueError("That item is on auction hold and cannot be dropped.")

    # Cannot drop equipped items
    equipped = {player.get("equipped_weapon_id"),
                player.get("equipped_armor_id"),
                player.get("equipped_special_id")}
    if inv_id in equipped:
        raise ValueError("Unequip the item before dropping it.")

    detail = _get_item_detail(inv["item_type"], inv["item_id"])
    item_name = detail["name"] if detail else "Unknown Item"

    with exclusive_transaction():
        # Release the unique-item registry's inventory foreign key first.
        if inv["item_type"] == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry
                   SET status = 'IN_POOL', current_owner_player_id = NULL,
                       inventory_item_id = NULL, last_released_method = 'DROPPED',
                       updated_at = ?
                   WHERE special_item_id = ?""",
                (datetime.utcnow().isoformat(), inv["item_id"])
            )
        execute_write("DELETE FROM inventory_items WHERE id = ?", (inv_id,))
        execute_write(
            """INSERT INTO item_history
               (player_id, item_type, item_id, item_name, event_type)
               VALUES (?, ?, ?, ?, 'DROPPED')""",
            (player_id, inv["item_type"], inv["item_id"], item_name)
        )
        # If special: announce that it returned to the pool.
        if inv["item_type"] == "SPECIAL":
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
    """Handle the preference workflow."""
    pref = request.form.get("preference", "")
    try:
        enqueue_and_process(session["player_id"], "set_preference", {"preference": pref})
        return redirect(url_for("character.index", feedback=f"Combat preference set to {pref}."))
    except RuntimeError as e:
        return redirect(url_for("character.index", error=str(e)))


@register_handler("set_preference")
def handle_set_preference(player_id: int, payload: dict) -> dict:
    """Process the queued set preference action against validated game state."""
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
