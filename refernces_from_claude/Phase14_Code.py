################################################################################
# PHASE 14 CODE — Gap Closures
# BBS-Inspired Multiplayer Dueling Game
#
# Gaps closed:
#   1. Minion weapon steal  — combat/actions.py _boss_steal_result()
#      Priority: special -> minion weapon -> credits
#
#   2. Boss intel display   — routes/actions.py + combat_open.html
#      Full resistances, weaknesses, special names, last known HP shown
#
#   3. New player tutorial  — routes/auth.py _write_tutorial_feed()
#      11 personal feed entries written on character creation
#
#   4. Classes importer     — confirmed correct, no change needed
#   5. Settings sheet       — confirmed 89 rows populated, no change needed
################################################################################

# =============================================================================
# PHASE 14 — Gap Closures
# =============================================================================

# GAP 1: Minion weapon loot via Steal
MINION_STEAL_PATCH = '''
def _boss_steal_result(player_id, opponent, steal_bonus, settings, combat_type):
    import random, math
    from datetime import datetime

    base_chance   = settings.get("STEAL_SPECIAL_BASE_CHANCE", cfg.STEAL_SPECIAL_BASE_CHANCE)
    cr_multiplier = settings.get("STEAL_BOSS_CREDIT_MULTIPLIER", cfg.STEAL_BOSS_CREDIT_MULTIPLIER)
    player        = execute_one("SELECT lck_stat FROM players WHERE id = ?", (player_id,))
    lck_bonus     = math.floor(player["lck_stat"] / 2) / 100

    # Try special item first
    if random.random() < (base_chance + lck_bonus):
        association_type = "Boss" if combat_type == "BOSS" else "Minion"
        special_def = execute_one(
            """SELECT si.id, si.name, si.starting_durability
               FROM special_items si
               JOIN special_item_registry sir ON sir.special_item_id = si.id
               WHERE si.associated_to = ? AND si.association_type = ?
                 AND sir.status = 'IN_POOL'""",
            (opponent["name"], association_type)
        )
        if special_def:
            with exclusive_transaction():
                inv_id = execute_write(
                    """INSERT INTO inventory_items
                       (player_id, item_type, item_id, current_durability, acquired_method)
                       VALUES (?, 'SPECIAL', ?, ?, 'COMBAT_STEAL')""",
                    (player_id, special_def["id"], special_def.get("starting_durability", 100))
                )
                execute_write(
                    """UPDATE special_item_registry
                       SET status='IN_INVENTORY', current_owner_player_id=?,
                           inventory_item_id=?, last_acquired_method='COMBAT_STEAL', updated_at=?
                       WHERE special_item_id=?""",
                    (player_id, inv_id, datetime.utcnow().isoformat(), special_def["id"])
                )
                execute_write(
                    """INSERT INTO item_history
                       (player_id, item_type, item_id, item_name, event_type)
                       VALUES (?, 'SPECIAL', ?, ?, 'RECEIVED_COMBAT_STEAL')""",
                    (player_id, special_def["id"], special_def["name"])
                )
            return {"item_name": special_def["name"]}

    # Minion only: try to steal the minion weapon
    if combat_type == "MINION":
        master = execute_one(
            """SELECT m.minion_weapon_id, w.name as weapon_name, w.starting_durability
               FROM master m
               JOIN minions mn ON mn.id = m.minion_id
               JOIN weapons w  ON w.id  = m.minion_weapon_id
               WHERE mn.name = ?""",
            (opponent["name"],)
        )
        if master and master["minion_weapon_id"]:
            already_owned = execute_one(
                "SELECT id FROM inventory_items WHERE player_id = ? AND item_type = 'WEAPON' AND item_id = ?",
                (player_id, master["minion_weapon_id"])
            )
            if not already_owned:
                with exclusive_transaction():
                    execute_write(
                        """INSERT INTO inventory_items
                           (player_id, item_type, item_id, current_durability, acquired_method)
                           VALUES (?, 'WEAPON', ?, ?, 'COMBAT_STEAL')""",
                        (player_id, master["minion_weapon_id"], master.get("starting_durability", 100))
                    )
                    execute_write(
                        """INSERT INTO item_history
                           (player_id, item_type, item_id, item_name, event_type)
                           VALUES (?, 'WEAPON', ?, ?, 'RECEIVED_COMBAT_STEAL')""",
                        (player_id, master["minion_weapon_id"], master["weapon_name"])
                    )
                return {"item_name": master["weapon_name"]}

    # Credits fallback
    credits_stolen = int(opponent["level"] * (cr_multiplier + steal_bonus * cr_multiplier))
    with exclusive_transaction():
        execute_write("UPDATE players SET credits = credits + ? WHERE id = ?",
                      (credits_stolen, player_id))
    return {"credits": credits_stolen}
'''

# GAP 2: Boss intel detail display
INTEL_ROUTES_PATCH = '''
# In routes/actions.py _start_boss_fight(), replace the intel block with:

    intel        = None
    intel_detail = None
    if encounter_type == "BOSS":
        intel_row = execute_one(
            "SELECT * FROM boss_intel WHERE player_id = ? AND boss_id = ?",
            (player["id"], opponent["id"])
        )
        if intel_row:
            intel = intel_row
            damage_types = ["blade","blunt","ballistic","energy","arcane","explosive","venom"]
            resistances  = [t.upper() for t in damage_types if opponent_full.get(f"res_{t}")]
            weaknesses   = [t.upper() for t in damage_types if opponent_full.get(f"weak_{t}")]
            intel_detail = {
                "resistances":         resistances,
                "weaknesses":          weaknesses,
                "special_attack_name": opponent_full.get("special_attack_name"),
                "special_attack_type": opponent_full.get("special_attack_damage_type"),
                "special_buff_name":   opponent_full.get("special_buff_name"),
                "special_buff_type":   opponent_full.get("special_buff_type"),
                "current_hp":          opponent_full.get("current_hp"),
                "max_hp":              opponent_full.get("max_hp"),
            }

# Pass intel_detail=intel_detail to render_template(...)
'''

INTEL_TEMPLATE_PATCH = '''
<!-- In templates/fragments/combat_open.html replace the intel block with: -->

{% if intel and intel_detail %}
<div class="term-line term-blue">[KNOWN INTEL — previous encounter data]</div>
{% if intel_detail.resistances %}
<div class="term-line term-blue" style="font-size:11px;margin-left:12px;">
    Resistant to: {{ intel_detail.resistances | join(", ") }}
</div>
{% endif %}
{% if intel_detail.weaknesses %}
<div class="term-line term-good" style="font-size:11px;margin-left:12px;">
    Weak to: {{ intel_detail.weaknesses | join(", ") }}
</div>
{% endif %}
{% if intel_detail.special_attack_name %}
<div class="term-line term-amber" style="font-size:11px;margin-left:12px;">
    Special Attack: {{ intel_detail.special_attack_name }} ({{ intel_detail.special_attack_type }})
</div>
{% endif %}
{% if intel_detail.special_buff_name %}
<div class="term-line term-amber" style="font-size:11px;margin-left:12px;">
    Special Buff: {{ intel_detail.special_buff_name }} ({{ intel_detail.special_buff_type }})
</div>
{% endif %}
{% if intel_detail.current_hp is not none %}
<div class="term-line term-blue" style="font-size:11px;margin-left:12px;">
    Last known HP: {{ intel_detail.current_hp }}/{{ intel_detail.max_hp }}
</div>
{% endif %}
{% elif intel %}
<div class="term-line term-blue">[KNOWN INTEL — previous encounter logged]</div>
{% endif %}
'''

# GAP 3: New player tutorial
TUTORIAL_PATCH = '''
# In routes/auth.py, add after _award_starter_gear() call in character_create_post():

    _write_tutorial_feed(player_id)
    return redirect(url_for("dashboard.index"))


def _write_tutorial_feed(player_id: int):
    """Write onboarding feed entries so the terminal has context on first login."""
    from datetime import datetime, timedelta
    messages = [
        ("SYSTEM",       "Welcome. The world is dangerous. Here is what you need to know."),
        ("SYSTEM",       "AP (Action Points) fuel everything. You earn a daily allotment at midnight plus trickle bonuses every 6 hours. Spend them wisely."),
        ("SYSTEM",       "BOSS — Challenge a movie villain. Defeat them for XP, credits, and gear. Watch for phase transitions as their HP drops."),
        ("SYSTEM",       "PVP — Fight another player. Win to steal credits and items. Lose and you drop to 1 HP. Choose your targets carefully."),
        ("SYSTEM",       "TAVERN — Spend credits to restore HP. No AP cost once inside."),
        ("SYSTEM",       "BLACKSMITH — Repair damaged gear. Durability matters — broken weapons deal less damage."),
        ("SYSTEM",       "SHOP — Buy and sell weapons, armor, and special items. Special items are unique. Only one copy exists in the world at a time."),
        ("SYSTEM",       "OBSERVE in combat to learn an enemy's resistances and weaknesses. That intel is stored permanently for future fights."),
        ("SYSTEM",       "Level up by earning XP. Each level grants one permanent stat point. Choose carefully — there is no going back."),
        ("SYSTEM",       "You have been given starter gear. Visit your Character Sheet to equip it before your first fight."),
        ("RANDOM_EVENT", "Good luck out there. You will need it."),
    ]
    base_time = datetime.utcnow()
    with exclusive_transaction():
        for i, (category, text) in enumerate(messages):
            ts = (base_time + timedelta(seconds=i)).isoformat()
            execute_write(
                """INSERT INTO daily_feed
                   (feed_scope, player_id, flavor_text, event_category, occurred_at)
                   VALUES ('PERSONAL', ?, ?, ?, ?)""",
                (player_id, text, category, ts)
            )
'''

SUMMARY = """
Phase 14 — Gap Closures Summary
=================================

1. Minion weapon steal (combat/actions.py)
   _boss_steal_result() now has a three-step priority:
   special item -> minion weapon (from master table) -> credits
   Skips weapon if player already owns that item_id.

2. Boss intel detail (routes/actions.py + combat_open.html)
   _start_boss_fight() builds intel_detail dict with:
   resistances, weaknesses, special attack/buff names and types, last known HP.
   Template renders each field as a colour-coded terminal line.
   Falls back gracefully if intel_detail cannot be built.

3. New player tutorial (routes/auth.py)
   _write_tutorial_feed() called after character creation.
   11 staggered PERSONAL feed entries covering AP, boss, PvP,
   tavern, blacksmith, shop, observe, leveling, gear, and a farewell.
   Entries are ephemeral (cleared at midnight like all daily_feed rows).

4. Classes importer (importer.py)
   Confirmed _map_class() reads Description correctly. No change needed.

5. Settings sheet
   Confirmed 89 rows already populated. No change needed.
"""
