"""Personal and global feed endpoints used by the terminal interface."""
# routes/feeds.py
# Lightweight JSON polling endpoints for the live terminal feed.
# Called every 5 seconds by terminal.js.
# These are the only two JSON-returning routes in the main app.

from flask import Blueprint, jsonify, render_template, request, session
from database import execute, get_player
import config_defaults as cfg

bp = Blueprint("feeds", __name__)


@bp.route("/help")
def game_help():
    """Show the canonical player-facing explanation of flows and formulas."""
    return render_template("help/game_help.html", xp_curve=cfg.XP_CURVE)


@bp.route("/feed/global")
def global_log():
    """Render a readable, scrollable history of public world announcements."""
    rows = execute(
        """SELECT id,flavor_text,event_category,occurred_at,combat_session_id
           FROM daily_feed WHERE feed_scope='GLOBAL'
           ORDER BY datetime(occurred_at) DESC,id DESC LIMIT 500"""
    )
    return render_template("feeds/global_log.html", entries=rows)


@bp.route("/feed/personal/latest")
def personal_latest():
    """Return new personal feed entries since a given timestamp.
    Query param: since=<ISO datetime string>"""
    player_id = session.get("player_id")
    since = request.args.get("since", "1970-01-01T00:00:00")

    rows = execute(
        """SELECT feed_scope,flavor_text,event_category,occurred_at,combat_session_id
           FROM daily_feed
           WHERE player_id = ? AND datetime(occurred_at) > datetime(?)
             AND event_category != 'COMBAT_TURN'
           ORDER BY occurred_at ASC""",
        (player_id, since)
    )
    return jsonify(rows)


@bp.route("/feed/global/latest")
def global_latest():
    """Return new global feed entries since a given timestamp.
    Query param: since=<ISO datetime string>"""
    since = request.args.get("since", "1970-01-01T00:00:00")

    rows = execute(
        """SELECT feed_scope,flavor_text,event_category,occurred_at FROM (
               SELECT feed_scope,flavor_text,event_category,occurred_at,id
               FROM daily_feed
               WHERE feed_scope = 'GLOBAL' AND datetime(occurred_at) > datetime(?)
               ORDER BY datetime(occurred_at) DESC, id DESC LIMIT 50
           ) ORDER BY datetime(occurred_at) ASC""",
        (since,)
    )
    return jsonify(rows)


@bp.route("/feed/player-status")
def player_status():
    """Return compact live state without reloading or disturbing the page."""
    player = get_player(session.get("player_id"))
    if not player:
        return jsonify({"authenticated": False}), 401
    from routes.character import get_player_combat_snapshot
    combat = get_player_combat_snapshot(player)
    return jsonify({
        "authenticated": True, "level": player["level"], "xp": player["xp"],
        "xp_threshold": player.get("next_level_xp"),
        "xp_next": player.get("xp_to_next_level"),
        "hp": player["current_hp"], "max_hp": player["max_hp"],
        "ap": player["current_ap"], "max_ap": player["max_ap"],
        "inventory_count": player.get("inventory_count", 0),
        "inventory_limit": player.get("inventory_limit", 0),
        "ac": combat["ac"],
        "damage_min": combat["damage_min"], "damage_max": combat["damage_max"],
        "damage_types": combat["damage_types"],
        "credits": player["credits"], "in_combat": bool(player["in_combat"]),
        "is_overencumbered": bool(player.get("is_overencumbered")),
        "is_cursed": bool(player.get("is_cursed")),
    })


@bp.route("/players/active")
def active_players():
    """List characters that submitted an action during the last five minutes."""
    rows = execute(
        """SELECT p.character_name,MAX(q.created_at) AS last_action_at,
                  CAST((julianday('now')-julianday(MAX(q.created_at)))*86400 AS INTEGER) seconds_ago
           FROM action_queue q JOIN players p ON p.id=q.player_id
           WHERE datetime(q.created_at)>=datetime('now','-5 minutes') AND p.is_banned=0
           GROUP BY p.id,p.character_name ORDER BY MAX(q.created_at) DESC,p.character_name"""
    )
    return jsonify({"count": len(rows), "players": rows, "window_minutes": 5})


################################################################################
