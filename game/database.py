"""SQLite connection, transaction, settings, and player-state helpers."""
# database.py
# Single point of contact for all DB operations.
# Provides: connection management, schema init, query helpers,
# exclusive transaction context manager, player/setting loaders.

import sqlite3
import logging
import math
import uuid
from datetime import datetime
from contextlib import contextmanager
from flask import g
import config_defaults as cfg

logger = logging.getLogger(__name__)


def calculate_max_hp(level: int, effective_end: int,
                     settings: dict | None = None) -> int:
    """Return the authoritative maximum HP for a fully resolved loadout."""
    settings = settings or get_all_settings()
    base = int(settings.get("BASE_HP", cfg.BASE_HP))
    per_level = int(settings.get("HP_PER_LEVEL", cfg.HP_PER_LEVEL))
    return base + int(effective_end) + (per_level * int(level))


def calculate_daily_ap(effective_end: int, bonus_ap: int = 0,
                       is_cursed: bool = False,
                       settings: dict | None = None) -> dict:
    """Return raw and effective daily AP after curse reduction and the cap."""
    settings = settings or get_all_settings()
    base = int(settings.get("BASE_DAILY_AP", cfg.BASE_DAILY_AP))
    cap = int(settings.get("AP_CARRYOVER_CAP", cfg.AP_CARRYOVER_CAP))
    curse_reduction = float(settings.get(
        "CURSE_AP_REDUCTION", cfg.CURSE_AP_REDUCTION
    ))
    raw = base + math.floor(int(effective_end) / 2) + int(bonus_ap or 0)
    after_curse = int(raw * (1 - curse_reduction)) if is_cursed else raw
    return {
        "raw": raw,
        "after_curse": after_curse,
        "effective": min(after_curse, cap),
        "cap": cap,
        "is_capped": after_curse > cap,
        "is_cursed": bool(is_cursed),
    }


def calculate_passive_regen(effective_end: int, hp_regen_bonus: int = 0,
                            settings: dict | None = None) -> int:
    """Return HP restored when an AP-charging action is completed."""
    settings = settings or get_all_settings()
    base = int(settings.get("AP_PASSIVE_HP_REGEN", cfg.AP_PASSIVE_HP_REGEN))
    divisor = max(1, int(settings.get(
        "END_HP_REGEN_DIVISOR", cfg.END_HP_REGEN_DIVISOR
    )))
    return base + math.floor(int(effective_end) / divisor) + int(hp_regen_bonus or 0)


SPECIAL_SLOT_COLUMNS = (
    "equipped_special_id", "equipped_special_2_id", "equipped_special_3_id",
)


def unlocked_special_slots(level: int) -> int:
    """One special slot initially, a second at level 8, and a third at level 16."""
    return 1 + int(int(level) >= 8) + int(int(level) >= 16)


def equipped_special_ids(player: dict, unlocked_only: bool = True) -> list[int]:
    """Return unique equipped special inventory IDs in stable slot order."""
    columns = SPECIAL_SLOT_COLUMNS[:unlocked_special_slots(player.get("level", 1))] \
        if unlocked_only else SPECIAL_SLOT_COLUMNS
    result = []
    for column in columns:
        inv_id = player.get(column)
        if inv_id and inv_id not in result:
            result.append(inv_id)
    return result


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


def encumbered_ap_cost(player: dict, base_cost: int, settings: dict | None = None) -> int:
    """Return an action's AP cost after the shared encumbrance penalty."""
    if not player or int(base_cost or 0) <= 0:
        return int(base_cost or 0)
    if "is_overencumbered" not in player:
        player = get_player(player["id"])
    if not player or not player.get("is_overencumbered"):
        return int(base_cost)
    settings = settings or get_all_settings()
    multiplier = max(1, int(settings.get(
        "OVERENCUMBERED_AP_MULTIPLIER", cfg.OVERENCUMBERED_AP_MULTIPLIER
    )))
    return int(base_cost) * multiplier


def inventory_capacity(effective_str: int, settings: dict | None = None) -> int:
    """Return carried-item capacity from the restrictive base plus STR scaling."""
    settings = settings or get_all_settings()
    base = max(3, int(settings.get("INVENTORY_LIMIT", cfg.INVENTORY_LIMIT)))
    divisor = max(1, int(settings.get(
        "INVENTORY_STR_DIVISOR", cfg.INVENTORY_STR_DIVISOR
    )))
    return base + math.floor(max(0, int(effective_str)) / divisor)


def tavern_quote(player: dict, settings: dict | None = None) -> dict:
    """Return proportional Tavern healing and its credit price."""
    settings = settings or get_all_settings()
    missing = max(0, int(player["max_hp"]) - int(player["current_hp"]))
    if missing <= 0:
        return {"missing_hp": 0, "heal_amount": 0, "credit_cost": 0}
    heal_pct = float(settings.get("TAVERN_HEAL_PERCENT", cfg.TAVERN_HEAL_PERCENT))
    heal_amount = min(missing, max(1, int(missing * heal_pct)))
    per_hp = max(0, int(settings.get(
        "TAVERN_CREDITS_PER_HP", cfg.TAVERN_CREDITS_PER_HP
    )))
    minimum = max(0, int(settings.get("TAVERN_MIN_COST", cfg.TAVERN_MIN_COST)))
    return {"missing_hp": missing, "heal_amount": heal_amount,
            "credit_cost": max(minimum, heal_amount * per_hp)}


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
        # CREATE TABLE IF NOT EXISTS does not add new columns to an existing
        # installation. Keep small additive migrations safe and repeatable.
        npc_columns = {row[1] for row in conn.execute("PRAGMA table_info(npc_profiles)")}
        if "thief" not in npc_columns:
            conn.execute("ALTER TABLE npc_profiles ADD COLUMN thief INTEGER NOT NULL DEFAULT 0")
        if "world_boss_hunter" not in npc_columns:
            conn.execute(
                "ALTER TABLE npc_profiles ADD COLUMN world_boss_hunter INTEGER NOT NULL DEFAULT 0"
            )
        if "wake_actions" not in npc_columns:
            conn.execute(
                "ALTER TABLE npc_profiles ADD COLUMN wake_actions INTEGER NOT NULL DEFAULT 0"
            )
        player_columns = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
        if "retired_at" not in player_columns:
            conn.execute("ALTER TABLE players ADD COLUMN retired_at TEXT")
        if "pending_perk" not in player_columns:
            conn.execute("ALTER TABLE players ADD COLUMN pending_perk INTEGER NOT NULL DEFAULT 0")
        for column in ("equipped_special_2_id", "equipped_special_3_id"):
            if column not in player_columns:
                conn.execute(f"ALTER TABLE players ADD COLUMN {column} INTEGER REFERENCES inventory_items(id)")
        class_columns = {row[1] for row in conn.execute("PRAGMA table_info(classes)")}
        class_migrations = {
            "initiative_bonus": "INTEGER NOT NULL DEFAULT 0",
            "crit_chance_bonus": "REAL NOT NULL DEFAULT 0",
            "crit_dmg_multiplier": "REAL NOT NULL DEFAULT 0",
            "ac_bonus": "INTEGER NOT NULL DEFAULT 0",
            "bonus_damage_amount": "INTEGER NOT NULL DEFAULT 0",
            "bonus_damage_type": "TEXT NOT NULL DEFAULT ''",
            "observe_bonus": "INTEGER NOT NULL DEFAULT 0",
            "encounter_bonus": "REAL NOT NULL DEFAULT 0",
            "durability_reduction": "REAL NOT NULL DEFAULT 0",
            "steal_bonus": "REAL NOT NULL DEFAULT 0",
            "shop_discount": "REAL NOT NULL DEFAULT 0",
        }
        added_class_passives = False
        for column, declaration in class_migrations.items():
            if column not in class_columns:
                conn.execute(f"ALTER TABLE classes ADD COLUMN {column} {declaration}")
                added_class_passives = True
        if added_class_passives:
            # Seed existing databases once. Future imports remain authoritative.
            conn.execute("""UPDATE classes SET bonus_damage_amount=1,
                         bonus_damage_type='Weapon',crit_dmg_multiplier=.10
                         WHERE name='Action Hero'""")
            conn.execute("""UPDATE classes SET initiative_bonus=2,
                         crit_chance_bonus=.05 WHERE name='Gunslinger'""")
            conn.execute("""UPDATE classes SET observe_bonus=2,
                         encounter_bonus=.05 WHERE name='Hunter'""")
            conn.execute("""UPDATE classes SET ac_bonus=1,
                         durability_reduction=.10 WHERE name='Juggernaut'""")
            conn.execute("""UPDATE classes SET steal_bonus=.10,
                         shop_discount=.05 WHERE name='Scoundrel'""")
        board_position_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(board_positions)")
        }
        if board_position_columns and "layer" not in board_position_columns:
            conn.execute(
                "ALTER TABLE board_positions ADD COLUMN layer INTEGER NOT NULL DEFAULT 1"
            )
        if board_position_columns:
            conn.execute("DROP INDEX IF EXISTS idx_board_positions_hex")
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_board_positions_hex
                   ON board_positions(board_id,layer,q,r)"""
            )
        if "in_scene_combat" not in player_columns:
            conn.execute("ALTER TABLE players ADD COLUMN in_scene_combat INTEGER NOT NULL DEFAULT 0")
        scene_choice_columns = {row[1] for row in conn.execute("PRAGMA table_info(scene_choices)")}
        if scene_choice_columns and "is_active" not in scene_choice_columns:
            conn.execute("ALTER TABLE scene_choices ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        scene_attempt_columns = {row[1] for row in conn.execute("PRAGMA table_info(scene_attempts)")}
        if scene_attempt_columns and "scene_combat_session_id" not in scene_attempt_columns:
            conn.execute("ALTER TABLE scene_attempts ADD COLUMN scene_combat_session_id INTEGER")
        scene_combat_columns = {row[1] for row in conn.execute("PRAGMA table_info(scene_combat_sessions)")}
        if scene_combat_columns and "version" not in scene_combat_columns:
            conn.execute("ALTER TABLE scene_combat_sessions ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
        for table in ("boss_instances", "minion_instances"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "encounter_max_hp" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN encounter_max_hp INTEGER")
        combat_columns = {row[1] for row in conn.execute("PRAGMA table_info(combat_sessions)")}
        if "world_boss_event_id" not in combat_columns:
            conn.execute("ALTER TABLE combat_sessions ADD COLUMN world_boss_event_id INTEGER")
        for column, declaration in (
            ("special_attack_used", "INTEGER NOT NULL DEFAULT 0"),
            ("special_buff_used", "INTEGER NOT NULL DEFAULT 0"),
            ("current_phase", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if column not in combat_columns:
                conn.execute(f"ALTER TABLE combat_sessions ADD COLUMN {column} {declaration}")
        npc_log_columns = {row[1] for row in conn.execute("PRAGMA table_info(npc_action_log)")}
        if "details_json" not in npc_log_columns:
            conn.execute("ALTER TABLE npc_action_log ADD COLUMN details_json TEXT")
        activity_columns = {row[1] for row in conn.execute("PRAGMA table_info(player_activity_log)")}
        if "seen_at" not in activity_columns:
            conn.execute("ALTER TABLE player_activity_log ADD COLUMN seen_at TEXT")
        queue_columns = {row[1] for row in conn.execute("PRAGMA table_info(action_queue)")}
        if "admin_acknowledged_at" not in queue_columns:
            conn.execute("ALTER TABLE action_queue ADD COLUMN admin_acknowledged_at TEXT")
        if "admin_note" not in queue_columns:
            conn.execute("ALTER TABLE action_queue ADD COLUMN admin_note TEXT")
        for table in ("bosses", "minions", "weapons", "armor", "special_items"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "description" not in columns:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN description TEXT NOT NULL DEFAULT ''"
                )
        minion_columns = {row[1] for row in conn.execute("PRAGMA table_info(minions)")}
        for prefix in ("res", "weak"):
            for damage_type in ("blade", "blunt", "ballistic", "energy", "arcane", "explosive", "venom"):
                column = f"{prefix}_{damage_type}"
                if column not in minion_columns:
                    conn.execute(
                        f"ALTER TABLE minions ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
                    )
        master_columns = {row[1] for row in conn.execute("PRAGMA table_info(master)")}
        if "protagonist_description" not in master_columns:
            conn.execute("ALTER TABLE master ADD COLUMN protagonist_description TEXT")
        for column, declaration in (
            ("layer_name", "TEXT"),
            ("tile_number", "INTEGER"),
            ("hex_q", "INTEGER"),
            ("hex_r", "INTEGER"),
            ("vehicle", "TEXT"),
        ):
            if column not in master_columns:
                conn.execute(f"ALTER TABLE master ADD COLUMN {column} {declaration}")
        conn.execute(
            """INSERT OR IGNORE INTO settings(constant_name,value,description)
               VALUES ('SUCCESSFUL_STEAL_XP','10',
                       'XP awarded whenever a combat steal attempt succeeds.')"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO settings(constant_name,value,description)
               VALUES ('COMBAT_DEFEAT_XP','10',
                       'Small XP award for losing a completed fight; escapes and stalemates excluded.')"""
        )
        # Adopt the hourly AP-trickle rule only for installations still using
        # the former stock 3 AP / 6 hour values. Administrator customizations
        # are deliberately preserved.
        conn.execute(
            """UPDATE settings SET value='1',
                   description='AP awarded to every non-banned character at each trickle.'
               WHERE constant_name='TRICKLE_AP_AMOUNT' AND CAST(value AS INTEGER)=3"""
        )
        conn.execute(
            """UPDATE settings SET value='1',
                   description='Hours between automatic AP trickle awards.'
               WHERE constant_name='TRICKLE_AP_INTERVAL_HOURS' AND CAST(value AS INTEGER)=6"""
        )
        # Balance revision: Brace retains its full defensive stance but heals
        # only 15% of missing HP. Update the former stock value while leaving
        # any deliberately customized administrator value untouched.
        conn.execute(
            """UPDATE settings SET value='0.15',
                   description='Fraction of missing HP restored when a character uses Brace.'
               WHERE constant_name='BRACE_HEAL_PERCENT'
                 AND ABS(CAST(value AS REAL) - 0.25) < 0.000001"""
        )
        # The original twenty-item daily rotation became unwieldy once
        # player-sold gear and specials were added. Migrate only the former
        # stock defaults; administrator-customized counts remain untouched.
        conn.execute(
            """UPDATE settings SET value='5'
               WHERE constant_name IN ('SHOP_WEAPONS_COUNT','SHOP_ARMOR_COUNT')
                 AND CAST(value AS INTEGER)=10"""
        )
        for name, value, description in (
            ("MINION_XP_PER_LEVEL", "20", "Base victory XP per minion level."),
            ("BOSS_XP_PER_LEVEL", "35", "Base victory XP per boss level."),
            ("PVP_XP_PER_LEVEL", "25", "Base victory XP per opposing player level."),
            ("NPC_UPGRADE_MIN_UNEQUIPPED", "2", "Unequipped gear required before an NPC may liquidate items for an upgrade."),
            ("NPC_UPGRADE_MIN_IMPROVEMENT", "0.15", "Minimum fractional NPC equipment-score improvement required for a planned upgrade."),
            ("NPC_OBSERVE_MAX_ATTEMPTS", "1", "Maximum Observe attempts an NPC may make during one combat."),
            ("NPC_RANDOM_WAKE_CHANCE", "0.003", "Chance per scheduler minute that an NPC takes an unscheduled action."),
            ("PERK_EFFECT_SCALE", "0.65", "Global multiplier applied to scalable perk bonuses; 0.65 reduces imported values by 35%."),
            ("AP_COST_WORLD_BOSS", "4", "AP required to begin one world-boss attempt."),
            ("AP_COST_SCENE", "2", "Fallback AP charge for a cinematic scene when its row does not specify one."),
            ("SCENES_PLAYER_ENABLED", "FALSE", "Feature gate for the cinematic scene player routes and navigation."),
            ("SCENE_ENEMY_HP_SCALE", "0.70", "HP multiplier used only by isolated cinematic scene enemies."),
            ("SCENE_ENEMY_DAMAGE_SCALE", "0.85", "Damage multiplier used only by isolated cinematic scene enemies."),
            ("SCENE_COMBAT_MAX_ROUNDS", "20", "Hard round cap used only by cinematic three-actor combat."),
            ("AP_COST_AUCTION", "1", "AP required to enter the player auction house."),
            ("WORLD_BOSS_HP_MULTIPLIER", "1.0", "Multiplier applied to imported world-boss HP."),
            ("WORLD_BOSS_ATTEMPT_XP", "10", "XP granted after a completed world-boss attempt."),
            ("WORLD_BOSS_ATTEMPT_CREDITS", "5", "Credits granted after a completed world-boss attempt."),
            ("WORLD_BOSS_XP_PER_DAMAGE", "1.0", "Additional world-boss attempt XP per point of actual shared-pool damage."),
            ("WORLD_BOSS_XP_PER_ROUND", "2.0", "Additional world-boss attempt XP per completed combat round."),
            ("WORLD_BOSS_CREDITS_PER_DAMAGE", "0.25", "Additional world-boss attempt credits per point of actual shared-pool damage."),
            ("WORLD_BOSS_CREDITS_PER_ROUND", "1.0", "Additional world-boss attempt credits per completed combat round."),
            ("WORLD_BOSS_REWARD_HOURS", "12", "Hours each placed player has to choose a prize."),
            ("SHOP_DAILY_VENDOR_CREDITS", "500", "Credits each character's shop vendor can spend on their direct sales per UTC day."),
            ("SHOP_PLAYER_SOLD_LISTING_CAP", "30", "Maximum player-sold listings retained by the Shop; the oldest player-sold stock expires first."),
            ("SHOP_SPECIAL_COUNT", "2", "Maximum unique specials placed in each normal Shop rotation."),
            ("TAVERN_CREDITS_PER_HP", "2", "Credits charged for each HP purchased from the Tavern."),
            ("TAVERN_MIN_COST", "5", "Minimum credit price for any Tavern treatment."),
            ("INVENTORY_STR_DIVISOR", "3", "Effective STR required for each additional inventory slot."),
            ("BOARD_FEATURE_ENABLED", "FALSE", "Dormant feature gate for the future hex game board."),
            ("INTERRUPTION_LUCK_DC", "15", "Luck-check difficulty after an action interruption; success produces a protagonist encounter and failure produces a minion."),
            ("PROTAGONIST_ENCOUNTER_XP_PER_LEVEL", "10", "Base XP awarded per player level by a friendly protagonist interruption."),
            ("PROTAGONIST_ENCOUNTER_CREDITS_BASE", "15", "Flat credits included in a friendly protagonist interruption reward."),
            ("PROTAGONIST_ENCOUNTER_CREDITS_PER_LEVEL", "10", "Additional credits per player level in a friendly protagonist interruption reward."),
            ("ENCOUNTER_MAX_LEVEL_ABOVE", "7", "Highest boss or interruption-minion level permitted above the encountering character."),
        ):
            conn.execute(
                "INSERT OR IGNORE INTO settings(constant_name,value,description) VALUES(?,?,?)",
                (name, value, description)
            )
        # Adopt the approved restrictive baseline only when the installation
        # still carries the former stock value.
        conn.execute(
            """UPDATE settings SET value='6',
                   description='Base inventory slots before effective STR scaling.'
               WHERE constant_name='INVENTORY_LIMIT' AND CAST(value AS INTEGER)=10"""
        )
        # Older builds recorded permanent level choices in level_up_history but
        # did not publish them to the player's dashboard feed. Backfill each
        # historical choice once, keyed by player and original timestamp.
        conn.execute(
            """INSERT INTO daily_feed
               (feed_scope, player_id, flavor_text, event_category, occurred_at)
               SELECT 'PERSONAL', l.player_id,
                      p.character_name || ' reached Level ' || l.level_reached ||
                      ' and increased ' ||
                      CASE l.stat_increased
                          WHEN 'STR' THEN 'Strength'
                          WHEN 'END' THEN 'Endurance'
                          WHEN 'AGI' THEN 'Agility'
                          WHEN 'LCK' THEN 'Luck'
                          WHEN 'PER' THEN 'Perception'
                          ELSE l.stat_increased
                      END || ' by 1.',
                      'LEVEL_UP', l.timestamp
               FROM level_up_history l
               JOIN players p ON p.id = l.player_id
               WHERE NOT EXISTS (
                   SELECT 1 FROM daily_feed d
                   WHERE d.player_id = l.player_id
                     AND d.event_category = 'LEVEL_UP'
                     AND d.occurred_at = l.timestamp
               )"""
        )
        conn.execute(
            "UPDATE random_events SET is_active = 0 WHERE effect_type = 'XP_LOSS'"
        )
        # Older builds counted only selected PvP outcomes on the shame board.
        # Reconstruct historical 1-HP defeats once from combat starting HP and
        # accumulated damage; future defeats increment at finalization time.
        if not conn.execute(
            "SELECT 1 FROM settings WHERE constant_name='SHAME_STATS_REBUILT_V2'"
        ).fetchone():
            conn.execute(
                """UPDATE player_stats SET times_reduced_to_1hp=(
                       SELECT COUNT(*) FROM combat_sessions cs
                       WHERE cs.result='1HP_WIN' AND (
                           (cs.attacker_player_id=player_stats.player_id
                            AND cs.defender_total_damage_dealt>=cs.attacker_hp_start-1)
                           OR
                           (cs.defender_player_id=player_stats.player_id
                            AND cs.attacker_total_damage_dealt>=cs.defender_hp_start-1)
                       )
                   )"""
            )
            conn.execute(
                """INSERT INTO settings(constant_name,value,description)
                   VALUES('SHAME_STATS_REBUILT_V2','TRUE',
                          'Marker for the one-time all-encounter defeat-stat reconstruction.')"""
            )
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
    if db.in_transaction:
        savepoint = f"nested_{uuid.uuid4().hex}"
        db.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
            db.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            db.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        return

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


def reconcile_combat_state(player_id: int | None = None) -> dict:
    """Repair invalid combat/session relationships without ending valid fights.

    A valid ACTIVE session is authoritative. Player flags are synchronized to
    it; broken references and duplicate older sessions are abandoned, logged,
    and cleaned so no character can remain trapped by inconsistent state.
    """
    scope_sql = "" if player_id is None else \
        "AND (cs.attacker_player_id=? OR cs.defender_player_id=?)"
    params = () if player_id is None else (player_id, player_id)
    active = execute(
        f"""SELECT cs.*,att.id AS attacker_exists,att.is_banned AS attacker_banned,
                   def.id AS defender_exists,def.is_banned AS defender_banned,
                   bi.id AS boss_instance_exists,mi.id AS minion_instance_exists,
                   wbe.id AS world_boss_event_exists,wbe.status AS world_boss_event_status
            FROM combat_sessions cs
            LEFT JOIN players att ON att.id=cs.attacker_player_id
            LEFT JOIN players def ON def.id=cs.defender_player_id
            LEFT JOIN boss_instances bi ON bi.id=cs.boss_instance_id
            LEFT JOIN minion_instances mi ON mi.id=cs.minion_instance_id
            LEFT JOIN world_boss_events wbe ON wbe.id=cs.world_boss_event_id
            WHERE cs.status='ACTIVE' {scope_sql}
            ORDER BY cs.id DESC""", params
    )
    claimed_players = set()
    abandoned = []
    valid_ids = []
    for combat in active:
        participants = [combat["attacker_player_id"]]
        if combat.get("defender_player_id"):
            participants.append(combat["defender_player_id"])
        broken = (not combat.get("attacker_exists") or combat.get("attacker_banned") or
                  (combat["combat_type"] == "PVP" and
                   (not combat.get("defender_exists") or combat.get("defender_banned"))) or
                  (combat["combat_type"] == "BOSS" and not combat.get("boss_instance_exists")) or
                  (combat["combat_type"] == "MINION" and not combat.get("minion_instance_exists")))
        if combat["combat_type"] == "WORLD_BOSS" and (
                not combat.get("world_boss_event_exists") or
                combat.get("world_boss_event_status") != "ACTIVE"):
            broken = True
        duplicate = any(pid in claimed_players for pid in participants)
        if broken or duplicate:
            abandoned.append((combat, "BROKEN_REFERENCE" if broken else "DUPLICATE_ACTIVE_COMBAT"))
        else:
            valid_ids.append(combat["id"])
            claimed_players.update(participants)

    # This runs before every authenticated request, including frequent feed
    # polls. Avoid an exclusive SQLite lock just to rewrite a correct flag;
    # long NPC turns may legitimately hold the single writer lock.
    flag_needs_update = True
    if player_id is not None:
        flag_row = execute_one(
            "SELECT in_combat,in_scene_combat FROM players WHERE id=?", (player_id,)
        )
        desired_flag = bool(
            flag_row and (flag_row.get("in_scene_combat") or player_id in claimed_players)
        )
        flag_needs_update = bool(
            flag_row and bool(flag_row.get("in_combat")) != desired_flag
        )
        if not abandoned and not flag_needs_update:
            return {"valid_active": len(valid_ids), "abandoned": 0}

    now = datetime.utcnow().isoformat()
    with exclusive_transaction():
        for combat, reason in abandoned:
            execute_write(
                """UPDATE combat_sessions SET status='ABANDONED',result=?,resolved_at=?
                   WHERE id=? AND status='ACTIVE'""",
                (reason, now, combat["id"])
            )
            execute_write("DELETE FROM combat_buffs WHERE combat_session_id=?", (combat["id"],))
            if combat.get("boss_instance_id") and combat.get("boss_instance_exists"):
                execute_write(
                    """UPDATE boss_instances SET current_hp=(SELECT max_hp FROM bosses WHERE id=boss_id),
                       special_attack_used=0,special_buff_used=0,current_phase=1 WHERE id=?""",
                    (combat["boss_instance_id"],)
                )
            if combat.get("minion_instance_id") and combat.get("minion_instance_exists"):
                execute_write(
                    """UPDATE minion_instances SET current_hp=(SELECT max_hp FROM minions WHERE id=minion_id)
                       WHERE id=?""", (combat["minion_instance_id"],)
                )
            for pid in {combat.get("attacker_player_id"), combat.get("defender_player_id")} - {None}:
                execute_write(
                    """INSERT INTO player_activity_log
                       (player_id,category,action,status,message,details_json,source)
                       VALUES(?,'SYSTEM','combat_recovery','SUCCESS',?,?,'SYSTEM')""",
                    (pid, f"Recovered invalid combat #{combat['id']} ({reason}).",
                     '{"combat_id": %d, "reason": "%s"}' % (combat["id"], reason))
                )
        if player_id is None:
            execute_write(
                """UPDATE players SET in_combat=CASE WHEN in_scene_combat=1 OR EXISTS(
                       SELECT 1 FROM combat_sessions cs WHERE cs.status='ACTIVE'
                       AND (cs.attacker_player_id=players.id OR cs.defender_player_id=players.id)
                   ) THEN 1 ELSE 0 END"""
            )
        elif flag_needs_update:
            execute_write(
                """UPDATE players SET in_combat=CASE WHEN in_scene_combat=1 OR EXISTS(
                       SELECT 1 FROM combat_sessions cs WHERE cs.status='ACTIVE'
                       AND (cs.attacker_player_id=players.id OR cs.defender_player_id=players.id)
                   ) THEN 1 ELSE 0 END WHERE id=?""", (player_id,)
            )
    if abandoned:
        logger.warning("Recovered %d invalid active combat session(s)", len(abandoned))
    return {"valid_active": len(valid_ids), "abandoned": len(abandoned)}


def get_player(player_id: int) -> dict | None:
    """Load player row with all derived computed fields attached.
    Called by context processor on every request."""
    player = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))
    if player is None:
        return None

    active_effects = execute(
        "SELECT effect_type, value FROM status_effects WHERE player_id = ?", (player_id,)
    )
    is_cursed = any(e["effect_type"] == "CURSED" for e in active_effects)
    modifiers = {"str": 0, "end": 0, "agi": 0, "lck": 0, "per": 0, "initiative": 0}
    names = {
        "STR": "str", "END": "end", "AGI": "agi", "LCK": "lck",
        "PER": "per", "INITIATIVE": "initiative",
    }
    for effect in active_effects:
        parts = effect["effect_type"].split("_")
        if len(parts) == 3 and parts[0] == "STAT" and parts[2] in names:
            modifiers[names[parts[2]]] += int(effect["value"])
    for column, key in (("str_stat", "str"), ("end_stat", "end"),
                        ("agi_stat", "agi"), ("lck_stat", "lck"),
                        ("per_stat", "per")):
        player[column] = max(1, player[column] + modifiers[key])
    player["initiative_modifier"] = modifiers["initiative"]
    settings = get_all_settings()

    inactive_days  = settings.get("INACTIVE_DAYS_THRESHOLD",  cfg.INACTIVE_DAYS_THRESHOLD)

    equipped = get_player_equipped(player)
    gear_str = sum(int((equipped.get(slot) or {}).get("str_bonus", 0) or 0)
                   for slot in ("weapon", "armor"))
    gear_end = sum(int((equipped.get(slot) or {}).get("end_bonus", 0) or 0)
                   for slot in ("weapon", "armor"))
    special = get_player_bonus_profile(player_id, equipped.get("specials", []))
    end   = player["end_stat"] + gear_end + int(special.get("end_bonus", 0))
    effective_str = player["str_stat"] + gear_str + int(special.get("str_bonus", 0))
    level = player["level"]

    max_hp     = calculate_max_hp(level, end, settings)
    ap_result  = calculate_daily_ap(
        end, int(special.get("bonus_ap", 0) or 0), is_cursed, settings
    )
    max_ap     = ap_result["effective"]
    inv_limit  = inventory_capacity(effective_str, settings)
    passive_regen = calculate_passive_regen(
        end, int(special.get("hp_regen_bonus", 0) or 0), settings
    )

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

    next_level_xp = cfg.XP_CURVE.get(level + 1)
    xp_to_next_level = (max(0, next_level_xp - player["xp"])
                        if next_level_xp is not None else None)

    player.update({
        "max_hp":            max_hp,
        "max_ap":            max_ap,
        "raw_max_ap":        ap_result["raw"],
        "is_ap_capped":      ap_result["is_capped"],
        "inventory_limit":   inv_limit,
        "inventory_count":   inv_count,
        "is_overencumbered": inv_count > inv_limit,
        "is_cursed":         is_cursed,
        "is_inactive":       is_inactive,
        "passive_regen":     passive_regen,
        "hp_tier":           hp_tier,
        "hp_pct":            round(hp_pct, 1),
        "next_level_xp":     next_level_xp,
        "xp_to_next_level":  xp_to_next_level,
    })
    return player


def clamp_player_hp_to_max(player_id: int) -> dict | None:
    """Clamp current HP after a loadout reduces END; never inflict defeat."""
    player = get_player(player_id)
    if not player:
        return None
    clamped_hp = max(1, min(int(player["current_hp"]), int(player["max_hp"])))
    if clamped_hp != player["current_hp"]:
        with exclusive_transaction():
            execute_write(
                "UPDATE players SET current_hp=? WHERE id=?",
                (clamped_hp, player_id),
            )
        player["current_hp"] = clamped_hp
    return {"current_hp": clamped_hp, "max_hp": player["max_hp"]}


BONUS_FIELDS = (
    "str_bonus", "end_bonus", "agi_bonus", "lck_bonus", "per_bonus",
    "initiative_bonus", "extra_attack", "crit_chance_bonus",
    "crit_dmg_multiplier", "ac_bonus", "res_blade", "res_blunt",
    "res_ballistic", "res_energy", "res_arcane", "res_explosive",
    "res_venom", "bonus_damage_amount", "xp_multiplier",
    "credit_multiplier", "steal_bonus", "bonus_ap", "hp_regen_bonus",
    "durability_reduction", "shop_discount", "sell_bonus", "encounter_bonus",
    "observe_bonus",
)


def get_player_perks(player_id: int) -> list[dict]:
    """Return a character's permanent perks in acquisition order."""
    return [scale_perk_effects(perk) for perk in execute(
        """SELECT p.*,pp.level_chosen,pp.acquired_at
           FROM player_perks pp JOIN perks p ON p.id=pp.perk_id
           WHERE pp.player_id=? ORDER BY pp.level_chosen,p.id""", (player_id,)
    )]


def scale_perk_effects(perk: dict) -> dict:
    """Scale perk magnitudes consistently while preserving binary abilities."""
    result = dict(perk)
    scale = max(0.0, float(get_all_settings().get(
        "PERK_EFFECT_SCALE", cfg.PERK_EFFECT_SCALE
    )))
    integer_fields = {
        "str_bonus", "end_bonus", "agi_bonus", "lck_bonus", "per_bonus",
        "initiative_bonus", "ac_bonus", "bonus_damage_amount", "bonus_ap",
        "hp_regen_bonus",
    }
    fractional_fields = {
        "crit_chance_bonus", "crit_dmg_multiplier", "xp_multiplier",
        "credit_multiplier", "steal_bonus", "durability_reduction",
        "shop_discount", "sell_bonus", "encounter_bonus",
    }
    for field in integer_fields:
        result[field] = int(round(float(result.get(field, 0) or 0) * scale))
    # Permanent core-stat perks should be meaningful without overwhelming
    # level-up choices, equipment, Armor Class, attack rolls, or derived HP/AP.
    for field in ("str_bonus", "end_bonus", "agi_bonus", "lck_bonus", "per_bonus"):
        result[field] = max(-5, min(5, result[field]))
    for field in fractional_fields:
        result[field] = round(float(result.get(field, 0) or 0) * scale, 6)

    # Per-effect balance ceilings. These are deliberately applied after the
    # global scale so future content imports cannot accidentally restore the
    # original oversized combat and economy bonuses.
    integer_caps = {
        "initiative_bonus": 5,
        "ac_bonus": 4,
        "bonus_damage_amount": 5,
        "bonus_ap": 3,
        "hp_regen_bonus": 2,
    }
    fractional_caps = {
        "crit_chance_bonus": 0.10,
        "crit_dmg_multiplier": 0.25,
        "xp_multiplier": 0.25,
        "credit_multiplier": 0.25,
        "steal_bonus": 0.15,
        "durability_reduction": 0.25,
        "shop_discount": 0.20,
        "sell_bonus": 0.20,
        "encounter_bonus": 0.20,
    }
    for field, ceiling in integer_caps.items():
        result[field] = max(-ceiling, min(ceiling, result[field]))
    for field, ceiling in fractional_caps.items():
        result[field] = max(-ceiling, min(ceiling, result[field]))
    return result


def get_player_perk_bonuses(player_id: int) -> dict:
    """Aggregate all permanent perk effects, retaining typed damage components."""
    perks = get_player_perks(player_id)
    result = {field: 0 for field in BONUS_FIELDS}
    components = []
    for perk in perks:
        for field in BONUS_FIELDS:
            result[field] += float(perk.get(field, 0) or 0)
        if perk.get("bonus_damage_amount") and perk.get("bonus_damage_type"):
            components.append({"type": perk["bonus_damage_type"],
                               "amount": int(perk["bonus_damage_amount"])})
    for field in ("str_bonus", "end_bonus", "agi_bonus", "lck_bonus", "per_bonus",
                  "initiative_bonus", "extra_attack", "ac_bonus", "bonus_damage_amount",
                  "bonus_ap", "hp_regen_bonus", "res_blade", "res_blunt",
                  "res_ballistic", "res_energy", "res_arcane", "res_explosive", "res_venom"):
        result[field] = int(result[field])
    result["bonus_damage_components"] = components
    return result


_LOAD_EQUIPPED_SPECIAL = object()


def get_player_bonus_profile(player_id: int, special=_LOAD_EQUIPPED_SPECIAL) -> dict:
    """Combine unlocked equipped specials, class passives, and permanent perks."""
    if special is _LOAD_EQUIPPED_SPECIAL:
        player = execute_one("SELECT * FROM players WHERE id=?", (player_id,)) or {}
        special = []
        for inv_id in equipped_special_ids(player):
            row = execute_one(
                """SELECT s.* FROM inventory_items ii JOIN special_items s ON s.id=ii.item_id
                   WHERE ii.id=? AND ii.player_id=?""", (inv_id, player_id)
            )
            if row:
                special.append(row)
    specials = special if isinstance(special, (list, tuple)) else ([special] if special else [])
    result = {field: 0 for field in BONUS_FIELDS}
    for item in specials:
        for field in BONUS_FIELDS:
            result[field] += float(item.get(field, 0) or 0)
    class_row = execute_one(
        """SELECT c.* FROM players p LEFT JOIN classes c ON c.id=p.class_id WHERE p.id=?""",
        (player_id,),
    ) or {}
    for field in BONUS_FIELDS:
        # Core class attributes were permanently applied at creation and must
        # not be counted a second time here.
        if field not in ("str_bonus", "end_bonus", "agi_bonus", "lck_bonus", "per_bonus"):
            result[field] += float(class_row.get(field, 0) or 0)
    perk = get_player_perk_bonuses(player_id)
    for field in BONUS_FIELDS:
        result[field] += float(perk.get(field, 0) or 0)
    components = []
    for item in specials:
        if item.get("bonus_damage_amount") and item.get("bonus_damage_type"):
            components.append({"type": item["bonus_damage_type"],
                               "amount": int(item["bonus_damage_amount"])})
    if class_row.get("bonus_damage_amount"):
        components.append({"type": class_row.get("bonus_damage_type") or "Weapon",
                           "amount": int(class_row["bonus_damage_amount"])})
    components.extend(perk.get("bonus_damage_components", []))
    result["bonus_damage_components"] = components
    result["equipped_specials"] = specials
    result["class_name"] = class_row.get("name")
    return result


def get_player_equipped(player: dict) -> dict:
    """Load full weapon, armor, and special item rows for a player's equipped gear.
    Returns {'weapon': dict|None, 'armor': dict|None, 'special': dict|None}"""
    result = {"weapon": None, "armor": None, "special": None, "specials": []}
    for slot, col, table in [
        ("weapon",  "equipped_weapon_id",  "weapons"),
        ("armor",   "equipped_armor_id",   "armor"),
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
    for inv_id in equipped_special_ids(player):
        inv_row = execute_one("SELECT * FROM inventory_items WHERE id=?", (inv_id,))
        if inv_row:
            content = execute_one("SELECT * FROM special_items WHERE id=?", (inv_row["item_id"],))
            if content:
                result["specials"].append({**content, "inv_id": inv_id,
                    "current_durability": inv_row["current_durability"]})
    result["special"] = result["specials"][0] if result["specials"] else None
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
