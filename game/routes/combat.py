# routes/combat.py  (Phase 5 — full implementation)
# All in-combat terminal-fragment POST routes.
# Each route loads combat state, resolves the action, checks for combat end,
# and returns an HTML fragment appended to the terminal by terminal.js.

import logging
from datetime import datetime

from flask import Blueprint, render_template, request, session, g
from database import (execute, execute_one, execute_write,
                      exclusive_transaction, get_all_settings)
from queue_handler import enqueue_and_process, register_handler
from combat import actions as combat_actions
from combat import engine, flavour
import config_defaults as cfg

bp = Blueprint("combat", __name__)
logger = logging.getLogger(__name__)


def _error_fragment(message: str) -> str:
    return render_template("fragments/error.html", message=message,
                           player=g.get("player"))


def _get_session_id() -> int | None:
    return session.get("combat_session_id")


# ─────────────────────────────────────────────────────────────────────────────
# POST /combat/action
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/combat/action", methods=["POST"])
def action():
    session_id = _get_session_id()
    if not session_id:
        return _error_fragment("No active combat session.")

    action_type = request.form.get("action_type", "attack").lower()
    player      = g.player

    result = enqueue_and_process(
        player["id"], "combat_action",
        {"session_id": session_id, "action_type": action_type}
    )
    return _render_combat_round(result, session_id, player)


@register_handler("combat_action")
def handle_combat_action(player_id: int, payload: dict) -> dict:
    """Resolve one full combat round:
    1. Roll initiative — determine who acts first
    2. First actor resolves chosen action
    3. Check for combat end
    4. Second actor resolves automated action (or round ends)
    5. Check for combat end again
    6. Apply end-of-round effects (special item durability, expire END_OF_ROUND buffs)
    7. Advance round counter"""
    session_id  = payload["session_id"]
    action_type = payload["action_type"]
    settings    = get_all_settings()

    state = combat_actions.get_combat_state(session_id)
    sess  = state["session"]

    if sess["status"] != "ACTIVE":
        raise ValueError("Combat session is not active.")

    attacker = state["attacker"]
    att_eq   = state["attacker_equipped"]
    att_special = att_eq.get("special")

    # Determine opponent for initiative
    if sess["combat_type"] == "PVP":
        defender = state["defender"]
        def_special = state["defender_equipped"].get("special")
    else:
        defender = state["boss"] or state["minion"]
        def_special = None

    # --- Initiative ---
    att_init_bonus = att_special.get("initiative_bonus", 0) if att_special else 0
    att_init, att_agi = engine.calc_initiative(attacker, att_init_bonus)
    def_init, def_agi = engine.calc_initiative(defender)

    if att_init > def_init:
        attacker_first = True
    elif def_init > att_init:
        attacker_first = False
    else:
        # Tie: higher raw AGI wins; if still tied, reroll
        if att_agi != def_agi:
            attacker_first = att_agi > def_agi
        else:
            while att_init == def_init:
                att_init, _ = engine.calc_initiative(attacker, att_init_bonus)
                def_init, _ = engine.calc_initiative(defender)
            attacker_first = att_init > def_init

    round_log = []
    first_result  = None
    second_result = None
    combat_ended  = False
    winner_side   = None
    result_type   = None

    # --- First actor ---
    if attacker_first:
        first_result = _resolve_player_action(
            session_id, player_id, action_type, state, settings
        )
        round_log.append(first_result)
        ended, winner_side = combat_actions.check_combat_end(state)
        if ended:
            combat_ended = True
            result_type  = "1HP_WIN"
    else:
        first_result = combat_actions.handle_opponent_action(session_id, state)
        round_log.append(first_result)
        ended, winner_side = combat_actions.check_combat_end(state)
        if ended:
            combat_ended = True
            winner_side  = "DEFENDER"  # boss/opponent won by hitting player to 1 HP
            result_type  = "1HP_WIN"

    # --- Second actor (if fight not over) ---
    if not combat_ended:
        # Reload state after first action (HP may have changed)
        state = combat_actions.get_combat_state(session_id)
        if attacker_first:
            second_result = combat_actions.handle_opponent_action(session_id, state)
        else:
            second_result = _resolve_player_action(
                session_id, player_id, action_type, state, settings
            )
        round_log.append(second_result)
        ended, winner_side = combat_actions.check_combat_end(state)
        if ended:
            combat_ended = True
            result_type  = "1HP_WIN"

    # --- End of round effects ---
    if not combat_ended:
        _apply_end_of_round(session_id, state, settings)
        with exclusive_transaction():
            execute_write(
                "UPDATE combat_sessions SET current_round = current_round + 1 WHERE id = ?",
                (session_id,)
            )

    # --- PvP round limit check ---
    reload_sess = execute_one("SELECT * FROM combat_sessions WHERE id = ?", (session_id,))
    pvp_rounds  = settings.get("COMBAT_ROUNDS_DEFAULT", cfg.COMBAT_ROUNDS_DEFAULT)
    rounds_extended = reload_sess["rounds_extended"]
    max_rounds  = pvp_rounds + (rounds_extended * settings.get("COMBAT_ROUNDS_EXTENSION",
                                                                cfg.COMBAT_ROUNDS_EXTENSION))

    at_round_limit = (not combat_ended and
                      sess["combat_type"] == "PVP" and
                      reload_sess["current_round"] > max_rounds)

    # --- Post-combat resolution ---
    final_result = None
    if combat_ended and winner_side:
        state = combat_actions.get_combat_state(session_id)
        final_result = combat_actions.finalize_combat(
            session_id, winner_side, result_type, state
        )
        session.pop("combat_session_id", None)

    return {
        "round_log":       round_log,
        "combat_ended":    combat_ended,
        "at_round_limit":  at_round_limit,
        "winner_side":     winner_side,
        "final_result":    final_result,
        "session_id":      session_id,
        "attacker_first":  attacker_first,
        "att_init":        att_init,
        "def_init":        def_init,
    }


def _resolve_player_action(session_id: int, player_id: int,
                            action_type: str, state: dict,
                            settings: dict) -> dict:
    """Route the player's chosen action to the correct handler."""
    if action_type == "attack":
        return combat_actions.handle_attack(session_id, "ATTACKER", state)
    elif action_type == "brace":
        return combat_actions.handle_brace(session_id, player_id, state)
    elif action_type == "escape":
        return combat_actions.handle_escape(session_id, player_id, state)
    elif action_type == "observe":
        return combat_actions.handle_observe(session_id, player_id, state)
    elif action_type == "swap_gear":
        new_weapon  = request.form.get("new_weapon_id",  type=int)
        new_armor   = request.form.get("new_armor_id",   type=int)
        new_special = request.form.get("new_special_id", type=int)
        return combat_actions.handle_swap_gear(
            session_id, player_id, state, new_weapon, new_armor, new_special
        )
    else:
        raise ValueError(f"Unknown action type: {action_type}")


def _apply_end_of_round(session_id: int, state: dict, settings: dict):
    """Apply end-of-round effects:
    - Special item durability loss (both sides)
    - Expire END_OF_ROUND combat buffs"""
    loss_pct = settings.get("SPECIAL_ITEM_DURABILITY_LOSS_PER_ROUND",
                             cfg.SPECIAL_ITEM_DURABILITY_LOSS_PER_ROUND)
    loss_pts = max(1, int(100 * loss_pct))

    with exclusive_transaction():
        # Attacker special item
        att_special = state["attacker_equipped"].get("special")
        if att_special:
            new_dur = max(0, att_special["current_durability"] - loss_pts)
            execute_write(
                "UPDATE inventory_items SET current_durability = ? WHERE id = ?",
                (new_dur, att_special["inv_id"])
            )
            if new_dur == 0:
                execute_write(
                    "DELETE FROM inventory_items WHERE id = ?", (att_special["inv_id"],)
                )
                execute_write(
                    "UPDATE players SET equipped_special_id = NULL WHERE id = ?",
                    (state["session"]["attacker_player_id"],)
                )

        # Defender special item (PvP only)
        if state["session"]["combat_type"] == "PVP" and state.get("defender_equipped"):
            def_special = state["defender_equipped"].get("special")
            if def_special:
                new_dur = max(0, def_special["current_durability"] - loss_pts)
                execute_write(
                    "UPDATE inventory_items SET current_durability = ? WHERE id = ?",
                    (new_dur, def_special["inv_id"])
                )
                if new_dur == 0:
                    execute_write(
                        "DELETE FROM inventory_items WHERE id = ?", (def_special["inv_id"],)
                    )
                    execute_write(
                        "UPDATE players SET equipped_special_id = NULL WHERE id = ?",
                        (state["session"]["defender_player_id"],)
                    )

        # Expire END_OF_ROUND buffs
        execute_write(
            "DELETE FROM combat_buffs WHERE combat_session_id = ? AND expires_on = 'END_OF_ROUND'",
            (session_id,)
        )


# ─────────────────────────────────────────────────────────────────────────────
# POST /combat/steal  (confirmation step)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/combat/steal", methods=["POST"])
def steal():
    """Return a confirmation fragment showing risk/reward before committing."""
    session_id = _get_session_id()
    if not session_id:
        return _error_fragment("No active combat session.")
    player = g.player
    state  = combat_actions.get_combat_state(session_id)
    opponent = state.get("defender") or state.get("boss") or state.get("minion")
    return render_template("fragments/combat_steal_confirm.html",
                           opponent=opponent,
                           session_id=session_id,
                           player=player)


@bp.route("/combat/steal/confirm", methods=["POST"])
def steal_confirm():
    """Execute the steal action after player confirms."""
    session_id = _get_session_id()
    if not session_id:
        return _error_fragment("No active combat session.")
    player = g.player
    result = enqueue_and_process(
        player["id"], "combat_steal", {"session_id": session_id}
    )
    return _render_combat_round(result, session_id, player)


@register_handler("combat_steal")
def handle_combat_steal(player_id: int, payload: dict) -> dict:
    """Steal resolves as a full combat round (player steals, then opponent acts)."""
    session_id = payload["session_id"]
    state = combat_actions.get_combat_state(session_id)
    sess  = state["session"]

    if sess["status"] != "ACTIVE":
        raise ValueError("Combat session is not active.")

    round_log = []
    # Player steal attempt
    steal_result = combat_actions.handle_steal(session_id, player_id, state)
    round_log.append(steal_result)

    # Check if escape happened (steal on escaped opponent?)
    ended, winner_side = combat_actions.check_combat_end(state)
    final_result = None
    if ended:
        state = combat_actions.get_combat_state(session_id)
        final_result = combat_actions.finalize_combat(session_id, winner_side, "1HP_WIN", state)
        session.pop("combat_session_id", None)
    else:
        # Opponent counter-acts
        state = combat_actions.get_combat_state(session_id)
        opp_result = combat_actions.handle_opponent_action(session_id, state)
        round_log.append(opp_result)
        ended, winner_side = combat_actions.check_combat_end(state)
        if ended:
            state = combat_actions.get_combat_state(session_id)
            final_result = combat_actions.finalize_combat(
                session_id, winner_side, "1HP_WIN", state
            )
            session.pop("combat_session_id", None)
        else:
            _apply_end_of_round(session_id, state, get_all_settings())
            with exclusive_transaction():
                execute_write(
                    "UPDATE combat_sessions SET current_round = current_round + 1 WHERE id = ?",
                    (session_id,)
                )

    return {
        "round_log":      round_log,
        "combat_ended":   ended,
        "at_round_limit": False,
        "winner_side":    winner_side,
        "final_result":   final_result,
        "session_id":     session_id,
        "attacker_first": True,
        "att_init": 0, "def_init": 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /combat/extend  (PvP round extension)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/combat/extend", methods=["POST"])
def extend():
    session_id = _get_session_id()
    if not session_id:
        return _error_fragment("No active combat session.")
    player = g.player
    result = enqueue_and_process(
        player["id"], "combat_extend", {"session_id": session_id}
    )
    if result.get("error"):
        return _error_fragment(result["error"])
    settings = get_all_settings()
    timeout  = settings.get("COMBAT_EXTENSION_TIMEOUT", cfg.COMBAT_EXTENSION_TIMEOUT)
    return render_template("fragments/combat_extend.html",
                           session_id=session_id,
                           timeout=timeout,
                           player=player)


@register_handler("combat_extend")
def handle_combat_extend(player_id: int, payload: dict) -> dict:
    session_id = payload["session_id"]
    settings   = get_all_settings()
    ap_cost    = settings.get("AP_COST_ESCAPE", 1)  # extension costs 1 AP

    player = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))
    if player["current_ap"] < ap_cost:
        return {"error": f"Not enough AP to extend. Need {ap_cost}."}

    sess = execute_one("SELECT * FROM combat_sessions WHERE id = ?", (session_id,))
    if sess["combat_type"] != "PVP":
        return {"error": "Round extension is only available in PvP."}

    with exclusive_transaction():
        execute_write(
            "UPDATE players SET current_ap = current_ap - ? WHERE id = ?",
            (ap_cost, player_id)
        )
        execute_write(
            "UPDATE combat_sessions SET rounds_extended = rounds_extended + 1 WHERE id = ?",
            (session_id,)
        )
    return {"success": True}


# ─────────────────────────────────────────────────────────────────────────────
# POST /combat/resolve  (score formula or auto-triggered by timer)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/combat/resolve", methods=["POST"])
def resolve():
    session_id = _get_session_id()
    if not session_id:
        return _error_fragment("No active combat session.")
    player = g.player
    result = enqueue_and_process(
        player["id"], "combat_resolve", {"session_id": session_id}
    )
    return _render_combat_round(result, session_id, player)


@register_handler("combat_resolve")
def handle_combat_resolve(player_id: int, payload: dict) -> dict:
    """Resolve combat via the PvP score formula."""
    session_id = payload["session_id"]
    state = combat_actions.get_combat_state(session_id)
    sess  = state["session"]

    if sess["status"] != "ACTIVE":
        raise ValueError("Session not active.")
    if sess["combat_type"] != "PVP":
        raise ValueError("Score resolution only applies to PvP.")

    attacker = state["attacker"]
    defender = state["defender"]
    att_max_hp = engine.calc_max_hp(attacker)
    def_max_hp = engine.calc_max_hp(defender)

    att_score, def_score = engine.calc_pvp_score(sess, att_max_hp, def_max_hp)
    winner_side  = "ATTACKER" if att_score > def_score else "DEFENDER"
    final_result = combat_actions.finalize_combat(
        session_id, winner_side, "SCORE_WIN", state
    )
    session.pop("combat_session_id", None)

    return {
        "round_log":      [],
        "combat_ended":   True,
        "at_round_limit": False,
        "winner_side":    winner_side,
        "final_result":   final_result,
        "session_id":     session_id,
        "att_score":      round(att_score, 3),
        "def_score":      round(def_score, 3),
        "attacker_first": True,
        "att_init": 0, "def_init": 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FRAGMENT RENDERER
# ─────────────────────────────────────────────────────────────────────────────

def _render_combat_round(result: dict, session_id: int, player) -> str:
    """Choose which fragment to render based on combat state."""
    if result.get("combat_ended"):
        return render_template("fragments/combat_result.html",
                               result=result, player=player)
    if result.get("at_round_limit"):
        settings = get_all_settings()
        timeout  = settings.get("COMBAT_EXTENSION_TIMEOUT", cfg.COMBAT_EXTENSION_TIMEOUT)
        return render_template("fragments/combat_extend.html",
                               session_id=session_id, timeout=timeout, player=player)
    return render_template("fragments/combat_round.html",
                           result=result, session_id=session_id, player=player)


################################################################################
