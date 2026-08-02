# database.py
# Single point of contact for all DB operations.
# Provides: connection management, schema init, query helpers,
# exclusive transaction context manager, player/setting loaders.

import sqlite3
import logging
import math
from contextlib import contextmanager
from flask import g
import config_defaults as cfg

logger = logging.getLogger(__name__)


def get_db() -> sqlite3.Connection:
    """Return the thread-local DB connection, creating it if needed."""
    if 'db' not in g:
        g.db = sqlite3.connect(
            cfg.DB_PATH,
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=10,
        )
        g.db.row_factory = dict_factory
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


def close_db(e=None):
    """Close thread-local DB connection. Registered as teardown_appcontext."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    """sqlite3 row_factory: rows as dicts keyed by column name."""
    return {col[0]: val for col, val in zip(cursor.description, row)}


def init_db():
    """Create all tables and indexes if they don't exist.
    Safe to call on an existing DB. Called at startup and after full reset."""
    import os
    os.makedirs("data/logs/rejected", exist_ok=True)
    os.makedirs("data/logs/daily",    exist_ok=True)

    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with sqlite3.connect(cfg.DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        with open(schema_path, "r") as f:
            conn.executescript(f.read())
    logger.info("Database initialised at %s", cfg.DB_PATH)


@contextmanager
def exclusive_transaction():
    """Context manager: BEGIN EXCLUSIVE ... COMMIT/ROLLBACK.
    Use for all write operations to prevent race conditions.

    Usage:
        with exclusive_transaction():
            execute_write("UPDATE players SET credits = ? WHERE id = ?", (amt, pid))
    """
    db = get_db()
    db.execute("BEGIN EXCLUSIVE")
    try:
        yield
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def execute(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT, return all rows as list of dicts."""
    return get_db().execute(sql, params).fetchall()


def execute_one(sql: str, params: tuple = ()) -> dict | None:
    """Execute a SELECT, return first row as dict or None."""
    return get_db().execute(sql, params).fetchone()


def execute_write(sql: str, params: tuple = ()) -> int:
    """Execute INSERT/UPDATE/DELETE. Returns lastrowid or rowcount.
    Must be called inside exclusive_transaction()."""
    cursor = get_db().execute(sql, params)
    return cursor.lastrowid if cursor.lastrowid else cursor.rowcount


def get_player(player_id: int) -> dict | None:
    """Load player row with all derived computed fields attached.
    Called by context processor on every request."""
    player = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))
    if player is None:
        return None

    cursed = execute_one(
        "SELECT value FROM status_effects WHERE player_id = ? AND effect_type = 'CURSED'",
        (player_id,)
    )
    is_cursed = cursed is not None
    settings = get_all_settings()

    base_daily_ap  = settings.get("BASE_DAILY_AP",            cfg.BASE_DAILY_AP)
    ap_cap         = settings.get("AP_CARRYOVER_CAP",         cfg.AP_CARRYOVER_CAP)
    inv_limit_base = settings.get("INVENTORY_LIMIT",          cfg.INVENTORY_LIMIT)
    inactive_days  = settings.get("INACTIVE_DAYS_THRESHOLD",  cfg.INACTIVE_DAYS_THRESHOLD)
    ap_regen       = settings.get("AP_PASSIVE_HP_REGEN",      cfg.AP_PASSIVE_HP_REGEN)
    end_divisor    = settings.get("END_HP_REGEN_DIVISOR",     cfg.END_HP_REGEN_DIVISOR)
    curse_red      = settings.get("CURSE_AP_REDUCTION",       cfg.CURSE_AP_REDUCTION)

    end   = player["end_stat"]
    level = player["level"]

    max_hp     = 10 + end + (5 * level)
    raw_max_ap = base_daily_ap + math.floor(end / 2)
    max_ap     = int(raw_max_ap * (1 - curse_red)) if is_cursed else raw_max_ap
    max_ap     = min(max_ap, ap_cap)
    inv_limit  = inv_limit_base + math.floor(player["str_stat"] / 2)
    passive_regen = ap_regen + math.floor(end / end_divisor)

    inv_count = execute_one(
        "SELECT COUNT(*) as cnt FROM inventory_items WHERE player_id = ?", (player_id,)
    )["cnt"]

    from datetime import datetime
    is_inactive = False
    if player["last_login_at"]:
        try:
            last = datetime.fromisoformat(player["last_login_at"])
            is_inactive = (datetime.utcnow() - last).days >= inactive_days
        except ValueError:
            pass

    hp_pct = (player["current_hp"] / max_hp * 100) if max_hp > 0 else 0
    if   hp_pct >= 76: hp_tier = "Healthy"
    elif hp_pct >= 51: hp_tier = "Wounded"
    elif hp_pct >= 26: hp_tier = "Hurt"
    else:              hp_tier = "Critical"

    player.update({
        "max_hp":            max_hp,
        "max_ap":            max_ap,
        "inventory_limit":   inv_limit,
        "inventory_count":   inv_count,
        "is_overencumbered": inv_count > inv_limit,
        "is_cursed":         is_cursed,
        "is_inactive":       is_inactive,
        "passive_regen":     passive_regen,
        "hp_tier":           hp_tier,
        "hp_pct":            round(hp_pct, 1),
    })
    return player


def get_player_equipped(player: dict) -> dict:
    """Load full weapon, armor, and special item rows for a player's equipped gear.
    Returns {'weapon': dict|None, 'armor': dict|None, 'special': dict|None}"""
    result = {"weapon": None, "armor": None, "special": None}
    for slot, col, table in [
        ("weapon",  "equipped_weapon_id",  "weapons"),
        ("armor",   "equipped_armor_id",   "armor"),
        ("special", "equipped_special_id", "special_items"),
    ]:
        inv_id = player.get(col)
        if inv_id:
            inv_row = execute_one("SELECT * FROM inventory_items WHERE id = ?", (inv_id,))
            if inv_row:
                content = execute_one(f"SELECT * FROM {table} WHERE id = ?", (inv_row["item_id"],))
                if content:
                    result[slot] = {**content,
                                    "inv_id": inv_id,
                                    "current_durability": inv_row["current_durability"]}
    return result


def get_setting(constant_name: str, default=None):
    """Look up one constant from settings table; falls back to config_defaults."""
    row = execute_one("SELECT value FROM settings WHERE constant_name = ?", (constant_name,))
    if row is None:
        fallback = getattr(cfg, constant_name, default)
        logger.warning("Setting '%s' missing from DB — using fallback: %s", constant_name, fallback)
        return fallback
    raw = row["value"]
    target_type = cfg.SETTING_TYPES.get(constant_name)
    if target_type is bool:  return raw.upper() in ("TRUE", "1", "YES")
    if target_type is int:   return int(raw)
    if target_type is float: return float(raw)
    return raw


def get_all_settings() -> dict:
    """Return all settings as a typed dict. Cached on g per request."""
    if "settings_cache" in g:
        return g.settings_cache
    rows = execute("SELECT constant_name, value FROM settings")
    result = {}
    for row in rows:
        name, raw = row["constant_name"], row["value"]
        t = cfg.SETTING_TYPES.get(name)
        try:
            if t is bool:  result[name] = raw.upper() in ("TRUE", "1", "YES")
            elif t is int:   result[name] = int(raw)
            elif t is float: result[name] = float(raw)
            else:            result[name] = raw
        except (ValueError, TypeError):
            result[name] = raw
    g.settings_cache = result
    return result


################################################################################
