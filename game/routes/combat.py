"""Combat request routes that execute complete player/opponent rounds."""
# HTTP and queued-action orchestration for every supported combat type.
# All in-combat terminal-fragment POST routes.
# Each route loads combat state, resolves the action, checks for combat end,
# and returns an HTML fragment appended to the terminal by terminal.js.

import logging
from datetime import datetime

from flask import Blueprint, render_template, request, session, g, has_request_context
from database import (execute, execute_one, execute_write, get_player,
                      exclusive_transaction, get_all_settings, encumbered_ap_cost,
                      spend_ap_and_regen)
from queue_handler import enqueue_and_process, register_handler
from combat import actions as combat_actions
from combat import engine, flavour
import config_defaults as cfg

bp = Blueprint("combat", __name__)
logger = logging.getLogger(__name__)


def _clear_browser_combat_session():
    """Clear browser-only state when a human request context exists."""
    if has_request_context():
        session.pop("combat_session_id", None)


def _error_fragment(message: str) -> str:
    """Provide the internal error fragment operation used by this module."""
    return render_template("fragments/error.html", message=message,
                           player=g.get("player"))


def _get_session_id() -> int | None:
    """Load session id from current database state."""
    return session.get("combat_session_id")


def _external_world_boss_end(session_id: int) -> str | None:
    """Turn a concurrent final blow into a normal notice instead of a 500."""
    row = execute_one(
        """SELECT cs.status,cs.combat_type,w.name,p.character_name finisher
           FROM combat_sessions cs
           LEFT JOIN world_boss_events e ON e.id=cs.world_boss_event_id
           LEFT JOIN world_bosses w ON w.id=e.world_boss_id
           LEFT JOIN players p ON p.id=e.defeated_by_player_id WHERE cs.id=?""",
        (session_id,)
    )
    if row and row["combat_type"] == "WORLD_BOSS" and row["status"] != "ACTIVE":
        _clear_browser_combat_session()
        message = (f"{row['finisher']} delivered the final blow to {row['name']}."
                   if row.get("finisher") else f"The shared battle against {row['name']} has ended.")
        return render_template("fragments/combat_external_end.html", message=message,
                               player=get_player(g.player["id"]))
    return None


# ─────────────────────────────────────────────────────────────────────────────
# POST /combat/action
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/combat/action", methods=["POST"])
def action():
    """Handle the action workflow."""
    session_id = _get_session_id()
    if not session_id:
        return _error_fragment("No active combat session.")
    if ended_notice := _external_world_boss_end(session_id):
        return ended_notice

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
    att_special = att_eq.get("bonuses")

    # AP can change between an automated character choosing Escape and this
    # queued round acquiring the database lock (for example a simultaneous
    # scheduled/manual NPC action). NPCs follow the established zero-AP rule:
    # if Escape is no longer legal, fight with Attack instead. Human requests
    # still receive the normal validation error rather than having their choice
    # silently changed.
    requested_action = action_type
    action_fallback = None
    if action_type == "escape":
        escape_cost = encumbered_ap_cost(
            attacker, settings.get("AP_COST_ESCAPE", cfg.AP_COST_ESCAPE), settings
        )
        if attacker["current_ap"] < escape_cost:
            is_npc = bool(execute_one(
                "SELECT 1 FROM npc_profiles WHERE player_id=? AND enabled=1 AND retired=0",
                (player_id,),
            ))
            if is_npc:
                action_type = "attack"
                action_fallback = (
                    f"Escape became unaffordable ({attacker['current_ap']} AP; "
                    f"{escape_cost} needed), so the NPC fought instead."
                )
            else:
                raise ValueError(f"Not enough AP to attempt escape (need {escape_cost}).")

    # Determine opponent for initiative
    if sess["combat_type"] == "PVP":
        defender = state["defender"]
        def_special = state["defender_equipped"].get("bonuses")
    else:
        defender = state["boss"] or state["minion"]
        def_special = None

    # --- Initiative ---
    att_init_bonus = att_special.get("initiative_bonus", 0) if att_special else 0
    att_init, att_agi = engine.calc_initiative(attacker, att_init_bonus)
    # PvP defenders receive the same equipped-special and permanent-perk
    # initiative bonuses as the initiating player. Creature initiative remains
    # authored directly on the creature stat block.
    def_init_bonus = def_special.get("initiative_bonus", 0) if def_special else 0
    def_init, def_agi = engine.calc_initiative(defender, def_init_bonus)

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
                def_init, _ = engine.calc_initiative(defender, def_init_bonus)
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
        if first_result.get("escaped"):
            return _escaped_round_result(round_log, session_id, attacker_first, att_init, def_init)
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
        if second_result.get("escaped"):
            return _escaped_round_result(round_log, session_id, attacker_first, att_init, def_init)
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

    # Boss and minion fights normally continue until someone falls, but a hard
    # cap prevents corrupted balance or modifiers from creating endless combat.
    hard_cap = (settings.get("WORLD_BOSS_ROUNDS_MAX", cfg.WORLD_BOSS_ROUNDS_MAX)
                if sess["combat_type"] == "WORLD_BOSS" else
                settings.get("COMBAT_ROUNDS_HARD_CAP", cfg.COMBAT_ROUNDS_HARD_CAP))
    forced_stalemate = (not combat_ended and sess["combat_type"] in ("BOSS", "MINION", "WORLD_BOSS")
                        and reload_sess["current_round"] > hard_cap)

    # Capture the opponent's post-round condition before finalization can reset
    # a defeated boss instance for its next encounter.
    state = combat_actions.get_combat_state(session_id)
    opponent = state.get("defender") or state.get("boss") or state.get("minion")
    opponent_max_hp = engine.calc_max_hp(opponent) if sess["combat_type"] == "PVP" else opponent["max_hp"]
    opponent_health = flavour.hp_status(opponent["current_hp"], opponent_max_hp)

    # --- Post-combat resolution ---
    final_result = None
    if forced_stalemate:
        final_result = combat_actions.finalize_stalemate(session_id, state)
        combat_ended = True
        result_type = "STALEMATE"
        _clear_browser_combat_session()
    elif combat_ended and winner_side:
        final_result = combat_actions.finalize_combat(
            session_id, winner_side, result_type, state
        )
        _clear_browser_combat_session()

    result = {
        "round_log":       round_log,
        "combat_ended":    combat_ended,
        "at_round_limit":  at_round_limit,
        "winner_side":     winner_side,
        "final_result":    final_result,
        "session_id":      session_id,
        "round_number":    sess["current_round"],
        "attacker_first":  attacker_first,
        "att_init":        att_init,
        "def_init":        def_init,
        "opponent_health": opponent_health,
        "requested_action": requested_action,
        "resolved_action": action_type,
        "action_fallback": action_fallback,
    }
    _record_round_history(result)
    return result


def _escaped_round_result(round_log, session_id, attacker_first, att_init, def_init):
    """Return immediately after a successful normal Escape action."""
    combat_session = execute_one(
        "SELECT current_round FROM combat_sessions WHERE id = ?", (session_id,)
    )
    # handle_escape resolves the database session and clears the combat flags.
    # Also discard the browser-side session reference so the next navigation
    # cannot try to resume combat that has already ended.
    _clear_browser_combat_session()
    result = {
        "round_log": round_log, "combat_ended": True, "at_round_limit": False,
        "winner_side": None, "final_result": {"result_type": "ESCAPE"},
        "session_id": session_id, "attacker_first": attacker_first,
        "att_init": att_init, "def_init": def_init,
        # The result fragment replaces the ordinary round fragment, so it needs
        # the round number in order to display the Escape action and its roll.
        "round_number": combat_session["current_round"] if combat_session else None,
    }
    _record_round_history(result)
    return result


def _record_round_history(result: dict) -> None:
    """Record a readable round without ever allowing logging to break combat."""
    try:
        _record_round_history_impl(result)
    except Exception:
        # The round has already resolved by the time this optional history is
        # written. Preserve the combat result even if descriptive logging has
        # malformed legacy data or encounters an unexpected schema mismatch.
        logger.exception("Could not write readable history for combat session %s",
                         result.get("session_id"))


def _record_round_history_impl(result: dict) -> None:
    """Build and persist one readable daily transcript entry per participant."""
    session_id = result.get("session_id")
    round_log = result.get("round_log") or []
    if not session_id or not round_log:
        return
    combat = execute_one("SELECT * FROM combat_sessions WHERE id=?", (session_id,))
    if not combat:
        return
    attacker = execute_one(
        "SELECT character_name FROM players WHERE id=?", (combat["attacker_player_id"],)
    )
    if combat["combat_type"] == "PVP":
        opponent = execute_one(
            "SELECT character_name FROM players WHERE id=?", (combat["defender_player_id"],)
        )
    elif combat["combat_type"] == "BOSS":
        opponent = execute_one(
            """SELECT b.name AS character_name
               FROM boss_instances bi JOIN bosses b ON b.id=bi.boss_id
               WHERE bi.id=?""",
            (combat["boss_instance_id"],)
        )
    elif combat["combat_type"] == "WORLD_BOSS":
        opponent = execute_one(
            """SELECT w.name AS character_name FROM world_boss_events e
               JOIN world_bosses w ON w.id=e.world_boss_id WHERE e.id=?""",
            (combat["world_boss_event_id"],)
        )
    else:
        opponent = execute_one(
            """SELECT m.name AS character_name
               FROM minion_instances mi JOIN minions m ON m.id=mi.minion_id
               WHERE mi.id=?""",
            (combat["minion_instance_id"],)
        )
    attacker_name = attacker["character_name"] if attacker else "Attacker"
    opponent_name = opponent["character_name"] if opponent else "Opponent"
    initiative = (f"Initiative: {attacker_name} {result.get('att_init', '?')} vs "
                  f"{opponent_name} {result.get('def_init', '?')}")
    actions = []
    for action in round_log:
        flavor_text = action.get("flavor") or action.get("message") or action.get("action", "Action")
        roll = action.get("roll_detail")
        damage = action.get("outcome_detail")
        details = " | ".join(part for part in (roll, damage) if part)
        actions.append(f"{flavor_text}{' [' + details + ']' if details else ''}")
    transcript = f"Round {result.get('round_number', '?')} — {initiative}. " + " ".join(actions)
    recipients = [combat["attacker_player_id"]]
    if combat["combat_type"] == "PVP" and combat.get("defender_player_id"):
        recipients.append(combat["defender_player_id"])
    with exclusive_transaction():
        for recipient_id in recipients:
            execute_write(
                """INSERT INTO daily_feed
                   (feed_scope,player_id,flavor_text,event_category,combat_session_id)
                   VALUES('PERSONAL',?,?, 'COMBAT_TURN',?)""",
                (recipient_id, transcript, session_id)
            )


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
    with exclusive_transaction():
        # Every unlocked equipped special shares the normal per-round wear.
        for att_special in state["attacker_equipped"].get("specials", []):
            loss_pts = engine.calc_special_item_round_loss(
                state["attacker_equipped"].get("bonuses")
            )
            new_dur = max(0, att_special["current_durability"] - loss_pts)
            execute_write(
                "UPDATE inventory_items SET current_durability = ? WHERE id = ?",
                (new_dur, att_special["inv_id"])
            )
            if new_dur == 0:
                combat_actions._destroy_item(
                    att_special["inv_id"],
                    {**att_special, "item_type": "SPECIAL", "item_id": att_special["id"]},
                    state["session"]["attacker_player_id"]
                )

        # Defender special item (PvP only)
        if state["session"]["combat_type"] == "PVP" and state.get("defender_equipped"):
            for def_special in state["defender_equipped"].get("specials", []):
                loss_pts = engine.calc_special_item_round_loss(
                    state["defender_equipped"].get("bonuses")
                )
                new_dur = max(0, def_special["current_durability"] - loss_pts)
                execute_write(
                    "UPDATE inventory_items SET current_durability = ? WHERE id = ?",
                    (new_dur, def_special["inv_id"])
                )
                if new_dur == 0:
                    combat_actions._destroy_item(
                        def_special["inv_id"],
                        {**def_special, "item_type": "SPECIAL", "item_id": def_special["id"]},
                        state["session"]["defender_player_id"]
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
    if ended_notice := _external_world_boss_end(session_id):
        return ended_notice
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
    at_round_limit = False
    opponent_health = None
    # Player steal attempt
    steal_result = combat_actions.handle_steal(session_id, player_id, state)
    round_log.append(steal_result)

    # Check if escape happened (steal on escaped opponent?)
    ended, winner_side = combat_actions.check_combat_end(state)
    final_result = None
    if ended:
        state = combat_actions.get_combat_state(session_id)
        final_result = combat_actions.finalize_combat(session_id, winner_side, "1HP_WIN", state)
        _clear_browser_combat_session()
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
            _clear_browser_combat_session()
        else:
            _apply_end_of_round(session_id, state, get_all_settings())
            with exclusive_transaction():
                execute_write(
                    "UPDATE combat_sessions SET current_round = current_round + 1 WHERE id = ?",
                    (session_id,)
                )

    # Steal is a complete combat round and must obey the same continuation
    # limits and provide the same opponent status as every other action.
    if not ended:
        settings = get_all_settings()
        reload_sess = execute_one("SELECT * FROM combat_sessions WHERE id=?", (session_id,))
        pvp_rounds = settings.get("COMBAT_ROUNDS_DEFAULT", cfg.COMBAT_ROUNDS_DEFAULT)
        max_rounds = pvp_rounds + (
            reload_sess["rounds_extended"]
            * settings.get("COMBAT_ROUNDS_EXTENSION", cfg.COMBAT_ROUNDS_EXTENSION)
        )
        at_round_limit = (sess["combat_type"] == "PVP"
                          and reload_sess["current_round"] > max_rounds)
        hard_cap = (settings.get("WORLD_BOSS_ROUNDS_MAX", cfg.WORLD_BOSS_ROUNDS_MAX)
                    if sess["combat_type"] == "WORLD_BOSS" else
                    settings.get("COMBAT_ROUNDS_HARD_CAP", cfg.COMBAT_ROUNDS_HARD_CAP))
        forced_stalemate = (sess["combat_type"] in ("BOSS", "MINION", "WORLD_BOSS")
                            and reload_sess["current_round"] > hard_cap)
        state = combat_actions.get_combat_state(session_id)
        opponent = state.get("defender") or state.get("boss") or state.get("minion")
        opponent_max_hp = (engine.calc_max_hp(opponent) if sess["combat_type"] == "PVP"
                           else opponent["max_hp"])
        opponent_health = flavour.hp_status(opponent["current_hp"], opponent_max_hp)
        if forced_stalemate:
            final_result = combat_actions.finalize_stalemate(session_id, state)
            ended = True
            _clear_browser_combat_session()

    result = {
        "round_log":      round_log,
        "combat_ended":   ended,
        "at_round_limit": at_round_limit,
        "winner_side":    winner_side,
        "final_result":   final_result,
        "session_id":     session_id,
        "round_number":   sess["current_round"],
        "attacker_first": True,
        "att_init": 0, "def_init": 0,
        "opponent_health": opponent_health,
    }
    _record_round_history(result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# POST /combat/extend  (PvP round extension)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/combat/extend", methods=["POST"])
def extend():
    """Handle the extend workflow."""
    session_id = _get_session_id()
    if not session_id:
        return _error_fragment("No active combat session.")
    player = g.player
    result = enqueue_and_process(
        player["id"], "combat_extend", {"session_id": session_id}
    )
    if result.get("error"):
        return _error_fragment(result["error"])
    player = get_player(player["id"]) or player
    return render_template("fragments/combat_resume.html",
                           session_id=session_id, player=player,
                           extension_rounds=result["extension_rounds"])


@register_handler("combat_extend")
def handle_combat_extend(player_id: int, payload: dict) -> dict:
    """Process the queued combat extend action against validated game state."""
    session_id = payload["session_id"]
    settings   = get_all_settings()
    ap_cost = settings.get("AP_COST_COMBAT_EXTENSION", cfg.AP_COST_COMBAT_EXTENSION)

    player = get_player(player_id)
    ap_cost = encumbered_ap_cost(player, ap_cost, settings)
    if player["current_ap"] < ap_cost:
        return {"error": f"Not enough AP to extend. Need {ap_cost}."}

    sess = execute_one("SELECT * FROM combat_sessions WHERE id = ?", (session_id,))
    if not sess or sess["status"] != "ACTIVE":
        return {"error": "This combat is no longer active."}
    if sess["attacker_player_id"] != player_id:
        return {"error": "You are not the attacker in this combat."}
    if sess["combat_type"] != "PVP":
        return {"error": "Round extension is only available in PvP."}

    base_rounds = settings.get("COMBAT_ROUNDS_DEFAULT", cfg.COMBAT_ROUNDS_DEFAULT)
    extension_rounds = settings.get("COMBAT_ROUNDS_EXTENSION", cfg.COMBAT_ROUNDS_EXTENSION)
    current_limit = base_rounds + (sess["rounds_extended"] * extension_rounds)
    if sess["current_round"] <= current_limit:
        return {"error": "Combat has already been extended. Choose your next action."}

    with exclusive_transaction():
        spent = spend_ap_and_regen(player_id, player, ap_cost, settings)
        execute_write(
            "UPDATE combat_sessions SET rounds_extended = rounds_extended + 1 WHERE id = ?",
            (session_id,)
        )
    return {"success": True, "extension_rounds": extension_rounds,
            "hp_regenerated": spent["hp_regenerated"], "new_hp": spent["new_hp"]}


# ─────────────────────────────────────────────────────────────────────────────
# POST /combat/resolve  (score formula or auto-triggered by timer)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/combat/resolve", methods=["POST"])
def resolve():
    """Handle the resolve workflow."""
    session_id = _get_session_id()
    if not session_id:
        return _error_fragment("No active combat session.")
    player = g.player
    result = enqueue_and_process(
        player["id"], "combat_resolve", {"session_id": session_id}
    )
    if result.get("error"):
        return _error_fragment(result["error"])
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
    if sess["attacker_player_id"] != player_id:
        raise ValueError("You are not the attacker in this combat.")
    settings = get_all_settings()
    current_limit = (settings.get("COMBAT_ROUNDS_DEFAULT", cfg.COMBAT_ROUNDS_DEFAULT) +
                     sess["rounds_extended"] * settings.get(
                         "COMBAT_ROUNDS_EXTENSION", cfg.COMBAT_ROUNDS_EXTENSION))
    if sess["current_round"] <= current_limit:
        raise ValueError("Combat is still active; choose a combat action.")

    attacker = state["attacker"]
    defender = state["defender"]
    att_max_hp = engine.calc_max_hp(attacker)
    def_max_hp = engine.calc_max_hp(defender)

    att_score, def_score = engine.calc_pvp_score(
        sess, att_max_hp, def_max_hp,
        attacker_current_hp=attacker["current_hp"],
        defender_current_hp=defender["current_hp"],
    )
    winner_side  = "ATTACKER" if att_score > def_score else "DEFENDER"
    final_result = combat_actions.finalize_combat(
        session_id, winner_side, "SCORE_WIN", state
    )
    _clear_browser_combat_session()

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
    # g.player was loaded before the round changed HP/AP, so refresh it for the
    # fragment. This prevents the health display from lagging one round behind.
    player = get_player(player["id"]) or player
    if result.get("combat_ended"):
        pending_action = None
        interrupted_action_cancelled = None
        combat_row = execute_one(
            "SELECT combat_type FROM combat_sessions WHERE id=?", (session_id,)
        )
        if combat_row and combat_row["combat_type"] == "MINION":
            from routes.actions import (get_pending_interrupted_action,
                                        clear_pending_interrupted_action)
            pending = get_pending_interrupted_action(player["id"])
            final = result.get("final_result") or {}
            survived = (result.get("winner_side") == "ATTACKER"
                        or final.get("result_type") in ("ESCAPE", "STALEMATE"))
            if pending and survived:
                pending_action = pending
            elif pending:
                interrupted_action_cancelled = pending["action_type"]
                clear_pending_interrupted_action(player["id"])
        return render_template("fragments/combat_result.html",
                               result=result, player=player,
                               pending_action=pending_action,
                               interrupted_action_cancelled=interrupted_action_cancelled)
    if result.get("at_round_limit"):
        settings = get_all_settings()
        timeout  = settings.get("COMBAT_EXTENSION_TIMEOUT", cfg.COMBAT_EXTENSION_TIMEOUT)
        return render_template("fragments/combat_extend.html",
                               session_id=session_id, timeout=timeout, player=player)
    return render_template("fragments/combat_round.html",
                           result=result, session_id=session_id, player=player)


################################################################################
