################################################################################
# PHASE 13 CODE — Boss Phase Behavior
# BBS-Inspired Multiplayer Dueling Game
#
# File changed: combat/actions.py
#
# What was missing:
#   current_phase was stored in boss_instances and reset on fight end,
#   but never checked or updated during combat. All bosses fought identically
#   regardless of HP — no escalation, no phase transitions.
#
# What this adds:
#   _boss_action() — now checks HP% against phase thresholds each round:
#       Phase 1 (full HP to phase2_hp_percent):
#           33/33/33 split — attack / special_attack / special_buff
#       Phase 2 (phase2_hp_percent to phase3_hp_percent):
#           Specials used first if available, then pure attack
#           +2 bonus to all attack rolls
#           Feed entry fires on phase entry
#       Phase 3 (below phase3_hp_percent):
#           Special move cooldowns reset — can use again
#           +4 bonus to all attack rolls
#           Boss attacks TWICE per round (extra attack via _boss_regular_attack)
#           Feed entry fires on phase entry
#
#   _boss_regular_attack() — extracted from _boss_action() into its own
#       helper so it can be called twice in phase 3 cleanly.
#
#   Phase attack bonuses are injected as END_OF_ROUND combat_buffs so they
#   go through the existing buff resolution system in engine.resolve_full_attack().
#
# No schema changes required.
################################################################################

# =============================================================================
# PHASE 13 — Boss Phase Behavior
# =============================================================================
# File changed: combat/actions.py
#
# Two functions need patching:
#   1. _boss_action()        — check/update phase before choosing action
#   2. handle_combat_action() in routes/combat.py — boss phase 3 extra attack
#
# Phase thresholds are stored as percentages on the bosses table:
#   phase2_hp_percent  (default 50) — below this % HP, enter phase 2
#   phase3_hp_percent  (default 25) — below this % HP, enter phase 3
#
# Phase behaviors:
#   Phase 1: 33/33/33 attack / special_attack / special_buff
#   Phase 2: specials used first if available, then pure attack
#             +2 bonus to all attack rolls
#             On entering phase 2: write a dramatic flavor line to feed
#   Phase 3: specials cooldown resets (can use again)
#             +4 bonus to all attack rolls
#             Boss attacks TWICE per round (extra attack)
#             On entering phase 3: write a dramatic flavor line to feed
# =============================================================================


BOSS_ACTION_REPLACEMENT = '''
# In combat/actions.py, replace the entire _boss_action() function with:

def _boss_action(session_id: int, state: dict) -> dict:
    """Boss chooses and executes its action for this round.
    Checks phase thresholds first, updates phase if needed,
    then scales behavior to current phase."""
    boss    = state["boss"]
    session = state["session"]

    # ── Phase check ───────────────────────────────────────────────────────────
    max_hp        = boss["max_hp"]
    current_hp    = boss["current_hp"]
    hp_pct        = (current_hp / max_hp * 100) if max_hp else 100
    phase2_thresh = boss.get("phase2_hp_percent", 50)
    phase3_thresh = boss.get("phase3_hp_percent", 25)
    current_phase = boss.get("current_phase", 1)

    new_phase = current_phase
    if hp_pct <= phase3_thresh:
        new_phase = 3
    elif hp_pct <= phase2_thresh:
        new_phase = 2

    # Persist phase change and handle transition effects
    if new_phase != current_phase:
        with exclusive_transaction():
            # On entering phase 3: reset special move flags (can use again)
            if new_phase == 3:
                execute_write(
                    """UPDATE boss_instances
                       SET current_phase = 3,
                           special_attack_used = 0,
                           special_buff_used = 0
                       WHERE id = ?""",
                    (boss["instance_id"],)
                )
                flavor_text = (
                    f"{boss['name'].upper()} ENTERS PHASE 3 — "
                    f"desperate, enraged, and more dangerous than ever!"
                )
            else:
                execute_write(
                    "UPDATE boss_instances SET current_phase = ? WHERE id = ?",
                    (new_phase, boss["instance_id"])
                )
                flavor_text = (
                    f"{boss['name'].upper()} ENTERS PHASE 2 — "
                    f"wounded and furious, its attacks grow more deliberate."
                )
            # Personal feed entry for the phase transition
            execute_write(
                """INSERT INTO daily_feed
                   (feed_scope, player_id, flavor_text, event_category)
                   VALUES ('PERSONAL', ?, ?, 'COMBAT')""",
                (session["attacker_player_id"], flavor_text)
            )
        # Refresh boss state after update
        boss["current_phase"]       = new_phase
        boss["special_attack_used"] = 0 if new_phase == 3 else boss["special_attack_used"]
        boss["special_buff_used"]   = 0 if new_phase == 3 else boss["special_buff_used"]
        current_phase = new_phase

    # ── Choose action based on phase ──────────────────────────────────────────
    s_atk_used = boss["special_attack_used"]
    s_buf_used = boss["special_buff_used"]

    if current_phase == 1:
        # Phase 1: 33/33/33 split
        r = random.random()
        if   r < 0.333 and not s_atk_used: chosen = "SPECIAL_ATTACK"
        elif r < 0.666 and not s_buf_used:  chosen = "SPECIAL_BUFF"
        else:                                chosen = "ATTACK"

    elif current_phase == 2:
        # Phase 2: specials first if available, else attack
        if not s_atk_used and not s_buf_used:
            chosen = "SPECIAL_ATTACK" if random.random() < 0.5 else "SPECIAL_BUFF"
        elif not s_atk_used:
            chosen = "SPECIAL_ATTACK"
        elif not s_buf_used:
            chosen = "SPECIAL_BUFF"
        else:
            chosen = "ATTACK"

    else:
        # Phase 3: specials reset — same as phase 2 but with extra attack
        # (extra attack handled in combat round handler, see routes/combat.py patch)
        if not s_atk_used and not s_buf_used:
            chosen = "SPECIAL_ATTACK" if random.random() < 0.5 else "SPECIAL_BUFF"
        elif not s_atk_used:
            chosen = "SPECIAL_ATTACK"
        elif not s_buf_used:
            chosen = "SPECIAL_BUFF"
        else:
            chosen = "ATTACK"

    # ── Execute chosen action ─────────────────────────────────────────────────
    if chosen == "SPECIAL_ATTACK" and not s_atk_used:
        primary = _boss_special_attack(session_id, state)
    elif chosen == "SPECIAL_BUFF" and not s_buf_used:
        primary = _boss_special_buff(session_id, state)
    else:
        primary = _boss_regular_attack(session_id, state, current_phase)

    primary["boss_phase"] = current_phase
    primary["phase_changed"] = new_phase != (boss.get("current_phase", 1) if new_phase == current_phase else current_phase - 1)

    # Phase 3 extra attack — always attacks again after any action
    if current_phase == 3:
        # Reload state (HP may have changed)
        state2 = get_combat_state(session_id)
        if state2["session"]["status"] == "ACTIVE":
            extra = _boss_regular_attack(session_id, state2, current_phase)
            extra["is_extra_attack"] = True
            primary["extra_attack_result"] = extra

    return primary


def _boss_regular_attack(session_id: int, state: dict, phase: int) -> dict:
    """Execute a regular boss attack, with phase-based attack bonuses.
    Phase 2: +2 to attack roll. Phase 3: +4 to attack roll."""
    boss    = state["boss"]
    session = state["session"]

    # Phase attack bonus
    phase_attack_bonus = {1: 0, 2: 2, 3: 4}.get(phase, 0)

    # Inject phase bonus as a temporary combat buff for this round
    if phase_attack_bonus > 0:
        with exclusive_transaction():
            execute_write(
                """INSERT INTO combat_buffs
                   (combat_session_id, side, buff_type, value, expires_on)
                   VALUES (?, \'DEFENDER\', \'BOSS_ATTACK_BONUS\', ?, \'END_OF_ROUND\')""",
                (session_id, phase_attack_bonus)
            )
        # Reload state to pick up the new buff
        state = get_combat_state(session_id)
        boss  = state["boss"]

    boss_as_attacker = {**boss}
    boss_weapon      = _get_boss_weapon(boss)
    attacker_player  = state["attacker"]
    att_armor        = state["attacker_equipped"].get("armor")
    att_special      = state["attacker_equipped"].get("special")
    att_buffs        = state["attacker_buffs"]
    brace_dodge      = sum(
        int(b["value"]) for b in att_buffs if b["buff_type"] == "BRACE_DODGE_BONUS"
    )

    result = engine.resolve_full_attack(
        attacker=boss_as_attacker,
        defender=attacker_player,
        attacker_weapon=boss_weapon,
        attacker_special=None,
        defender_armor=att_armor,
        defender_special=att_special,
        boss=None,
        brace_dodge_bonus=brace_dodge,
        active_buffs=att_buffs,
        is_player_attacker=False,
    )

    with exclusive_transaction():
        if result["hit"]:
            new_hp = max(1, attacker_player["current_hp"] - result["damage_total"])
            execute_write(
                "UPDATE players SET current_hp = ? WHERE id = ?",
                (new_hp, session["attacker_player_id"])
            )
            execute_write(
                """UPDATE combat_sessions
                   SET defender_total_damage_dealt = defender_total_damage_dealt + ?
                   WHERE id = ?""",
                (result["damage_total"], session_id)
            )
            if att_armor:
                _apply_durability_loss(att_armor["inv_id"], 1,
                                       session["attacker_player_id"])
            execute_write(
                """DELETE FROM combat_buffs
                   WHERE combat_session_id = ? AND side = \'ATTACKER\'
                   AND expires_on = \'NEXT_HIT_RESOLVED\'""",
                (session_id,)
            )
        _write_combat_log(session_id, session["current_round"], "DEFENDER",
                          "ATTACK", result["roll_detail"], result["outcome_detail"])

    flv = flavour.attack_flavor(
        attacker_name=boss["name"],
        weapon_name=boss_weapon.get("name", "attack"),
        weapon_type=boss_weapon.get("weapon_type", "Melee"),
        hit=result["hit"], dodged=result["dodged"],
        is_crit=result["is_crit"],
        damage=result["damage_total"],
        damage_type=boss_weapon.get("damage_type", "Blunt"),
    )
    return {
        "action": "ATTACK",
        "hit": result["hit"],
        "dodged": result["dodged"],
        "damage_total": result["damage_total"],
        "roll_detail": result["roll_detail"],
        "flavor": flv,
    }
'''


# =============================================================================
# TEMPLATE PATCH — combat_round.html
# Show phase transition message and extra attack result
# =============================================================================

TEMPLATE_PATCH = """
<!-- In templates/fragments/combat_round.html, inside the round_log loop,
     add after the existing action_result div: -->

{% if action_result.boss_phase is defined and action_result.phase_changed %}
<div class="term-line term-amber">
    ⚠ {{ action_result.flavor if 'PHASE' in action_result.flavor else '' }}
</div>
{% endif %}

{% if action_result.extra_attack_result is defined %}
<div class="term-line term-bad">
    ★ PHASE 3 EXTRA ATTACK: {{ action_result.extra_attack_result.flavor }}
</div>
{% endif %}

<!-- Also add a phase indicator to combat_open.html status line:
     (shown on fight start if boss already damaged from a previous session) -->
{% if boss_phase is defined and boss_phase > 1 %}
<div class="term-line term-amber">
    ⚠ This boss is in Phase {{ boss_phase }} — expect increased aggression.
</div>
{% endif %}
"""


# =============================================================================
# SUMMARY OF CHANGES
# =============================================================================

SUMMARY = """
Changes to apply:

1. combat/actions.py:
   - Replace _boss_action() with new version (above)
   - Add _boss_regular_attack() as a new helper function
   - Remove the old inline regular attack block from _boss_action()
     (it is now in _boss_regular_attack())

2. templates/fragments/combat_round.html:
   - Add phase transition message display
   - Add extra attack result display for phase 3

No schema changes required.
No new DB tables required.
The current_phase column on boss_instances already tracks this.
The special_attack_used / special_buff_used reset on phase 3 entry
is handled within _boss_action() itself.

Phase transition flavor lines write to PERSONAL daily_feed so they
appear in the player's terminal history even if they miss the live update.
"""
