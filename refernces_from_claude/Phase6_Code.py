################################################################################
# PHASE 6 CODE — Scoreboards
# BBS-Inspired Multiplayer Dueling Game
#
# Files included:
#   1. routes/scoreboards.py  — Full leaderboard queries (replaces Phase 3 stub)
#   2. templates/scoreboards/scoreboards.html
#
# Replaces the Phase 3 stub for routes/scoreboards.py.
################################################################################

################################################################################
# FILE: routes/scoreboards.py (Phase 6 — full implementation)
################################################################################

# routes/scoreboards.py  (Phase 6 — full implementation)
# Full-page leaderboards. All data computed via live DB queries.
# Inactive players (7+ days without login) excluded from all boards.

import logging
from flask import Blueprint, render_template, g
from database import execute, execute_one, get_all_settings
import config_defaults as cfg

bp = Blueprint("scoreboards", __name__)
logger = logging.getLogger(__name__)


@bp.route("/scoreboards")
def index():
    settings      = get_all_settings()
    inactive_days = settings.get("INACTIVE_DAYS_THRESHOLD", cfg.INACTIVE_DAYS_THRESHOLD)
    cutoff_expr   = f"datetime('now', '-{inactive_days} days')"

    top_level      = _top_level_xp(cutoff_expr)
    top_pvp_kills  = _top_pvp_kills(cutoff_expr)
    top_boss_global= _top_boss_kills_global(cutoff_expr)
    top_boss_each  = _top_boss_kills_per_boss(cutoff_expr)
    top_minion_gl  = _top_minion_kills_global(cutoff_expr)
    top_minion_each= _top_minion_kills_per_minion(cutoff_expr)
    top_credits    = _top_credits(cutoff_expr)
    shame_board    = _shame_board(cutoff_expr)

    return render_template(
        "scoreboards/scoreboards.html",
        top_level=top_level,
        top_pvp_kills=top_pvp_kills,
        top_boss_global=top_boss_global,
        top_boss_each=top_boss_each,
        top_minion_global=top_minion_gl,
        top_minion_each=top_minion_each,
        top_credits=top_credits,
        shame_board=shame_board,
    )


def _top_level_xp(cutoff_expr: str, limit: int = 20) -> list:
    return execute(
        f"""SELECT character_name, level, xp, class_id
            FROM players
            WHERE is_banned = 0
              AND (last_login_at IS NULL OR last_login_at >= {cutoff_expr})
            ORDER BY level DESC, xp DESC
            LIMIT ?""",
        (limit,)
    )


def _top_pvp_kills(cutoff_expr: str, limit: int = 20) -> list:
    return execute(
        f"""SELECT p.character_name, p.level, ps.pvp_kills
            FROM players p
            JOIN player_stats ps ON ps.player_id = p.id
            WHERE p.is_banned = 0
              AND (p.last_login_at IS NULL OR p.last_login_at >= {cutoff_expr})
            ORDER BY ps.pvp_kills DESC
            LIMIT ?""",
        (limit,)
    )


def _top_boss_kills_global(cutoff_expr: str, limit: int = 20) -> list:
    return execute(
        f"""SELECT p.character_name, p.level, SUM(bi.kill_count) as total_kills
            FROM players p
            JOIN boss_instances bi ON bi.player_id = p.id
            WHERE p.is_banned = 0
              AND (p.last_login_at IS NULL OR p.last_login_at >= {cutoff_expr})
            GROUP BY p.id
            ORDER BY total_kills DESC
            LIMIT ?""",
        (limit,)
    )


def _top_boss_kills_per_boss(cutoff_expr: str, limit_per: int = 5) -> dict:
    """Returns dict of {boss_name: [top players]}."""
    bosses = execute("SELECT id, name FROM bosses WHERE is_active = 1 ORDER BY name")
    result = {}
    for boss in bosses:
        rows = execute(
            f"""SELECT p.character_name, bi.kill_count
                FROM boss_instances bi
                JOIN players p ON p.id = bi.player_id
                WHERE bi.boss_id = ?
                  AND p.is_banned = 0
                  AND (p.last_login_at IS NULL OR p.last_login_at >= {cutoff_expr})
                  AND bi.kill_count > 0
                ORDER BY bi.kill_count DESC
                LIMIT ?""",
            (boss["id"], limit_per)
        )
        if rows:
            result[boss["name"]] = rows
    return result


def _top_minion_kills_global(cutoff_expr: str, limit: int = 20) -> list:
    return execute(
        f"""SELECT p.character_name, p.level, SUM(mi.kill_count) as total_kills
            FROM players p
            JOIN minion_instances mi ON mi.player_id = p.id
            WHERE p.is_banned = 0
              AND (p.last_login_at IS NULL OR p.last_login_at >= {cutoff_expr})
            GROUP BY p.id
            ORDER BY total_kills DESC
            LIMIT ?""",
        (limit,)
    )


def _top_minion_kills_per_minion(cutoff_expr: str, limit_per: int = 5) -> dict:
    minions = execute("SELECT id, name FROM minions WHERE is_active = 1 ORDER BY name")
    result  = {}
    for minion in minions:
        rows = execute(
            f"""SELECT p.character_name, mi.kill_count
                FROM minion_instances mi
                JOIN players p ON p.id = mi.player_id
                WHERE mi.minion_id = ?
                  AND p.is_banned = 0
                  AND (p.last_login_at IS NULL OR p.last_login_at >= {cutoff_expr})
                  AND mi.kill_count > 0
                ORDER BY mi.kill_count DESC
                LIMIT ?""",
            (minion["id"], limit_per)
        )
        if rows:
            result[minion["name"]] = rows
    return result


def _top_credits(cutoff_expr: str, limit: int = 20) -> list:
    return execute(
        f"""SELECT character_name, level, credits
            FROM players
            WHERE is_banned = 0
              AND (last_login_at IS NULL OR last_login_at >= {cutoff_expr})
            ORDER BY credits DESC
            LIMIT ?""",
        (limit,)
    )


def _shame_board(cutoff_expr: str, limit: int = 20) -> list:
    return execute(
        f"""SELECT p.character_name, p.level, ps.times_reduced_to_1hp
            FROM players p
            JOIN player_stats ps ON ps.player_id = p.id
            WHERE p.is_banned = 0
              AND (p.last_login_at IS NULL OR p.last_login_at >= {cutoff_expr})
            ORDER BY ps.times_reduced_to_1hp DESC
            LIMIT ?""",
        (limit,)
    )


################################################################################
# FILE: templates/scoreboards/scoreboards.html
################################################################################

<!-- FILE: templates/scoreboards/scoreboards.html -->
{% extends "base.html" %}
{% block title %}Scoreboards{% endblock %}
{% block content %}
<div id="page-content">
    <a href="{{ url_for('dashboard.index') }}" class="back-link">← Back to Dashboard</a>
    <h2 class="page-title">🏆 SCOREBOARDS</h2>

    <!-- TOP LEVEL / XP -->
    <h3 style="color:var(--amber);margin-bottom:8px;">Top Level / XP</h3>
    {% if top_level %}
    <table style="margin-bottom:24px;">
        <tr><th>#</th><th>Name</th><th>Level</th><th>XP</th></tr>
        {% for p in top_level %}
        <tr>
            <td style="color:var(--grey)">{{ loop.index }}</td>
            <td>{{ p.character_name }}</td>
            <td>{{ p.level }}</td>
            <td>{{ p.xp }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color:var(--grey);margin-bottom:24px;">No data yet.</p>
    {% endif %}

    <!-- PVP KILLS -->
    <h3 style="color:var(--amber);margin-bottom:8px;">Most PvP Kills</h3>
    {% if top_pvp_kills %}
    <table style="margin-bottom:24px;">
        <tr><th>#</th><th>Name</th><th>Level</th><th>PvP Kills</th></tr>
        {% for p in top_pvp_kills %}
        <tr>
            <td style="color:var(--grey)">{{ loop.index }}</td>
            <td>{{ p.character_name }}</td>
            <td>{{ p.level }}</td>
            <td>{{ p.pvp_kills }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color:var(--grey);margin-bottom:24px;">No data yet.</p>
    {% endif %}

    <!-- BOSS KILLS GLOBAL -->
    <h3 style="color:var(--amber);margin-bottom:8px;">Most Boss Kills (Global)</h3>
    {% if top_boss_global %}
    <table style="margin-bottom:24px;">
        <tr><th>#</th><th>Name</th><th>Level</th><th>Total Boss Kills</th></tr>
        {% for p in top_boss_global %}
        <tr>
            <td style="color:var(--grey)">{{ loop.index }}</td>
            <td>{{ p.character_name }}</td>
            <td>{{ p.level }}</td>
            <td>{{ p.total_kills }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color:var(--grey);margin-bottom:24px;">No data yet.</p>
    {% endif %}

    <!-- BOSS KILLS PER BOSS -->
    {% if top_boss_each %}
    <h3 style="color:var(--amber);margin-bottom:8px;">Boss Kill Leaders</h3>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-bottom:24px;">
        {% for boss_name, players in top_boss_each.items() %}
        <div style="background:var(--bg-panel);border:1px solid var(--border);padding:10px;">
            <div style="color:var(--amber);margin-bottom:6px;font-size:12px;">{{ boss_name }}</div>
            {% for p in players %}
            <div style="display:flex;justify-content:space-between;font-size:12px;">
                <span>{{ p.character_name }}</span>
                <span style="color:var(--green)">{{ p.kill_count }}</span>
            </div>
            {% endfor %}
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <!-- MINION KILLS GLOBAL -->
    <h3 style="color:var(--amber);margin-bottom:8px;">Most Minion Kills (Global)</h3>
    {% if top_minion_global %}
    <table style="margin-bottom:24px;">
        <tr><th>#</th><th>Name</th><th>Level</th><th>Total Minion Kills</th></tr>
        {% for p in top_minion_global %}
        <tr>
            <td style="color:var(--grey)">{{ loop.index }}</td>
            <td>{{ p.character_name }}</td>
            <td>{{ p.level }}</td>
            <td>{{ p.total_kills }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color:var(--grey);margin-bottom:24px;">No data yet.</p>
    {% endif %}

    <!-- CREDITS -->
    <h3 style="color:var(--amber);margin-bottom:8px;">Most Credits</h3>
    {% if top_credits %}
    <table style="margin-bottom:24px;">
        <tr><th>#</th><th>Name</th><th>Level</th><th>Credits</th></tr>
        {% for p in top_credits %}
        <tr>
            <td style="color:var(--grey)">{{ loop.index }}</td>
            <td>{{ p.character_name }}</td>
            <td>{{ p.level }}</td>
            <td>{{ p.credits }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color:var(--grey);margin-bottom:24px;">No data yet.</p>
    {% endif %}

    <!-- SHAME BOARD -->
    <h3 style="color:var(--red);margin-bottom:8px;">💀 Shame Board (Most Deaths)</h3>
    {% if shame_board %}
    <table style="margin-bottom:24px;">
        <tr><th>#</th><th>Name</th><th>Level</th><th>Times at 1 HP</th></tr>
        {% for p in shame_board %}
        <tr>
            <td style="color:var(--grey)">{{ loop.index }}</td>
            <td>{{ p.character_name }}</td>
            <td>{{ p.level }}</td>
            <td style="color:var(--red)">{{ p.times_reduced_to_1hp }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color:var(--grey);margin-bottom:24px;">No data yet.</p>
    {% endif %}

</div>
{% endblock %}


