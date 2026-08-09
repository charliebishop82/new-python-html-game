"""Player-facing weekly world-boss status, live log, and standings."""

from flask import Blueprint, render_template, jsonify, g, request, redirect, url_for, session

from database import (execute, execute_one, execute_write, exclusive_transaction,
                      get_all_settings, get_player)
from queue_handler import enqueue_and_process, register_handler
from routes.actions import _deduct_ap_and_regen
import config_defaults as cfg
from world_boss import (get_active_event, activate_next_event, standings,
                        pending_event_for_player, prize_options, claim_prize)

bp = Blueprint("world_boss", __name__)


@bp.route("/world-boss")
def index():
    # New encounters are activated only by midnight maintenance (or an
    # explicit admin action), never merely because somebody opened this page.
    active_event = get_active_event()
    event = active_event or execute_one(
        """SELECT e.*,w.name,w.flavor_text,w.description FROM world_boss_events e
           JOIN world_bosses w ON w.id=e.world_boss_id ORDER BY e.id DESC LIMIT 1"""
    )
    reward_event = pending_event_for_player(g.player["id"])
    logs = _logs(event["id"], 0) if event else []
    settings = get_all_settings()
    cost = int(settings.get("AP_COST_WORLD_BOSS", cfg.AP_COST_WORLD_BOSS))
    reward_blocked = bool(reward_event and execute_one(
        """SELECT 1 FROM world_boss_rewards WHERE event_id=? AND place<?
           AND status!='AWARDED' LIMIT 1""", (reward_event["id"], reward_event["place"])
    ))
    return render_template("world_boss/index.html", event=event,
                           standings=standings(event["id"]) if event else [], logs=logs,
                           entry_cost=cost, is_active=bool(active_event),
                           can_fight=bool(active_event and not g.player["in_combat"]
                           and g.player["current_ap"] >= cost), reward_event=reward_event,
                           reward_blocked=reward_blocked,
                           prize_options=(prize_options(reward_event["id"], reward_event["place"])
                                          if reward_event else []))


@bp.route("/world-boss/claim", methods=["POST"])
def claim():
    """Claim one still-available prize in the locked placing order."""
    try:
        claim_prize(g.player["id"], int(request.form["event_id"]),
                    request.form["item_type"], int(request.form["item_id"]))
        return redirect(url_for("world_boss.index", feedback="World-boss prize awarded."))
    except (ValueError, KeyError, TypeError) as exc:
        return redirect(url_for("world_boss.index", error=str(exc)))


@bp.route("/world-boss/fight", methods=["POST"])
def fight():
    """Begin an ordinary combat attempt whose damage targets the shared pool."""
    event = get_active_event()
    if not event:
        return redirect(url_for("world_boss.index"))
    from routes.actions import begin_minion_interruption
    minion = begin_minion_interruption(
        g.player, "WORLD_BOSS", {"event_id": event["id"]}, get_all_settings()
    )
    if minion:
        result = enqueue_and_process(
            g.player["id"], "start_boss_fight",
            {"opponent_id": minion["id"], "encounter_type": "MINION", "cost_ap": 0}
        )
        if result.get("error"):
            return redirect(url_for("world_boss.index", error=result["error"]))
        session["combat_session_id"] = result["session_id"]
        return redirect(url_for("dashboard.index"))
    result = enqueue_and_process(g.player["id"], "start_world_boss_fight",
                                 {"event_id": event["id"]})
    if result.get("error"):
        return redirect(url_for("world_boss.index", error=result["error"]))
    session["combat_session_id"] = result["session_id"]
    return redirect(url_for("dashboard.index"))


@register_handler("start_world_boss_fight")
def handle_start_world_boss_fight(player_id, payload):
    """Validate and create one isolated attempt against the active weekly boss."""
    player = get_player(player_id)
    event = execute_one("SELECT * FROM world_boss_events WHERE id=? AND status='ACTIVE'",
                        (payload["event_id"],))
    settings = get_all_settings()
    cost = int(settings.get("AP_COST_WORLD_BOSS", cfg.AP_COST_WORLD_BOSS))
    if not event:
        return {"error": "That world-boss event has ended."}
    if player["in_combat"]:
        return {"error": "You are already in combat."}
    if player["current_ap"] < cost:
        return {"error": f"Not enough AP (need {cost})."}
    with exclusive_transaction():
        _, new_hp = _deduct_ap_and_regen(player_id, player, cost, settings)
        execute_write("UPDATE players SET in_combat=1 WHERE id=?", (player_id,))
        combat_id = execute_write(
            """INSERT INTO combat_sessions
               (combat_type,attacker_player_id,world_boss_event_id,status,attacker_hp_start)
               VALUES('WORLD_BOSS',?,?, 'ACTIVE',?)""",
            (player_id, event["id"], new_hp)
        )
        execute_write(
            """INSERT INTO world_boss_contributions(event_id,player_id,attempts)
               VALUES(?,?,1) ON CONFLICT(event_id,player_id)
               DO UPDATE SET attempts=attempts+1""", (event["id"], player_id)
        )
    return {"session_id": combat_id, "event_id": event["id"], "new_hp": new_hp}


@bp.route("/world-boss/status")
def status():
    event = get_active_event()
    if not event:
        return jsonify({"active": False})
    after = request.args.get("after", 0, type=int)
    return jsonify({
        "active": True, "event_id": event["id"], "name": event["name"],
        "current_hp": event["current_hp"], "starting_hp": event["starting_hp"],
        "hp_percent": round(event["current_hp"] / event["starting_hp"] * 100, 1),
        "standings": standings(event["id"]), "logs": _logs(event["id"], after),
    })


def _logs(event_id, after):
    return execute(
        """SELECT l.id,l.category,l.message,l.occurred_at,p.character_name
           FROM world_boss_event_log l LEFT JOIN players p ON p.id=l.player_id
           WHERE l.event_id=? AND l.id>? ORDER BY l.id ASC LIMIT 100""", (event_id, after)
    )
