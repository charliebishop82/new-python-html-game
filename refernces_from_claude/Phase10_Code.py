################################################################################
# PHASE 10 CODE — Temporary Stat Boost/Penalty Status Effects
# BBS-Inspired Multiplayer Dueling Game
#
# Files to patch (all are small, targeted changes):
#   1. importer.py        — Add 12 new effect types to VALID_EFFECT_TYPES
#   2. routes/actions.py  — Handle new effect types in _apply_random_event()
#   3. database.py        — get_player() reads + applies active stat modifiers
#   4. combat/engine.py   — calc_initiative() reads initiative_modifier
#   5. routes/dashboard.py — Pass active effects to template for display
#   6. templates/base.html — Show active stat effects in status block
#   7. static/style.css   — Add .effect-tag styles
#
# No schema changes required — status_effects table already supports
# arbitrary effect_type strings and is cleared at midnight step 0.
################################################################################

# =============================================================================
# PHASE 10 — Temporary Stat Boost/Penalty Status Effects
# =============================================================================
# Files changed:
#   1. routes/actions.py  — _apply_random_event() additions
#   2. database.py        — get_player() reads active stat effects
#   3. combat/engine.py   — initiative roll reads STAT_BOOST_INITIATIVE
#   4. importer.py        — VALID_EFFECT_TYPES additions
# =============================================================================


# =============================================================================
# FILE: importer.py  (patch — add to VALID_EFFECT_TYPES set)
# =============================================================================
IMPORTER_PATCH = """
# In importer.py, replace the VALID_EFFECT_TYPES set with this expanded version:

VALID_EFFECT_TYPES = {
    "CREDITS", "ITEM_AT_LEVEL", "BONUS_AP", "DURABILITY_RESTORE_RANDOM",
    "SPECIAL_ITEM_FROM_POOL", "HP_LOSS", "DURABILITY_LOSS_RANDOM",
    "XP_LOSS", "AP_REDUCTION_PERCENT",
    # New stat effect types
    "STAT_BOOST_STR", "STAT_BOOST_END", "STAT_BOOST_AGI",
    "STAT_BOOST_LCK", "STAT_BOOST_PER", "STAT_BOOST_INITIATIVE",
    "STAT_PENALTY_STR", "STAT_PENALTY_END", "STAT_PENALTY_AGI",
    "STAT_PENALTY_LCK", "STAT_PENALTY_PER", "STAT_PENALTY_INITIATIVE",
}
"""


# =============================================================================
# FILE: routes/actions.py  (patch — extend _apply_random_event())
# Add this block inside _apply_random_event(), after the AP_REDUCTION_PERCENT
# elif block and before the ITEM_AT_LEVEL block.
# =============================================================================
ACTIONS_PATCH = """
# In routes/actions.py, inside _apply_random_event(), add these elif blocks:

        elif effect in (
            "STAT_BOOST_STR", "STAT_BOOST_END", "STAT_BOOST_AGI",
            "STAT_BOOST_LCK", "STAT_BOOST_PER", "STAT_BOOST_INITIATIVE",
            "STAT_PENALTY_STR", "STAT_PENALTY_END", "STAT_PENALTY_AGI",
            "STAT_PENALTY_LCK", "STAT_PENALTY_PER", "STAT_PENALTY_INITIATIVE",
        ):
            # Insert a status_effect row — cleared at midnight step 0.
            # amount is positive for boosts, negative for penalties.
            execute_write(
                \"\"\"INSERT INTO status_effects (player_id, effect_type, value)
                   VALUES (?, ?, ?)\"\"\",
                (player_id, effect, float(amount))
            )
"""


# =============================================================================
# FILE: database.py  (patch — extend get_player() to apply stat effects)
# Replace the existing 'cursed' block in get_player() with this expanded version.
# Find the line: cursed = execute_one(...) and replace through is_cursed = ...
# =============================================================================
GET_PLAYER_PATCH = """
# In database.py, inside get_player(), replace:
#
#   cursed = execute_one(
#       \"SELECT value FROM status_effects WHERE player_id = ? AND effect_type = 'CURSED'\",
#       (player_id,)
#   )
#   is_cursed = cursed is not None
#
# With this expanded block:

    # Load all active status effects for this player
    active_effects = execute(
        \"SELECT effect_type, value FROM status_effects WHERE player_id = ?\",
        (player_id,)
    )
    is_cursed = any(e[\"effect_type\"] == \"CURSED\" for e in active_effects)

    # Build stat modifier map from active effects
    stat_modifiers = {"str": 0, "end": 0, "agi": 0, "lck": 0, "per": 0, "initiative": 0}
    for effect in active_effects:
        etype = effect[\"effect_type\"]
        val   = int(effect[\"value\"])
        if etype == \"STAT_BOOST_STR\":      stat_modifiers[\"str\"]        += val
        elif etype == \"STAT_BOOST_END\":    stat_modifiers[\"end\"]        += val
        elif etype == \"STAT_BOOST_AGI\":    stat_modifiers[\"agi\"]        += val
        elif etype == \"STAT_BOOST_LCK\":    stat_modifiers[\"lck\"]        += val
        elif etype == \"STAT_BOOST_PER\":    stat_modifiers[\"per\"]        += val
        elif etype == \"STAT_BOOST_INITIATIVE\": stat_modifiers[\"initiative\"] += val
        elif etype == \"STAT_PENALTY_STR\":  stat_modifiers[\"str\"]        += val  # val is negative
        elif etype == \"STAT_PENALTY_END\":  stat_modifiers[\"end\"]        += val
        elif etype == \"STAT_PENALTY_AGI\":  stat_modifiers[\"agi\"]        += val
        elif etype == \"STAT_PENALTY_LCK\":  stat_modifiers[\"lck\"]        += val
        elif etype == \"STAT_PENALTY_PER\":  stat_modifiers[\"per\"]        += val
        elif etype == \"STAT_PENALTY_INITIATIVE\": stat_modifiers[\"initiative\"] += val

    # Apply modifiers to player stats — floor at 1 (stats can never go below 1)
    player[\"str_stat\"] = max(1, player[\"str_stat\"] + stat_modifiers[\"str\"])
    player[\"end_stat\"] = max(1, player[\"end_stat\"] + stat_modifiers[\"end\"])
    player[\"agi_stat\"] = max(1, player[\"agi_stat\"] + stat_modifiers[\"agi\"])
    player[\"lck_stat\"] = max(1, player[\"lck_stat\"] + stat_modifiers[\"lck\"])
    player[\"per_stat\"] = max(1, player[\"per_stat\"] + stat_modifiers[\"per\"])
    # Store initiative modifier for the combat engine to read
    player[\"initiative_modifier\"] = stat_modifiers[\"initiative\"]

# Then continue with the rest of get_player() as before (max_hp calc etc.)
# Note: max_hp will now correctly use the modified end_stat.
"""


# =============================================================================
# FILE: combat/engine.py  (patch — apply initiative_modifier in calc_initiative)
# Replace calc_initiative() with this updated version.
# =============================================================================
ENGINE_PATCH = """
# In combat/engine.py, replace calc_initiative() with:

def calc_initiative(combatant: dict, initiative_bonus: int = 0) -> tuple[int, int]:
    \"\"\"Roll initiative: d20 + floor(AGI/2) + initiative_bonus + initiative_modifier.
    initiative_modifier comes from status_effects (STAT_BOOST/PENALTY_INITIATIVE).
    Returns (total, raw_agi) — raw AGI used for tie-breaking.\"\"\"
    raw_roll = roll(20)
    status_init_mod = combatant.get(\"initiative_modifier\", 0)
    total = raw_roll + stat_mod(combatant[\"agi_stat\"]) + initiative_bonus + status_init_mod
    return total, combatant[\"agi_stat\"]
"""


# =============================================================================
# FILE: routes/dashboard.py  (patch — show active stat effects in status block)
# In the dashboard context, pass active effects so the template can show them.
# Add to the index() function after terminal_history is built:
# =============================================================================
DASHBOARD_PATCH = """
# In routes/dashboard.py index(), add before return render_template(...):

    active_effects = execute(
        \"SELECT effect_type, value FROM status_effects WHERE player_id = ?\",
        (player[\"id\"],)
    )
    # Format for display
    effect_labels = []
    label_map = {
        \"STAT_BOOST_STR\": \"+STR\", \"STAT_BOOST_END\": \"+END\",
        \"STAT_BOOST_AGI\": \"+AGI\", \"STAT_BOOST_LCK\": \"+LCK\",
        \"STAT_BOOST_PER\": \"+PER\", \"STAT_BOOST_INITIATIVE\": \"+INIT\",
        \"STAT_PENALTY_STR\": \"-STR\", \"STAT_PENALTY_END\": \"-END\",
        \"STAT_PENALTY_AGI\": \"-AGI\", \"STAT_PENALTY_LCK\": \"-LCK\",
        \"STAT_PENALTY_PER\": \"-PER\", \"STAT_PENALTY_INITIATIVE\": \"-INIT\",
        \"CURSED\": \"CURSED\",
    }
    for e in active_effects:
        lbl = label_map.get(e[\"effect_type\"], e[\"effect_type\"])
        val = int(abs(e[\"value\"]))
        effect_labels.append(f\"{lbl} {val}\")

# Then add effect_labels=effect_labels to the render_template() call.
"""


# =============================================================================
# FILE: templates/base.html  (patch — show active effects in status block)
# In the status block, after the existing cursed/overencumbered warnings, add:
# =============================================================================
TEMPLATE_PATCH = """
<!-- In templates/base.html, inside #status-block, after the existing
     {% if player.is_cursed %} block, add: -->

{% if effect_labels is defined and effect_labels %}
<div class=\"status-effects\" style=\"margin-top:4px;\">
    {% for label in effect_labels %}
    <span class=\"effect-tag
        {% if label.startswith('+') %}effect-good{% else %}effect-bad{% endif %}\">
        {{ label }}
    </span>
    {% endfor %}
</div>
{% endif %}

<!-- And in style.css add: -->
/*
.status-effects { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 4px; }
.effect-tag     { font-size: 10px; padding: 1px 5px; border-radius: 2px; }
.effect-good    { background: #0a2a0a; color: var(--green); border: 1px solid var(--green); }
.effect-bad     { background: #2a0a0a; color: var(--red);   border: 1px solid var(--red); }
*/
"""
