"""Personal and global feed endpoints used by the terminal interface."""
# routes/feeds.py
# Lightweight JSON polling endpoints for the live terminal feed.
# Called every 5 seconds by terminal.js.
# These are the only two JSON-returning routes in the main app.

from flask import Blueprint, jsonify, request, session
from database import execute

bp = Blueprint("feeds", __name__)


@bp.route("/feed/personal/latest")
def personal_latest():
    """Return new personal feed entries since a given timestamp.
    Query param: since=<ISO datetime string>"""
    player_id = session.get("player_id")
    since = request.args.get("since", "1970-01-01T00:00:00")

    rows = execute(
        """SELECT flavor_text, event_category, occurred_at, combat_session_id
           FROM daily_feed
           WHERE player_id = ? AND occurred_at > ?
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
        """SELECT flavor_text, event_category, occurred_at
           FROM daily_feed
           WHERE feed_scope = 'GLOBAL' AND occurred_at > ?
           ORDER BY occurred_at ASC""",
        (since,)
    )
    return jsonify(rows)


################################################################################
