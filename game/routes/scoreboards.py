"""Read-only public progression, combat, economy, and shame rankings."""
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
    """Handle the index workflow."""
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
    """Query and rank players for the level xp scoreboard."""
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
    """Query and rank players for the pvp kills scoreboard."""
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
    """Query and rank players for the boss kills global scoreboard."""
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
    """Query and rank players for the minion kills global scoreboard."""
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
    """Query and rank players for the minion kills per minion scoreboard."""
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
    """Query and rank players for the credits scoreboard."""
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
    """Provide the internal shame board operation used by this module."""
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
