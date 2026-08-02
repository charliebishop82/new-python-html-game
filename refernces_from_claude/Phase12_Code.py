################################################################################
# PHASE 12 CODE — Boss & Minion Drop Table Logic
# BBS-Inspired Multiplayer Dueling Game
#
# File changed: combat/actions.py
#
# What was missing:
#   finalize_combat() awarded XP and handled PvP credit/item theft correctly,
#   but never rolled the boss/minion drop tables defined in the Excel content.
#   Defeating a boss gave XP only — no credits, no weapon, no armor, no special.
#
# What this adds:
#   _get_master_for_opponent()  — looks up master table row for boss/minion
#   _award_drops()              — rolls all 4 drop table entries in sequence:
#       1. Credits (random between drop_credit_min and drop_credit_max)
#          + credit_multiplier bonus from equipped special item
#       2. Weapon drop (roll vs drop_weapon_chance, skip if already owned)
#       3. Armor drop  (roll vs drop_armor_chance, skip if already owned)
#       4. Special drop (roll vs drop_special_item_chance, only if IN_POOL)
#   All drops write to inventory_items, item_history, and daily_feed.
#   Special item drops update special_item_registry and fire a global feed entry.
#   Drop results are returned in final_result dict and displayed in combat_result.html.
#
# Integration point:
#   In finalize_combat(), after kill_count update and instance reset, add:
#       drops = _award_drops(player_id=attacker["id"], player=attacker,
#                            opponent=opp, combat_type=session["combat_type"],
#                            master_row=_get_master_for_opponent(opp, session["combat_type"]),
#                            settings=settings,
#                            equipped_special=state["attacker_equipped"].get("special"))
#   Then include drops in the return dict (see RETURN_DICT_PATCH below).
################################################################################

# =============================================================================
# PHASE 12 — Boss & Minion Drop Table Logic
# =============================================================================
# File changed: combat/actions.py
#
# In finalize_combat(), inside the BOSS/MINION winner block,
# immediately after the kill_count / instance reset block, add the
# _award_drops() call. The full replacement for that section is below.
#
# Drop sequence (boss and minion):
#   1. Credits: random between drop_credit_min and drop_credit_max
#               multiplied by credit_multiplier from equipped special
#   2. Weapon:  roll against drop_weapon_chance — award the boss/minion's weapon
#               if not already in player inventory
#   3. Armor:   roll against drop_armor_chance — award the boss/minion's armor
#               if not already in player inventory
#   4. Special: roll against drop_special_item_chance — only if IN_POOL
#               awarded via special_item_registry
#
# Items already owned by the player (same item_id) are skipped silently.
# Special items follow the registry (one copy in the world).
# =============================================================================


DROP_LOGIC_PATCH = """
# In combat/actions.py, inside finalize_combat(), in the BOSS/MINION block,
# after the kill_count update and instance reset, add:

        # ── Drop table ────────────────────────────────────────────────────────
        drops = _award_drops(
            player_id=attacker['id'],
            player=attacker,
            opponent=opp,
            combat_type=session['combat_type'],
            master_row=_get_master_for_opponent(opp, session['combat_type']),
            settings=settings,
            equipped_special=state['attacker_equipped'].get('special'),
        )
        # Include drops in the return value for the result fragment to display
"""


AWARD_DROPS_FUNCTION = '''
# Add these two functions to combat/actions.py

def _get_master_for_opponent(opponent: dict, combat_type: str) -> dict | None:
    """Load the master table row for a boss or minion by name."""
    col = "boss_id" if combat_type == "BOSS" else "minion_id"
    # opponent dict has 'id' which is the bosses/minions table id
    return execute_one(
        f"SELECT * FROM master WHERE {col} = (SELECT id FROM "
        f"{'bosses' if combat_type == 'BOSS' else 'minions'} WHERE name = ?)",
        (opponent["name"],)
    )


def _award_drops(player_id: int, player: dict, opponent: dict,
                 combat_type: str, master_row: dict | None,
                 settings: dict, equipped_special: dict | None) -> dict:
    """Roll all drop table entries for a defeated boss or minion.
    Returns dict with keys: credits, weapon, armor, special (each None or item name)."""
    import random
    from datetime import datetime

    result = {"credits": 0, "weapon": None, "armor": None, "special": None}

    if not master_row:
        return result

    # ── Credits ───────────────────────────────────────────────────────────────
    cr_min  = opponent.get("drop_credit_min", 0)
    cr_max  = opponent.get("drop_credit_max", 0)
    if cr_max > 0:
        credits = random.randint(cr_min, cr_max)
        # Apply credit multiplier from equipped special item
        if equipped_special and equipped_special.get("credit_multiplier"):
            credits = int(credits * (1 + equipped_special["credit_multiplier"]))
        if credits > 0:
            with exclusive_transaction():
                execute_write(
                    "UPDATE players SET credits = credits + ? WHERE id = ?",
                    (credits, player_id)
                )
            result["credits"] = credits

    # ── Determine which item IDs to roll for ──────────────────────────────────
    if combat_type == "BOSS":
        weapon_id  = master_row.get("boss_weapon_id")
        armor_id   = master_row.get("boss_armor_id")
        special_id = master_row.get("boss_special_item_id")
    else:
        weapon_id  = master_row.get("minion_weapon_id")
        armor_id   = master_row.get("minion_armor_id")
        special_id = master_row.get("minion_special_item_id")

    # ── Weapon drop ───────────────────────────────────────────────────────────
    weapon_chance = opponent.get("drop_weapon_chance", 0.0)
    if weapon_id and random.random() < weapon_chance:
        # Skip if player already owns this weapon
        already_owned = execute_one(
            "SELECT id FROM inventory_items WHERE player_id = ? AND item_type = 'WEAPON' AND item_id = ?",
            (player_id, weapon_id)
        )
        if not already_owned:
            weapon_detail = execute_one("SELECT * FROM weapons WHERE id = ?", (weapon_id,))
            if weapon_detail:
                with exclusive_transaction():
                    execute_write(
                        """INSERT INTO inventory_items
                           (player_id, item_type, item_id, current_durability, acquired_method)
                           VALUES (?, 'WEAPON', ?, ?, ?)""",
                        (player_id, weapon_id,
                         weapon_detail.get("starting_durability", 100),
                         "BOSS_DROP" if combat_type == "BOSS" else "MINION_DROP")
                    )
                    execute_write(
                        """INSERT INTO item_history
                           (player_id, item_type, item_id, item_name, event_type)
                           VALUES (?, 'WEAPON', ?, ?, ?)""",
                        (player_id, weapon_id, weapon_detail["name"],
                         "RECEIVED_BOSS_DROP" if combat_type == "BOSS" else "RECEIVED_MINION_DROP")
                    )
                result["weapon"] = weapon_detail["name"]

    # ── Armor drop ────────────────────────────────────────────────────────────
    armor_chance = opponent.get("drop_armor_chance", 0.0)
    if armor_id and random.random() < armor_chance:
        already_owned = execute_one(
            "SELECT id FROM inventory_items WHERE player_id = ? AND item_type = 'ARMOR' AND item_id = ?",
            (player_id, armor_id)
        )
        if not already_owned:
            armor_detail = execute_one("SELECT * FROM armor WHERE id = ?", (armor_id,))
            if armor_detail:
                with exclusive_transaction():
                    execute_write(
                        """INSERT INTO inventory_items
                           (player_id, item_type, item_id, current_durability, acquired_method)
                           VALUES (?, 'ARMOR', ?, ?, ?)""",
                        (player_id, armor_id,
                         armor_detail.get("starting_durability", 100),
                         "BOSS_DROP" if combat_type == "BOSS" else "MINION_DROP")
                    )
                    execute_write(
                        """INSERT INTO item_history
                           (player_id, item_type, item_id, item_name, event_type)
                           VALUES (?, 'ARMOR', ?, ?, ?)""",
                        (player_id, armor_id, armor_detail["name"],
                         "RECEIVED_BOSS_DROP" if combat_type == "BOSS" else "RECEIVED_MINION_DROP")
                    )
                result["armor"] = armor_detail["name"]

    # ── Special item drop ─────────────────────────────────────────────────────
    special_chance = opponent.get("drop_special_item_chance", 0.0)
    if special_id and random.random() < special_chance:
        # Check registry — must be IN_POOL
        reg = execute_one(
            "SELECT * FROM special_item_registry WHERE special_item_id = ?",
            (special_id,)
        )
        if reg and reg["status"] == "IN_POOL":
            special_detail = execute_one("SELECT * FROM special_items WHERE id = ?", (special_id,))
            if special_detail:
                with exclusive_transaction():
                    inv_id = execute_write(
                        """INSERT INTO inventory_items
                           (player_id, item_type, item_id, current_durability, acquired_method)
                           VALUES (?, 'SPECIAL', ?, ?, ?)""",
                        (player_id, special_id,
                         special_detail.get("starting_durability", 100),
                         "BOSS_DROP" if combat_type == "BOSS" else "MINION_DROP")
                    )
                    execute_write(
                        """UPDATE special_item_registry
                           SET status = 'IN_INVENTORY',
                               current_owner_player_id = ?,
                               inventory_item_id = ?,
                               last_acquired_method = ?,
                               updated_at = ?
                           WHERE special_item_id = ?""",
                        (player_id, inv_id,
                         "BOSS_DROP" if combat_type == "BOSS" else "MINION_DROP",
                         datetime.utcnow().isoformat(), special_id)
                    )
                    execute_write(
                        """INSERT INTO item_history
                           (player_id, item_type, item_id, item_name, event_type)
                           VALUES (?, 'SPECIAL', ?, ?, ?)""",
                        (player_id, special_id, special_detail["name"],
                         "RECEIVED_BOSS_DROP" if combat_type == "BOSS" else "RECEIVED_MINION_DROP")
                    )
                    # Global feed: special item enters world
                    execute_write(
                        """INSERT INTO daily_feed
                           (feed_scope, player_id, flavor_text, event_category)
                           VALUES ('GLOBAL', NULL, ?, 'ITEM')""",
                        (f"The {special_detail['name']} has been claimed from {opponent['name']}.",)
                    )
                result["special"] = special_detail["name"]

    # ── Personal feed entry summarising all drops ─────────────────────────────
    drop_lines = []
    if result["credits"]: drop_lines.append(f"+{result['credits']} credits")
    if result["weapon"]:  drop_lines.append(f"Found: {result['weapon']}")
    if result["armor"]:   drop_lines.append(f"Found: {result['armor']}")
    if result["special"]: drop_lines.append(f"★ Seized: {result['special']}")

    if drop_lines:
        with exclusive_transaction():
            execute_write(
                """INSERT INTO daily_feed
                   (feed_scope, player_id, flavor_text, event_category)
                   VALUES ('PERSONAL', ?, ?, 'ITEM')""",
                (player_id, " | ".join(drop_lines))
            )

    return result
'''


# =============================================================================
# TEMPLATE PATCH — combat_result.html
# Add drop display to the post-combat result fragment.
# In templates/fragments/combat_result.html, after the xp/credits lines, add:
# =============================================================================

TEMPLATE_PATCH = """
<!-- In templates/fragments/combat_result.html, after the XP and credits lines: -->

{% if fr.drops %}
    {% if fr.drops.credits %}
    <div class="term-line term-good">+{{ fr.drops.credits }} credits looted</div>
    {% endif %}
    {% if fr.drops.weapon %}
    <div class="term-line term-blue">⚔ Dropped: {{ fr.drops.weapon }}</div>
    {% endif %}
    {% if fr.drops.armor %}
    <div class="term-line term-blue">🛡 Dropped: {{ fr.drops.armor }}</div>
    {% endif %}
    {% if fr.drops.special %}
    <div class="term-line term-amber">★ SPECIAL: {{ fr.drops.special }}</div>
    {% endif %}
{% endif %}
"""


# =============================================================================
# FINALIZE_COMBAT PATCH — include drops in return dict
# In finalize_combat(), after the _award_drops() call, update the return dict
# at the bottom of the function to include drops:
# =============================================================================

RETURN_DICT_PATCH = """
# At the bottom of finalize_combat(), change the return statement to:

    return {
        "winner_side":    winner_side,
        "result_type":    result_type,
        "xp_earned":      xp_earned,
        "credits_stolen": credits_stolen,
        "item_stolen":    item_stolen,
        "drops":          drops if session["combat_type"] in ("BOSS", "MINION") else None,
        "flavor":         global_text,
    }
"""
