"""HTTP and queued handlers for Tavern, boss, minion, PvP, and random events."""
# routes/actions.py  (Phase 5 — full implementation)
# Terminal-fragment POST routes for all AP actions.
# Replaces the Phase 3 stub with full boss/minion/random event logic.

import math
import random
import logging
from datetime import datetime

from flask import Blueprint, render_template, request, session, g
from database import (execute, execute_one, execute_write,
                      exclusive_transaction, get_all_settings, get_player)
from queue_handler import enqueue_and_process, register_handler
from combat import actions as combat_actions
from combat import engine, flavour
import config_defaults as cfg

bp = Blueprint("actions", __name__)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _error_fragment(message: str) -> str:
    """Provide the internal error fragment operation used by this module."""
    return render_template("fragments/error.html", message=message,
                           player=g.get("player"))


def _with_random_event(event: dict | None, player: dict, content: str) -> str:
    """Prepend a triggered event without replacing the requested action."""
    if not event:
        return content
    event_html = render_template("fragments/event_result.html", event=event, player=player)
    return event_html + content


def _check_ap(player: dict, cost: int) -> str | None:
    """Provide the internal check ap operation used by this module."""
    if player["current_ap"] < cost:
        return _error_fragment(f"Not enough AP. Need {cost}, have {player['current_ap']}.")
    return None


def _deduct_ap_and_regen(player_id: int, player: dict, cost: int, settings: dict):
    """Deduct AP cost and apply passive HP regen. Must be inside exclusive_transaction."""
    # AP-triggered healing and its HP cap use the same effective END as combat.
    player = combat_actions.apply_equipped_stat_bonuses(player)
    ap_regen    = settings.get("AP_PASSIVE_HP_REGEN",   cfg.AP_PASSIVE_HP_REGEN)
    end_divisor = settings.get("END_HP_REGEN_DIVISOR",  cfg.END_HP_REGEN_DIVISOR)
    hp_regen    = ap_regen + math.floor(player["end_stat"] / end_divisor)

    if player.get("equipped_special_id"):
        inv = execute_one("SELECT item_id FROM inventory_items WHERE id = ?",
                          (player["equipped_special_id"],))
        if inv:
            s = execute_one("SELECT hp_regen_bonus FROM special_items WHERE id = ?",
                            (inv["item_id"],))
            if s:
                hp_regen += s["hp_regen_bonus"]

    max_hp = 10 + player["end_stat"] + (5 * player["level"])
    new_ap = player["current_ap"] - cost
    new_hp = min(player["current_hp"] + hp_regen, max_hp)
    execute_write(
        "UPDATE players SET current_ap = ?, current_hp = ? WHERE id = ?",
        (new_ap, new_hp, player_id)
    )
    return new_ap, new_hp


# ─────────────────────────────────────────────────────────────────────────────
# RANDOM EVENT CHECK
# ─────────────────────────────────────────────────────────────────────────────

def _describe_random_event_effect(event: dict) -> str:
    """Return a short player-facing description of an event's mechanics."""
    effect = event["effect_type"]
    amount = int(event["effect_amount"])
    stat_names = {
        "STAT_BOOST_STR": "STR", "STAT_BOOST_END": "END",
        "STAT_BOOST_AGI": "AGI", "STAT_BOOST_LCK": "LCK",
        "STAT_BOOST_PER": "PER", "STAT_BOOST_INITIATIVE": "Initiative",
        "STAT_PENALTY_STR": "STR", "STAT_PENALTY_END": "END",
        "STAT_PENALTY_AGI": "AGI", "STAT_PENALTY_LCK": "LCK",
        "STAT_PENALTY_PER": "PER", "STAT_PENALTY_INITIATIVE": "Initiative",
    }
    if effect in stat_names:
        return f"{stat_names[effect]} {amount:+d}"
    if effect == "CREDITS": return f"Credits {amount:+d}"
    if effect == "BONUS_AP": return f"AP +{amount} (up to your AP cap)"
    if effect == "HP_LOSS": return f"HP {amount:+d} (cannot reduce you below 1 HP)"
    if effect == "XP_LOSS": return "No XP lost (legacy event disabled)"
    if effect == "AP_REDUCTION_PERCENT": return f"Daily AP award -{abs(amount)}%"
    if effect == "DURABILITY_RESTORE_RANDOM": return f"Restore up to {abs(amount)} durability on one random item"
    if effect == "DURABILITY_LOSS_RANDOM": return f"One random item's durability {amount:+d}"
    if effect == "ITEM_AT_LEVEL": return "Receive one level-appropriate weapon or armor"
    if effect == "SPECIAL_ITEM_FROM_POOL": return "Receive one available unique special item"
    if effect == "PROTAGONIST_ENCOUNTER": return "Receive a reward from a protagonist encounter"
    return effect.replace("_", " ").title()


def check_random_event(player: dict, settings: dict) -> dict | None:
    """Roll for a random event. Returns event dict if triggered, else None.
    Fires BEFORE AP is deducted. If triggered: apply effect, write feeds."""
    base_chance   = settings.get("RANDOM_EVENT_BASE_CHANCE", cfg.RANDOM_EVENT_BASE_CHANCE)
    max_chance    = settings.get("RANDOM_EVENT_MAX_CHANCE",  cfg.RANDOM_EVENT_MAX_CHANCE)
    good_base     = settings.get("RANDOM_EVENT_GOOD_BASE",   cfg.RANDOM_EVENT_GOOD_BASE)
    good_max      = settings.get("RANDOM_EVENT_GOOD_MAX",    cfg.RANDOM_EVENT_GOOD_MAX)
    bad_min       = settings.get("RANDOM_EVENT_BAD_MIN",     cfg.RANDOM_EVENT_BAD_MIN)
    lck_bonus_per = settings.get("RANDOM_EVENT_LCK_BONUS",   cfg.RANDOM_EVENT_LCK_BONUS)

    lck_steps    = math.floor(player["lck_stat"] / 2)
    # Check for encounter_bonus from equipped special
    encounter_bonus = 0
    if player.get("equipped_special_id"):
        inv = execute_one("SELECT item_id FROM inventory_items WHERE id = ?",
                          (player["equipped_special_id"],))
        if inv:
            s = execute_one("SELECT encounter_bonus FROM special_items WHERE id = ?",
                            (inv["item_id"],))
            if s:
                encounter_bonus = math.floor(s["encounter_bonus"] * 20)  # treat as bonus LCK steps

    effective_lck_steps = lck_steps + encounter_bonus
    trigger_chance = min(base_chance + effective_lck_steps * lck_bonus_per, max_chance)
    if random.random() >= trigger_chance:
        return None

    # Determine good vs bad
    good_chance = min(good_base + effective_lck_steps * lck_bonus_per, good_max)
    bad_chance  = max(1.0 - good_chance, bad_min)
    is_good     = random.random() < good_chance

    # Pull matching events from DB
    events = execute(
        "SELECT * FROM random_events WHERE is_active = 1 AND event_type = ?",
        ("Good" if is_good else "Bad",)
    )
    if not events:
        return None

    # Avoid showing the same event twice in a row to the same player. The
    # previous feed text is enough to identify it without adding schema state.
    last_event = execute_one(
        """SELECT flavor_text FROM daily_feed
           WHERE player_id = ? AND event_category = 'RANDOM_EVENT'
           ORDER BY id DESC LIMIT 1""",
        (player["id"],)
    )
    if last_event and len(events) > 1:
        previous_text = last_event["flavor_text"]
        alternatives = [
            event for event in events
            if not previous_text.startswith(flavour.random_event_flavor(
                event, player.get("character_name", "Player")
            ))
        ]
        if alternatives:
            events = alternatives

    # Weight by rarity (LCK improves chance of Rare/Uncommon in good pool)
    if is_good:
        weights = {"Common": 60, "Uncommon": 30 + effective_lck_steps,
                   "Rare": 10 + effective_lck_steps * 2}
    else:
        weights = {"Common": 60, "Uncommon": 30, "Rare": 10}

    weighted_pool = []
    for e in events:
        w = weights.get(e["rarity"], 30)
        weighted_pool.extend([e] * w)
    if not weighted_pool:
        return None

    event = random.choice(weighted_pool)
    event["effect_summary"] = _describe_random_event_effect(event)
    _apply_random_event(player["id"], player, event, settings)
    return event


def _apply_random_event(player_id: int, player: dict, event: dict, settings: dict):
    """Apply event effect to the player. Writes to DB and daily_feed."""
    effect    = event["effect_type"]
    amount    = event["effect_amount"]
    ap_cap    = settings.get("AP_CARRYOVER_CAP", cfg.AP_CARRYOVER_CAP)
    player_name = player.get("character_name", "Player")

    with exclusive_transaction():
        if effect == "CREDITS":
            if amount >= 0:
                execute_write("UPDATE players SET credits = credits + ? WHERE id = ?",
                              (amount, player_id))
            else:
                execute_write(
                    "UPDATE players SET credits = MAX(0, credits + ?) WHERE id = ?",
                    (amount, player_id)
                )

        elif effect == "BONUS_AP":
            execute_write(
                "UPDATE players SET current_ap = MIN(current_ap + ?, ?) WHERE id = ?",
                (amount, ap_cap, player_id)
            )

        elif effect == "HP_LOSS":
            max_hp = 10 + player["end_stat"] + (5 * player["level"])
            new_hp = max(1, player["current_hp"] + amount)  # amount is negative
            execute_write("UPDATE players SET current_hp = ? WHERE id = ?", (new_hp, player_id))

        elif effect == "XP_LOSS":
            # XP represents permanent progression and may never be reduced.
            # Retain this branch as a safeguard for old/re-imported content.
            pass

        elif effect == "AP_REDUCTION_PERCENT":
            # Cursed: insert status_effect
            execute_write(
                """INSERT INTO status_effects (player_id, effect_type, value)
                   VALUES (?, 'CURSED', ?)""",
                (player_id, abs(amount) / 100)
            )

        elif effect == "ITEM_AT_LEVEL":
            # Random weapon or armor at or above player level
            table = random.choice(["weapons", "armor"])
            item  = execute_one(
                f"SELECT * FROM {table} WHERE level >= ? AND is_active = 1 ORDER BY RANDOM() LIMIT 1",
                (player["level"],)
            )
            if item is None:
                item = execute_one(
                    f"SELECT * FROM {table} WHERE is_active = 1 ORDER BY level DESC LIMIT 1"
                )
            if item:
                item_type = "WEAPON" if table == "weapons" else "ARMOR"
                inv_id = execute_write(
                    """INSERT INTO inventory_items
                       (player_id, item_type, item_id, current_durability, acquired_method)
                       VALUES (?, ?, ?, ?, 'RANDOM_EVENT')""",
                    (player_id, item_type, item["id"], item["starting_durability"])
                )
                execute_write(
                    """INSERT INTO item_history
                       (player_id, item_type, item_id, item_name, event_type)
                       VALUES (?, ?, ?, ?, 'RECEIVED_RANDOM_EVENT')""",
                    (player_id, item_type, item["id"], item["name"])
                )

        elif effect == "DURABILITY_RESTORE_RANDOM":
            # Random item including equipped — use repair formula, no cost
            all_inv = execute(
                "SELECT * FROM inventory_items WHERE player_id = ?", (player_id,)
            )
            if all_inv:
                target = random.choice(all_inv)
                if target["current_durability"] < 100:
                    missing  = 100 - target["current_durability"]
                    base_pct = settings.get("REPAIR_BASE_PERCENT", cfg.REPAIR_BASE_PERCENT)
                    restore  = max(1, int(missing * base_pct))
                    new_dur  = min(100, target["current_durability"] + restore)
                    execute_write(
                        "UPDATE inventory_items SET current_durability = ? WHERE id = ?",
                        (new_dur, target["id"])
                    )

        elif effect == "DURABILITY_LOSS_RANDOM":
            all_inv = execute(
                "SELECT * FROM inventory_items WHERE player_id = ?", (player_id,)
            )
            if all_inv:
                target  = random.choice(all_inv)
                new_dur = max(0, target["current_durability"] + amount)  # amount negative
                if new_dur == 0:
                    execute_write("DELETE FROM inventory_items WHERE id = ?", (target["id"],))
                else:
                    execute_write(
                        "UPDATE inventory_items SET current_durability = ? WHERE id = ?",
                        (new_dur, target["id"])
                    )

        elif effect in (
            "STAT_BOOST_STR", "STAT_BOOST_END", "STAT_BOOST_AGI",
            "STAT_BOOST_LCK", "STAT_BOOST_PER", "STAT_BOOST_INITIATIVE",
            "STAT_PENALTY_STR", "STAT_PENALTY_END", "STAT_PENALTY_AGI",
            "STAT_PENALTY_LCK", "STAT_PENALTY_PER", "STAT_PENALTY_INITIATIVE",
        ):
            execute_write(
                "INSERT INTO status_effects (player_id, effect_type, value) VALUES (?, ?, ?)",
                (player_id, effect, float(amount))
            )

        elif effect == "PROTAGONIST_ENCOUNTER":
            # Applied after this transaction because the handler owns its transaction.
            pass

        elif effect == "SPECIAL_ITEM_FROM_POOL":
            # Rare: give player a random special item from the pool
            available = execute(
                """SELECT si.id FROM special_items si
                   JOIN special_item_registry sir ON sir.special_item_id = si.id
                   WHERE sir.status = 'IN_POOL' AND si.is_active = 1 ORDER BY RANDOM() LIMIT 1"""
            )
            if available:
                special_id = available[0]["id"]
                inv_id = execute_write(
                    """INSERT INTO inventory_items
                       (player_id, item_type, item_id, current_durability, acquired_method)
                       VALUES (?, 'SPECIAL', ?, 100, 'RANDOM_EVENT')""",
                    (player_id, special_id)
                )
                execute_write(
                    """UPDATE special_item_registry
                       SET status='IN_INVENTORY', current_owner_player_id=?,
                           inventory_item_id=?, last_acquired_method='RANDOM_EVENT', updated_at=?
                       WHERE special_item_id=?""",
                    (player_id, inv_id, datetime.utcnow().isoformat(), special_id)
                )

        # Personal feed entry
        feed_text = (f"{flavour.random_event_flavor(event, player_name)}  "
                     f"Effect: {event.get('effect_summary') or _describe_random_event_effect(event)}.")
        execute_write(
            """INSERT INTO daily_feed (feed_scope, player_id, flavor_text, event_category)
               VALUES ('PERSONAL', ?, ?, 'RANDOM_EVENT')""",
            (player_id, feed_text)
        )

    if effect == "PROTAGONIST_ENCOUNTER":
        _handle_protagonist_encounter(player_id, player, settings)


# ─────────────────────────────────────────────────────────────────────────────
# TAVERN  (carried forward from Phase 3 — already complete)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/action/tavern", methods=["POST"])
def action_tavern():
    """Handle the action tavern workflow."""
    player   = combat_actions.apply_equipped_stat_bonuses(g.player)
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
        player["id"], "tavern_heal", {"cost_ap": cost_ap, "cost_cr": cost_cr}
    )
    return render_template("fragments/tavern_result.html", **result, player=player)


@register_handler("tavern_heal")
def handle_tavern_heal(player_id: int, payload: dict) -> dict:
    """Process the queued tavern heal action against validated game state."""
    settings  = get_all_settings()
    cost_ap   = payload["cost_ap"]
    cost_cr   = payload["cost_cr"]
    heal_pct  = settings.get("TAVERN_HEAL_PERCENT", cfg.TAVERN_HEAL_PERCENT)
    player    = combat_actions.apply_equipped_stat_bonuses(get_player(player_id))
    max_hp    = engine.calc_max_hp(player)
    missing   = max_hp - player["current_hp"]
    if missing <= 0:
        raise ValueError("Already at full health.")
    heal_amount = max(1, int(missing * heal_pct))
    with exclusive_transaction():
        new_ap, new_hp_regen = _deduct_ap_and_regen(player_id, player, cost_ap, settings)
        final_hp = min(new_hp_regen + heal_amount, max_hp)
        execute_write(
            "UPDATE players SET current_hp = ?, credits = credits - ? WHERE id = ?",
            (final_hp, cost_cr, player_id)
        )
    return {"heal_amount": heal_amount, "new_hp": final_hp, "max_hp": max_hp,
            "new_ap": new_ap, "max_ap": player["max_ap"],
            "new_credits": player["credits"] - cost_cr, "cost_cr": cost_cr}


# ─────────────────────────────────────────────────────────────────────────────
# BOSS FIGHT
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/action/boss", methods=["POST"])
def action_boss():
    """Handle the action boss workflow."""
    player   = g.player
    settings = get_all_settings()
    cost_ap  = settings.get("AP_COST_BOSS", cfg.AP_COST_BOSS)

    if player["in_combat"]:
        return _error_fragment("You are already in combat.")
    if g.get("blackout"):
        return _error_fragment("Combat unavailable — midnight reset approaching.")
    if err := _check_ap(player, cost_ap):
        return err

    # Random event check (fires before AP deducted)
    event = check_random_event(player, settings)
    if event:
        player = get_player(player["id"]) or player

    # A minion can interrupt the attempted boss hunt; otherwise find a boss.
    minion_chance = settings.get("MINION_ENCOUNTER_CHANCE", cfg.MINION_ENCOUNTER_CHANCE)
    encounter_type = "MINION" if random.random() < minion_chance else "BOSS"

    # Determine which boss/minion
    existing_instances = execute(
        f"SELECT * FROM {'boss' if encounter_type == 'BOSS' else 'minion'}_instances "
        f"WHERE player_id = ? ORDER BY discovered_at DESC",
        (player["id"],)
    )
    discovered_ids = [i[f"{'boss' if encounter_type == 'BOSS' else 'minion'}_id"]
                      for i in existing_instances]

    # Get a random undiscovered one, or random from all if all discovered
    tbl = "bosses" if encounter_type == "BOSS" else "minions"
    if discovered_ids:
        undiscovered = execute(
            f"SELECT * FROM {tbl} WHERE is_active = 1 AND id NOT IN ({','.join('?' * len(discovered_ids))}) ORDER BY RANDOM() LIMIT 1",
            tuple(discovered_ids)
        )
        opponent = undiscovered[0] if undiscovered else random.choice(
            execute(f"SELECT * FROM {tbl} WHERE is_active = 1")
        )
    else:
        result = execute(f"SELECT * FROM {tbl} WHERE is_active = 1 ORDER BY RANDOM() LIMIT 1")
        if not result:
            return _with_random_event(
                event, player,
                _error_fragment("No content available yet. Ask the admin to import game content.")
            )
        opponent = result[0]

    # Level warning check
    warn_threshold = settings.get("BOSS_LEVEL_WARNING_THRESHOLD", cfg.BOSS_LEVEL_WARNING_THRESHOLD)
    level_diff     = opponent["level"] - player["level"]
    if level_diff >= warn_threshold:
        content = render_template("fragments/boss_confirm.html",
                                  opponent=opponent,
                                  encounter_type=encounter_type,
                                  level_diff=level_diff,
                                  player=player)
        return _with_random_event(event, player, content)

    # Minion: PER check
    if encounter_type == "MINION":
        per_result = _minion_per_check(player, opponent)
        if per_result["spotted"]:
            content = render_template("fragments/minion_spotted.html",
                                      minion=opponent,
                                      per_result=per_result,
                                      player=player)
            return _with_random_event(event, player, content)

    # Start the fight
    content = _start_boss_fight(player, opponent, encounter_type, cost_ap, settings)
    return _with_random_event(event, player, content)


@bp.route("/action/boss/confirm", methods=["POST"])
def action_boss_confirm():
    """Player confirmed they want to fight despite level warning or spotted minion."""
    player       = g.player
    settings     = get_all_settings()
    cost_ap      = settings.get("AP_COST_BOSS",   cfg.AP_COST_BOSS)
    opponent_id  = request.form.get("opponent_id", type=int)
    encounter_type = request.form.get("encounter_type", "BOSS")
    action       = request.form.get("action", "fight")  # fight or avoid

    if action == "avoid":
        # AP refunded — just return a message
        return render_template("fragments/event_result.html",
                               event={"flavor_text": "You slip past undetected.",
                                      "event_type": "Good"},
                               player=player)

    tbl = "bosses" if encounter_type == "BOSS" else "minions"
    opponent = execute_one(f"SELECT * FROM {tbl} WHERE id = ?", (opponent_id,))
    if not opponent:
        return _error_fragment("Opponent not found.")

    return _start_boss_fight(player, opponent, encounter_type, cost_ap, settings)


def _minion_per_check(player: dict, minion: dict) -> dict:
    """Provide the internal minion per check operation used by this module."""
    from combat.engine import resolve_opposed_roll
    result = resolve_opposed_roll(
        actor_agi=player["agi_stat"], actor_lck=player["lck_stat"],
        defender_agi=minion["agi_stat"], defender_lck=minion["lck_stat"],
        actor_per=player["per_stat"], defender_per=minion.get("per_stat", 0),
        tie_goes_to="defender"
    )
    return {"spotted": result["success"], "detail": result["detail"]}


def _start_boss_fight(player: dict, opponent: dict, encounter_type: str,
                      cost_ap: int, settings: dict):
    """Initiate a boss or minion fight. Deducts AP, sets in_combat, creates session."""
    result = enqueue_and_process(
        player["id"], "start_boss_fight",
        {"opponent_id": opponent["id"], "encounter_type": encounter_type, "cost_ap": cost_ap}
    )
    if result.get("error"):
        return _error_fragment(result["error"])

    session["combat_session_id"] = result["session_id"]

    # Starting combat spends AP and may passively heal the player.  Reload the
    # committed values so the opening panel never displays the pre-action state.
    player = get_player(player["id"]) or player
    player = combat_actions.apply_equipped_stat_bonuses(player)

    opponent_full = execute_one(
        f"SELECT * FROM {'bosses' if encounter_type == 'BOSS' else 'minions'} WHERE id = ?",
        (opponent["id"],)
    )
    # Show boss intel if previously observed
    intel = None
    intel_detail = None
    if encounter_type == "BOSS":
        intel = execute_one(
            "SELECT * FROM boss_intel WHERE player_id = ? AND boss_id = ?",
            (player["id"], opponent["id"])
        )
        if intel:
            damage_types = ("blade", "blunt", "ballistic", "energy", "arcane", "explosive", "venom")
            intel_detail = {
                "resistances": [t.upper() for t in damage_types if opponent_full.get(f"res_{t}")],
                "weaknesses": [t.upper() for t in damage_types if opponent_full.get(f"weak_{t}")],
                "special_attack_name": opponent_full.get("special_attack_name"),
                "special_attack_type": opponent_full.get("special_attack_damage_type"),
                "special_buff_name": opponent_full.get("special_buff_name"),
                "special_buff_type": opponent_full.get("special_buff_type"),
                "current_hp": opponent_full.get("current_hp"),
                "max_hp": opponent_full.get("max_hp"),
            }

    return render_template("fragments/combat_open.html",
                           opponent=opponent_full,
                           encounter_type=encounter_type,
                           session_id=result["session_id"],
                           intel=intel,
                           intel_detail=intel_detail,
                           player=player,
                           opponent_health=flavour.hp_status(
                               opponent_full.get("current_hp", opponent_full["max_hp"]),
                               opponent_full["max_hp"]),
                           boss_flavor=opponent_full.get("flavor_text", ""))


@register_handler("start_boss_fight")
def handle_start_boss_fight(player_id: int, payload: dict) -> dict:
    """Process the queued start boss fight action against validated game state."""
    opponent_id    = payload["opponent_id"]
    encounter_type = payload["encounter_type"]
    cost_ap        = payload["cost_ap"]

    player   = get_player(player_id)
    settings = get_all_settings()

    if player["in_combat"]:
        return {"error": "Already in combat."}
    if player["current_ap"] < cost_ap:
        return {"error": "Not enough AP."}

    tbl = "bosses" if encounter_type == "BOSS" else "minions"
    opponent = execute_one(f"SELECT * FROM {tbl} WHERE id = ?", (opponent_id,))
    if not opponent:
        return {"error": "Opponent not found."}

    with exclusive_transaction():
        new_ap, new_hp = _deduct_ap_and_regen(player_id, player, cost_ap, settings)
        execute_write("UPDATE players SET in_combat = 1 WHERE id = ?", (player_id,))

        # Get or create boss/minion instance
        inst_tbl  = f"{'boss' if encounter_type == 'BOSS' else 'minion'}_instances"
        id_col    = f"{'boss' if encounter_type == 'BOSS' else 'minion'}_id"
        existing  = execute_one(
            f"SELECT * FROM {inst_tbl} WHERE player_id = ? AND {id_col} = ?",
            (player_id, opponent_id)
        )
        if existing:
            # Reset for new fight
            execute_write(
                f"UPDATE {inst_tbl} SET current_hp = ?, special_attack_used = 0, "
                f"special_buff_used = 0, current_phase = 1 WHERE id = ?",
                (opponent["max_hp"], existing["id"])
            )
            inst_id = existing["id"]
        else:
            inst_id = execute_write(
                f"INSERT INTO {inst_tbl} (player_id, {id_col}, current_hp) VALUES (?, ?, ?)",
                (player_id, opponent_id, opponent["max_hp"])
            )

        # Create combat session
        if encounter_type == "BOSS":
            session_id = execute_write(
                """INSERT INTO combat_sessions
                   (combat_type, attacker_player_id, boss_instance_id, status,
                    attacker_hp_start)
                   VALUES ('BOSS', ?, ?, 'ACTIVE', ?)""",
                (player_id, inst_id, new_hp)
            )
        else:
            session_id = execute_write(
                """INSERT INTO combat_sessions
                   (combat_type, attacker_player_id, minion_instance_id, status,
                    attacker_hp_start)
                   VALUES ('MINION', ?, ?, 'ACTIVE', ?)""",
                (player_id, inst_id, new_hp)
            )

    return {"session_id": session_id, "new_ap": new_ap, "new_hp": new_hp}


# ─────────────────────────────────────────────────────────────────────────────
# PVP
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/action/pvp", methods=["POST"])
def action_pvp():
    """Handle the action pvp workflow."""
    player   = g.player
    settings = get_all_settings()
    cost_ap  = settings.get("AP_COST_PVP", cfg.AP_COST_PVP)

    if player["in_combat"]:
        return _error_fragment("You are already in combat.")
    if g.get("blackout"):
        return _error_fragment("Combat unavailable — midnight reset approaching.")
    if err := _check_ap(player, cost_ap):
        return err

    # Random event check
    event = check_random_event(player, settings)
    if event:
        player = get_player(player["id"]) or player

    # Roaming minions can interrupt the PvP search before a target is chosen.
    minion_chance = settings.get("MINION_ENCOUNTER_CHANCE", cfg.MINION_ENCOUNTER_CHANCE)
    if random.random() < minion_chance:
        minion = _choose_minion_for_player(player)
        if minion:
            minion_cost = settings.get("AP_COST_BOSS", cfg.AP_COST_BOSS)
            if player["current_ap"] < minion_cost:
                return _with_random_event(
                    event, player, _error_fragment("A minion interrupts you, but you lack the AP to engage.")
                )
            per_result = _minion_per_check(player, minion)
            if per_result["spotted"]:
                content = render_template("fragments/minion_spotted.html",
                                          minion=minion, per_result=per_result, player=player)
            else:
                content = _start_boss_fight(player, minion, "MINION", minion_cost, settings)
            return _with_random_event(event, player, content)

    # Build eligible opponent list
    opponents = _get_eligible_opponents(player, settings)
    content = render_template("fragments/opponent_list.html",
                              opponents=opponents, player=player)
    return _with_random_event(event, player, content)


def _choose_minion_for_player(player: dict) -> dict | None:
    """Select an undiscovered active minion first, then any active minion."""
    discovered = execute(
        "SELECT minion_id FROM minion_instances WHERE player_id=?", (player["id"],)
    )
    discovered_ids = [row["minion_id"] for row in discovered]
    if discovered_ids:
        placeholders = ",".join("?" for _ in discovered_ids)
        minion = execute_one(
            f"SELECT * FROM minions WHERE is_active=1 AND id NOT IN ({placeholders}) "
            "ORDER BY RANDOM() LIMIT 1", tuple(discovered_ids)
        )
        if minion:
            return minion
    return execute_one("SELECT * FROM minions WHERE is_active=1 ORDER BY RANDOM() LIMIT 1")


def _get_eligible_opponents(player: dict, settings: dict) -> list[dict]:
    """Return list of PvP-eligible opponents with HP tier and wealth tier."""
    all_players = execute(
        """SELECT p.*, ps.pvp_kills FROM players p
           LEFT JOIN player_stats ps ON ps.player_id = p.id
           WHERE p.id != ? AND p.is_banned = 0""",
        (player["id"],)
    )
    # Filter eligibility
    eligible = []
    for p in all_players:
        if p["level"] < 3:
            continue  # Level 1-2 protected
        if p["current_hp"] <= 1:
            continue
        level_diff = player["level"] - p["level"]
        if level_diff > 2:
            continue  # Can't attack more than 2 levels below
        if p["level"] < player["level"] - 2:
            continue
        max_hp = 10 + p["end_stat"] + (5 * p["level"])
        hp_pct = p["current_hp"] / max_hp * 100 if max_hp else 0
        if hp_pct >= 76:   hp_tier = "Healthy"
        elif hp_pct >= 51: hp_tier = "Wounded"
        elif hp_pct >= 26: hp_tier = "Hurt"
        else:              hp_tier = "Critical"
        eligible.append({**p, "hp_tier": hp_tier, "max_hp": max_hp})

    # Calculate wealth tiers based on credit percentile
    if eligible:
        sorted_by_credits = sorted(eligible, key=lambda x: x["credits"])
        n = len(sorted_by_credits)
        for i, p in enumerate(sorted_by_credits):
            percentile = i / n
            poor_max   = settings.get("WEALTH_TIER_POOR_MAX",   cfg.WEALTH_TIER_POOR_MAX)
            middle_max = settings.get("WEALTH_TIER_MIDDLE_MAX", cfg.WEALTH_TIER_MIDDLE_MAX)
            if percentile <= poor_max:
                p["wealth_tier"] = "Poor"
            elif percentile <= middle_max:
                p["wealth_tier"] = "Middle"
            else:
                p["wealth_tier"] = "Rich"

    return eligible


@bp.route("/action/pvp/fight", methods=["POST"])
def action_pvp_fight():
    """Handle the action pvp fight workflow."""
    player     = g.player
    settings   = get_all_settings()
    cost_ap    = settings.get("AP_COST_PVP", cfg.AP_COST_PVP)
    target_id  = request.form.get("target_id", type=int)

    if not target_id:
        return _error_fragment("No opponent selected.")

    # Re-validate server-side
    target = execute_one("SELECT * FROM players WHERE id = ?", (target_id,))
    if target is None:
        return _error_fragment("Opponent not found.")
    if target["level"] < 3:
        return _error_fragment("That player cannot be attacked.")
    if target["current_hp"] <= 1:
        return _error_fragment("That player is at 1 HP and cannot be attacked.")
    if target["in_combat"]:
        return _error_fragment("That player is already in combat.")
    level_diff = player["level"] - target["level"]
    if level_diff > 2:
        return _error_fragment("That player is too far below your level.")

    result = enqueue_and_process(
        player["id"], "start_pvp_fight",
        {"target_id": target_id, "cost_ap": cost_ap}
    )
    if result.get("error"):
        return _error_fragment(result["error"])

    session["combat_session_id"] = result["session_id"]

    # Show the AP/HP values committed by start_pvp_fight, including equipment
    # stat bonuses used by the combat engine.
    player = get_player(player["id"]) or player
    player = combat_actions.apply_equipped_stat_bonuses(player)
    target = get_player(target["id"]) or target
    target = combat_actions.apply_equipped_stat_bonuses(target)

    return render_template("fragments/combat_open.html",
                           opponent=target,
                           encounter_type="PVP",
                           session_id=result["session_id"],
                           intel=None,
                           opponent_health=flavour.hp_status(
                               target["current_hp"], engine.calc_max_hp(target)),
                           player=player,
                           boss_flavor="")


@register_handler("start_pvp_fight")
def handle_start_pvp_fight(player_id: int, payload: dict) -> dict:
    """Process the queued start pvp fight action against validated game state."""
    target_id = payload["target_id"]
    cost_ap   = payload["cost_ap"]
    settings  = get_all_settings()

    player  = get_player(player_id)
    target  = combat_actions.apply_equipped_stat_bonuses(get_player(target_id))

    if player["in_combat"] or target["in_combat"]:
        return {"error": "A player is already in combat."}
    if player["current_ap"] < cost_ap:
        return {"error": "Not enough AP."}

    with exclusive_transaction():
        new_ap, new_hp = _deduct_ap_and_regen(player_id, player, cost_ap, settings)
        execute_write("UPDATE players SET in_combat = 1 WHERE id = ?", (player_id,))
        execute_write("UPDATE players SET in_combat = 1 WHERE id = ?", (target_id,))
        target_max_hp = 10 + target["end_stat"] + (5 * target["level"])
        session_id = execute_write(
            """INSERT INTO combat_sessions
               (combat_type, attacker_player_id, defender_player_id, status,
                attacker_hp_start, defender_hp_start)
               VALUES ('PVP', ?, ?, 'ACTIVE', ?, ?)""",
            (player_id, target_id, new_hp, target["current_hp"])
        )

    return {"session_id": session_id, "new_ap": new_ap, "new_hp": new_hp}


################################################################################


def _handle_protagonist_encounter(player_id: int, player: dict, settings: dict):
    """Find a level-appropriate protagonist, roll 40/40/20 for weapon/armor/special,
    award the item, write feed entry. If item already taken, fall back to credits."""
    from database import execute, execute_one, execute_write, exclusive_transaction
    from datetime import datetime
    import random, math

    # Find all movies with a protagonist defined, ordered by how close
    # their boss level is to the player's current level
    movies = execute(
        """SELECT m.id, m.movie_name,
                  m.protagonist_name,
                  m.protagonist_weapon_id,
                  m.protagonist_armor_id,
                  m.protagonist_special_item_id,
                  b.level as boss_level
           FROM master m
           JOIN bosses b ON b.id = m.boss_id
           WHERE m.protagonist_name IS NOT NULL
             AND m.is_active = 1
           ORDER BY ABS(b.level - ?) ASC""",
        (player["level"],)
    )

    if not movies:
        # Fallback: award credits
        with exclusive_transaction():
            execute_write(
            "UPDATE players SET credits = credits + 50 WHERE id = ?", (player_id,)
            )
            execute_write(
            """INSERT INTO daily_feed (feed_scope, player_id, flavor_text, event_category)
               VALUES ('PERSONAL', ?, ?, 'RANDOM_EVENT')""",
            (player_id,
             "A familiar figure passes in the crowd — but vanishes before you can speak. +50 credits left behind.")
            )
        return

    # Pick from the 3 closest level matches (weighted toward closest)
    candidates = movies[:3]
    weights    = [3, 2, 1][:len(candidates)]
    movie      = random.choices(candidates, weights=weights, k=1)[0]

    protagonist = movie["protagonist_name"]
    roll        = random.random()

    if roll < 0.40:
        # Weapon
        item_type = "WEAPON"
        item_id   = movie["protagonist_weapon_id"]
        table     = "weapons"
    elif roll < 0.80:
        # Armor
        item_type = "ARMOR"
        item_id   = movie["protagonist_armor_id"]
        table     = "armor"
    else:
        # Special — check registry first
        item_type = "SPECIAL"
        item_id   = movie["protagonist_special_item_id"]
        table     = "special_items"

    if not item_id:
        # Protagonist item not defined — fallback credits
        with exclusive_transaction():
            execute_write(
                "UPDATE players SET credits = credits + 50 WHERE id = ?", (player_id,)
            )
        return

    # For specials: check if already in world
    if item_type == "SPECIAL":
        reg = execute_one(
            "SELECT status FROM special_item_registry WHERE special_item_id = ?",
            (item_id,)
        )
        if reg and reg["status"] != "IN_POOL":
            # Already taken — fall back to weapon instead
            item_type = "WEAPON"
            item_id   = movie["protagonist_weapon_id"]
            table     = "weapons"

    # Get item detail for name
    item_detail = execute_one(f"SELECT name, starting_durability FROM {table} WHERE id = ?", (item_id,))
    if not item_detail:
        return

    item_name = item_detail["name"]
    durability = item_detail.get("starting_durability", 100) or 100

    with exclusive_transaction():
        inv_id = execute_write(
            """INSERT INTO inventory_items
               (player_id, item_type, item_id, current_durability, acquired_method)
               VALUES (?, ?, ?, ?, 'RANDOM_EVENT')""",
            (player_id, item_type, item_id, durability)
        )
        execute_write(
            """INSERT INTO item_history
               (player_id, item_type, item_id, item_name, event_type)
               VALUES (?, ?, ?, ?, 'RECEIVED_RANDOM_EVENT')""",
            (player_id, item_type, item_id, item_name)
        )
        if item_type == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry
                   SET status = 'IN_INVENTORY', current_owner_player_id = ?,
                       inventory_item_id = ?, last_acquired_method = 'RANDOM_EVENT',
                       updated_at = ?
                   WHERE special_item_id = ?""",
                (player_id, inv_id, datetime.utcnow().isoformat(), item_id)
            )
        # Personal feed entry
        execute_write(
            """INSERT INTO daily_feed (feed_scope, player_id, flavor_text, event_category)
               VALUES ('PERSONAL', ?, ?, 'RANDOM_EVENT')""",
            (player_id,
             f"{protagonist} looks you over and hands you the {item_name}. No words. Just a nod.")
        )
        # Global feed for special items
        if item_type == "SPECIAL":
            execute_write(
                """INSERT INTO daily_feed (feed_scope, player_id, flavor_text, event_category)
                   VALUES ('GLOBAL', NULL, ?, 'ITEM')""",
                (f"The {item_name} has entered the world.",)
            )
