################################################################################
# PHASE 1 CODE — Foundation
# BBS-Inspired Multiplayer Dueling Game
#
# Files included (in order):
#   1. config_defaults.py
#   2. schema.sql
#   3. database.py
#   4. queue_handler.py
#   5. app.py
#   6. scheduler.py
#
# Each file is clearly delimited below.
# Place each file at the project root unless otherwise noted.
# Directory structure expected:
#   game/
#   ├── config_defaults.py
#   ├── schema.sql
#   ├── database.py
#   ├── queue_handler.py
#   ├── app.py
#   ├── scheduler.py
#   └── data/               (auto-created by init_db())
#       ├── game.db
#       ├── pending_import.xlsx  (staged by admin when ready)
#       └── logs/
#
# Dependencies (pip install):
#   flask
#   apscheduler
#   openpyxl       (used in Phase 7 importer)
#
# To run in development:
#   export FLASK_APP=app:create_app
#   flask run
################################################################################


################################################################################
# FILE: config_defaults.py
################################################################################

# config_defaults.py
# Hardcoded fallback constants. database.get_setting() tries the settings DB
# table first, falls back here if the row is missing, and logs a warning.
# Deployment constants (paths, secret key) live here only — never in the DB.

import os

# ── Deployment constants (never in DB) ───────────────────────────────────────
PENDING_IMPORT_PATH      = "data/pending_import.xlsx"
REJECTED_IMPORT_PATH     = "data/logs/rejected/"
IMPORT_ERROR_LOG         = "data/logs/import_errors.log"
ORPHAN_LOG               = "data/logs/orphan_actions.log"
DB_PATH                  = "data/game.db"
TERMINAL_HISTORY_ENTRIES = 20
SECRET_KEY               = os.environ.get("GAME_SECRET_KEY", "dev-secret-change-in-production")

# ── Game constants (fallbacks if row missing from settings table) ─────────────
BASE_DAILY_AP                          = 20
AP_CARRYOVER_CAP                       = 40
AP_COST_BOSS                           = 3
AP_COST_PVP                            = 3
AP_COST_TAVERN                         = 2
AP_COST_BLACKSMITH                     = 2
AP_COST_SHOP                           = 1
AP_COST_ESCAPE                         = 1
TRICKLE_AP_AMOUNT                      = 3
TRICKLE_AP_INTERVAL_HOURS              = 6
COMBAT_EXTENSION_TIMEOUT               = 20
MIDNIGHT_BLACKOUT_MINUTES              = 10
STARTING_CREDITS                       = 25
STARTING_STAT_POINTS                   = 10
BASE_HP                                = 10
HP_PER_LEVEL                           = 5
END_HP_REGEN_DIVISOR                   = 2
TAVERN_HEAL_COST                       = 15
TAVERN_HEAL_PERCENT                    = 0.50
BRACE_HEAL_PERCENT                     = 0.25
BRACE_AC_BONUS_PERCENT                 = 0.25
BRACE_DODGE_BONUS                      = 5
MIDNIGHT_HEAL_PERCENT                  = 0.50
REPAIR_BASE_PERCENT                    = 0.50
REPAIR_LCK_MULTIPLIER                  = 2
REPAIR_LCK_CAP                         = 0.75
REPAIR_COST_PERCENT                    = 0.25
COMBAT_ROUNDS_DEFAULT                  = 4
COMBAT_ROUNDS_EXTENSION                = 4
COMBAT_WIN_HP_WEIGHT                   = 0.40
COMBAT_WIN_DMG_WEIGHT                  = 0.60
CREDIT_STEAL_PERCENT                   = 0.10
CREDIT_STEAL_LUCK_MULTIPLIER           = 2
ZERO_CREDIT_XP_BONUS                   = 25
STEAL_ACTION_CREDIT_PERCENT            = 0.20
STEAL_BOSS_CREDIT_MULTIPLIER           = 20
STEAL_SPECIAL_BASE_CHANCE              = 0.03
ESCAPE_CREDIT_DROP_CHANCE              = 0.10
INVENTORY_LIMIT                        = 10
OVERENCUMBERED_AP_MULTIPLIER           = 2
OVERENCUMBERED_AC_PENALTY              = 3
OVERENCUMBERED_ATTACK_PENALTY          = 3
SWAP_GEAR_ACCURACY_PENALTY             = 0.30
SWAP_GEAR_AC_PENALTY                   = 0.30
SHOP_WEAPONS_COUNT                     = 10
SHOP_ARMOR_COUNT                       = 10
SHOP_DISCOUNT_MAX                      = 0.50
RANDOM_EVENT_BASE_CHANCE               = 0.20
RANDOM_EVENT_MAX_CHANCE                = 0.60
RANDOM_EVENT_GOOD_BASE                 = 0.50
RANDOM_EVENT_GOOD_MAX                  = 0.90
RANDOM_EVENT_BAD_MIN                   = 0.10
RANDOM_EVENT_LCK_BONUS                 = 0.05
AP_PASSIVE_HP_REGEN                    = 1
CRIT_BASE_THRESHOLD                    = 20
CRIT_LCK_DIVISOR                       = 5
CRIT_MIN_THRESHOLD                     = 15
RESISTANCE_STACK_MIN_DAMAGE_PERCENT    = 0.25
XP_LOSS_DIVISOR                        = 3
SELL_PRICE_PERCENT                     = 0.50
COMBAT_PREF_BALANCED_SPLIT             = 0.50
COMBAT_PREF_OPPORTUNIST_SPLIT          = 0.50
WEALTH_TIER_POOR_MAX                   = 0.33
WEALTH_TIER_MIDDLE_MAX                 = 0.66
INACTIVE_DAYS_THRESHOLD                = 7
MINION_ENCOUNTER_CHANCE                = 0.50
CURSE_AP_REDUCTION                     = 0.20
SPECIAL_ITEM_DURABILITY_LOSS_PER_ROUND = 0.02
BOSS_LEVEL_WARNING_THRESHOLD           = 3
LOG_DAILY_ARCHIVE                      = False
LOG_ARCHIVE_PATH                       = "data/logs/daily/"

XP_CURVE = {
    2: 100,   3: 250,   4: 500,   5: 900,
    6: 1400,  7: 2000,  8: 2700,  9: 3500,
    10: 4400, 11: 5500, 12: 7000, 13: 9000,
    14: 12000, 15: 16000
}

# ── Type coercion helpers used by database.get_setting() ─────────────────────
SETTING_TYPES = {
    "BASE_DAILY_AP": int, "AP_CARRYOVER_CAP": int, "AP_COST_BOSS": int,
    "AP_COST_PVP": int, "AP_COST_TAVERN": int, "AP_COST_BLACKSMITH": int,
    "AP_COST_SHOP": int, "AP_COST_ESCAPE": int, "TRICKLE_AP_AMOUNT": int,
    "TRICKLE_AP_INTERVAL_HOURS": int, "COMBAT_EXTENSION_TIMEOUT": int,
    "MIDNIGHT_BLACKOUT_MINUTES": int, "STARTING_CREDITS": int,
    "STARTING_STAT_POINTS": int, "BASE_HP": int, "HP_PER_LEVEL": int,
    "END_HP_REGEN_DIVISOR": int, "TAVERN_HEAL_COST": int,
    "BRACE_DODGE_BONUS": int, "REPAIR_LCK_MULTIPLIER": int,
    "COMBAT_ROUNDS_DEFAULT": int, "COMBAT_ROUNDS_EXTENSION": int,
    "CREDIT_STEAL_LUCK_MULTIPLIER": int, "ZERO_CREDIT_XP_BONUS": int,
    "STEAL_BOSS_CREDIT_MULTIPLIER": int, "INVENTORY_LIMIT": int,
    "OVERENCUMBERED_AP_MULTIPLIER": int, "OVERENCUMBERED_AC_PENALTY": int,
    "OVERENCUMBERED_ATTACK_PENALTY": int, "SHOP_WEAPONS_COUNT": int,
    "SHOP_ARMOR_COUNT": int, "AP_PASSIVE_HP_REGEN": int,
    "CRIT_BASE_THRESHOLD": int, "CRIT_LCK_DIVISOR": int,
    "CRIT_MIN_THRESHOLD": int, "XP_LOSS_DIVISOR": int,
    "INACTIVE_DAYS_THRESHOLD": int, "BOSS_LEVEL_WARNING_THRESHOLD": int,
    "TERMINAL_HISTORY_ENTRIES": int,
    "TAVERN_HEAL_PERCENT": float, "BRACE_HEAL_PERCENT": float,
    "BRACE_AC_BONUS_PERCENT": float, "MIDNIGHT_HEAL_PERCENT": float,
    "REPAIR_BASE_PERCENT": float, "REPAIR_LCK_CAP": float,
    "REPAIR_COST_PERCENT": float, "COMBAT_WIN_HP_WEIGHT": float,
    "COMBAT_WIN_DMG_WEIGHT": float, "CREDIT_STEAL_PERCENT": float,
    "STEAL_ACTION_CREDIT_PERCENT": float, "STEAL_SPECIAL_BASE_CHANCE": float,
    "ESCAPE_CREDIT_DROP_CHANCE": float, "SWAP_GEAR_ACCURACY_PENALTY": float,
    "SWAP_GEAR_AC_PENALTY": float, "SHOP_DISCOUNT_MAX": float,
    "RANDOM_EVENT_BASE_CHANCE": float, "RANDOM_EVENT_MAX_CHANCE": float,
    "RANDOM_EVENT_GOOD_BASE": float, "RANDOM_EVENT_GOOD_MAX": float,
    "RANDOM_EVENT_BAD_MIN": float, "RANDOM_EVENT_LCK_BONUS": float,
    "RESISTANCE_STACK_MIN_DAMAGE_PERCENT": float, "SELL_PRICE_PERCENT": float,
    "COMBAT_PREF_BALANCED_SPLIT": float, "COMBAT_PREF_OPPORTUNIST_SPLIT": float,
    "WEALTH_TIER_POOR_MAX": float, "WEALTH_TIER_MIDDLE_MAX": float,
    "MINION_ENCOUNTER_CHANCE": float, "CURSE_AP_REDUCTION": float,
    "SPECIAL_ITEM_DURABILITY_LOSS_PER_ROUND": float,
    "LOG_DAILY_ARCHIVE": bool,
}


################################################################################
# FILE: schema.sql
# Place at project root alongside the Python files.
# Executed by database.init_db() — safe to re-run (uses IF NOT EXISTS).
################################################################################

SCHEMA_SQL = '''
-- schema.sql
-- Full database schema. Executed by database.init_db().
-- All tables use IF NOT EXISTS — safe to re-run on an existing DB.

-- ─────────────────────────────────────────────────────────────────────────────
-- PLAYERS & IDENTITY
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS players (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT    UNIQUE NOT NULL,
    password_hash       TEXT    NOT NULL,
    email               TEXT    UNIQUE NOT NULL,
    character_name      TEXT    NOT NULL,
    sex                 TEXT    NOT NULL,
    class_id            INTEGER REFERENCES classes(id),
    str_stat            INTEGER NOT NULL DEFAULT 1,
    end_stat            INTEGER NOT NULL DEFAULT 1,
    agi_stat            INTEGER NOT NULL DEFAULT 1,
    lck_stat            INTEGER NOT NULL DEFAULT 1,
    per_stat            INTEGER NOT NULL DEFAULT 1,
    level               INTEGER NOT NULL DEFAULT 1,
    xp                  INTEGER NOT NULL DEFAULT 0,
    current_hp          INTEGER NOT NULL,
    current_ap          INTEGER NOT NULL,
    credits             INTEGER NOT NULL DEFAULT 25,
    equipped_weapon_id  INTEGER REFERENCES inventory_items(id),
    equipped_armor_id   INTEGER REFERENCES inventory_items(id),
    equipped_special_id INTEGER REFERENCES inventory_items(id),
    in_combat           INTEGER NOT NULL DEFAULT 0,
    pending_levelup     INTEGER NOT NULL DEFAULT 0,
    combat_preference   TEXT    NOT NULL DEFAULT "Balanced",
    is_banned           INTEGER NOT NULL DEFAULT 0,
    last_login_at       TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS player_stats (
    player_id            INTEGER PRIMARY KEY REFERENCES players(id),
    pvp_kills            INTEGER NOT NULL DEFAULT 0,
    times_reduced_to_1hp INTEGER NOT NULL DEFAULT 0,
    updated_at           TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS level_up_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id      INTEGER NOT NULL REFERENCES players(id),
    level_reached  INTEGER NOT NULL,
    stat_increased TEXT    NOT NULL,
    timestamp      TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS status_effects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    effect_type TEXT    NOT NULL,
    value       REAL    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS combat_buffs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    combat_session_id INTEGER NOT NULL REFERENCES combat_sessions(id),
    side              TEXT    NOT NULL,
    buff_type         TEXT    NOT NULL,
    damage_type       TEXT,
    value             REAL    NOT NULL,
    expires_on        TEXT    NOT NULL,
    created_at        TEXT    NOT NULL DEFAULT (datetime("now"))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- COMBAT
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS combat_sessions (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    combat_type                 TEXT    NOT NULL,
    attacker_player_id          INTEGER NOT NULL REFERENCES players(id),
    defender_player_id          INTEGER REFERENCES players(id),
    boss_instance_id            INTEGER REFERENCES boss_instances(id),
    minion_instance_id          INTEGER REFERENCES minion_instances(id),
    status                      TEXT    NOT NULL DEFAULT "ACTIVE",
    result                      TEXT,
    current_round               INTEGER NOT NULL DEFAULT 1,
    rounds_extended             INTEGER NOT NULL DEFAULT 0,
    attacker_hp_start           INTEGER NOT NULL,
    defender_hp_start           INTEGER,
    attacker_total_damage_dealt INTEGER NOT NULL DEFAULT 0,
    defender_total_damage_dealt INTEGER NOT NULL DEFAULT 0,
    attacker_observed           INTEGER NOT NULL DEFAULT 0,
    defender_observed           INTEGER NOT NULL DEFAULT 0,
    started_at                  TEXT    NOT NULL DEFAULT (datetime("now")),
    resolved_at                 TEXT
);

CREATE TABLE IF NOT EXISTS boss_instances (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id           INTEGER NOT NULL REFERENCES players(id),
    boss_id             INTEGER NOT NULL REFERENCES bosses(id),
    current_hp          INTEGER NOT NULL,
    special_attack_used INTEGER NOT NULL DEFAULT 0,
    special_buff_used   INTEGER NOT NULL DEFAULT 0,
    current_phase       INTEGER NOT NULL DEFAULT 1,
    discovered_at       TEXT    NOT NULL DEFAULT (datetime("now")),
    kill_count          INTEGER NOT NULL DEFAULT 0,
    UNIQUE(player_id, boss_id)
);

CREATE TABLE IF NOT EXISTS minion_instances (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id     INTEGER NOT NULL REFERENCES players(id),
    minion_id     INTEGER NOT NULL REFERENCES minions(id),
    current_hp    INTEGER NOT NULL,
    discovered_at TEXT    NOT NULL DEFAULT (datetime("now")),
    kill_count    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(player_id, minion_id)
);

CREATE TABLE IF NOT EXISTS boss_intel (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id  INTEGER NOT NULL REFERENCES players(id),
    boss_id    INTEGER NOT NULL REFERENCES bosses(id),
    learned_at TEXT    NOT NULL DEFAULT (datetime("now")),
    UNIQUE(player_id, boss_id)
);

CREATE TABLE IF NOT EXISTS combat_logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    combat_session_id INTEGER NOT NULL REFERENCES combat_sessions(id),
    round_number      INTEGER NOT NULL,
    actor             TEXT    NOT NULL,
    action_type       TEXT    NOT NULL,
    roll_detail       TEXT    NOT NULL,
    outcome_detail    TEXT    NOT NULL,
    hp_after_attacker INTEGER,
    hp_after_defender INTEGER,
    created_at        TEXT    NOT NULL DEFAULT (datetime("now"))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- INVENTORY & ITEMS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS inventory_items (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id          INTEGER NOT NULL REFERENCES players(id),
    item_type          TEXT    NOT NULL,
    item_id            INTEGER NOT NULL,
    current_durability INTEGER NOT NULL DEFAULT 100,
    acquired_at        TEXT    NOT NULL DEFAULT (datetime("now")),
    acquired_method    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS item_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id         INTEGER NOT NULL REFERENCES players(id),
    item_type         TEXT    NOT NULL,
    item_id           INTEGER NOT NULL,
    item_name         TEXT    NOT NULL,
    event_type        TEXT    NOT NULL,
    credit_amount     INTEGER,
    related_player_id INTEGER REFERENCES players(id),
    occurred_at       TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS special_item_registry (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    special_item_id         INTEGER NOT NULL UNIQUE REFERENCES special_items(id),
    status                  TEXT    NOT NULL DEFAULT "IN_POOL",
    current_owner_player_id INTEGER REFERENCES players(id),
    inventory_item_id       INTEGER REFERENCES inventory_items(id),
    shop_listing_price      INTEGER,
    last_acquired_method    TEXT,
    last_released_method    TEXT,
    updated_at              TEXT    NOT NULL DEFAULT (datetime("now"))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- ECONOMY
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS shop_listings (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type             TEXT    NOT NULL,
    item_id               INTEGER NOT NULL,
    listing_source        TEXT    NOT NULL,
    seller_player_id      INTEGER REFERENCES players(id),
    durability_at_listing INTEGER,
    price                 INTEGER NOT NULL,
    listed_at             TEXT    NOT NULL DEFAULT (datetime("now"))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- FEEDS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS daily_feed (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_scope        TEXT    NOT NULL,
    player_id         INTEGER REFERENCES players(id),
    flavor_text       TEXT    NOT NULL,
    event_category    TEXT    NOT NULL,
    combat_session_id INTEGER REFERENCES combat_sessions(id),
    occurred_at       TEXT    NOT NULL DEFAULT (datetime("now"))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- QUEUE
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS action_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id    INTEGER NOT NULL REFERENCES players(id),
    action_type  TEXT    NOT NULL,
    payload      TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT "PROCESSING",
    created_at   TEXT    NOT NULL DEFAULT (datetime("now")),
    processed_at TEXT
);

-- ─────────────────────────────────────────────────────────────────────────────
-- CONTENT TABLES (Excel-imported)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS classes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    UNIQUE NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    str_bonus   INTEGER NOT NULL DEFAULT 0,
    end_bonus   INTEGER NOT NULL DEFAULT 0,
    agi_bonus   INTEGER NOT NULL DEFAULT 0,
    lck_bonus   INTEGER NOT NULL DEFAULT 0,
    per_bonus   INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    imported_at TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS bosses (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    name                        TEXT    UNIQUE NOT NULL,
    is_active                   INTEGER NOT NULL DEFAULT 1,
    level                       INTEGER NOT NULL,
    str_stat                    INTEGER NOT NULL,
    end_stat                    INTEGER NOT NULL,
    agi_stat                    INTEGER NOT NULL,
    lck_stat                    INTEGER NOT NULL,
    per_stat                    INTEGER NOT NULL,
    max_hp                      INTEGER NOT NULL,
    phase2_hp_percent           INTEGER NOT NULL,
    phase3_hp_percent           INTEGER NOT NULL,
    special_attack_name         TEXT    NOT NULL,
    special_attack_die          TEXT    NOT NULL,
    special_attack_damage_type  TEXT    NOT NULL,
    special_attack_flavor       TEXT    NOT NULL,
    special_buff_name           TEXT    NOT NULL,
    special_buff_type           TEXT    NOT NULL,
    special_buff_value          REAL    NOT NULL,
    special_buff_damage_type    TEXT,
    special_buff_flavor         TEXT    NOT NULL,
    res_blade     INTEGER NOT NULL DEFAULT 0,
    res_blunt     INTEGER NOT NULL DEFAULT 0,
    res_ballistic INTEGER NOT NULL DEFAULT 0,
    res_energy    INTEGER NOT NULL DEFAULT 0,
    res_arcane    INTEGER NOT NULL DEFAULT 0,
    res_explosive INTEGER NOT NULL DEFAULT 0,
    res_venom     INTEGER NOT NULL DEFAULT 0,
    weak_blade    INTEGER NOT NULL DEFAULT 0,
    weak_blunt    INTEGER NOT NULL DEFAULT 0,
    weak_ballistic INTEGER NOT NULL DEFAULT 0,
    weak_energy   INTEGER NOT NULL DEFAULT 0,
    weak_arcane   INTEGER NOT NULL DEFAULT 0,
    weak_explosive INTEGER NOT NULL DEFAULT 0,
    weak_venom    INTEGER NOT NULL DEFAULT 0,
    drop_weapon_chance       REAL    NOT NULL,
    drop_armor_chance        REAL    NOT NULL,
    drop_special_item_chance REAL    NOT NULL,
    drop_credit_min          INTEGER NOT NULL,
    drop_credit_max          INTEGER NOT NULL,
    flavor_text              TEXT    NOT NULL,
    imported_at              TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS minions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    UNIQUE NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    level         INTEGER NOT NULL,
    str_stat      INTEGER NOT NULL,
    end_stat      INTEGER NOT NULL,
    agi_stat      INTEGER NOT NULL,
    lck_stat      INTEGER NOT NULL,
    per_stat      INTEGER NOT NULL,
    max_hp        INTEGER NOT NULL,
    drop_weapon_chance       REAL    NOT NULL,
    drop_armor_chance        REAL    NOT NULL,
    drop_special_item_chance REAL    NOT NULL,
    drop_credit_min          INTEGER NOT NULL,
    drop_credit_max          INTEGER NOT NULL,
    flavor_text   TEXT    NOT NULL,
    imported_at   TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS weapons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    UNIQUE NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    level           INTEGER NOT NULL,
    weapon_type     TEXT    NOT NULL,
    damage_die      TEXT    NOT NULL,
    damage_type     TEXT    NOT NULL,
    str_bonus       INTEGER NOT NULL DEFAULT 0,
    end_bonus       INTEGER NOT NULL DEFAULT 0,
    agi_bonus       INTEGER NOT NULL DEFAULT 0,
    lck_bonus       INTEGER NOT NULL DEFAULT 0,
    per_bonus       INTEGER NOT NULL DEFAULT 0,
    associated_to   TEXT,
    credit_cost     INTEGER NOT NULL,
    drop_chance     REAL    NOT NULL,
    starting_durability INTEGER NOT NULL DEFAULT 100,
    imported_at     TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS armor (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    UNIQUE NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    level           INTEGER NOT NULL,
    ac_bonus        INTEGER NOT NULL DEFAULT 0,
    res_blade       INTEGER NOT NULL DEFAULT 0,
    res_blunt       INTEGER NOT NULL DEFAULT 0,
    res_ballistic   INTEGER NOT NULL DEFAULT 0,
    res_energy      INTEGER NOT NULL DEFAULT 0,
    res_arcane      INTEGER NOT NULL DEFAULT 0,
    res_explosive   INTEGER NOT NULL DEFAULT 0,
    res_venom       INTEGER NOT NULL DEFAULT 0,
    str_bonus       INTEGER NOT NULL DEFAULT 0,
    end_bonus       INTEGER NOT NULL DEFAULT 0,
    agi_bonus       INTEGER NOT NULL DEFAULT 0,
    lck_bonus       INTEGER NOT NULL DEFAULT 0,
    per_bonus       INTEGER NOT NULL DEFAULT 0,
    associated_to   TEXT,
    credit_cost     INTEGER NOT NULL,
    drop_chance     REAL    NOT NULL,
    starting_durability INTEGER NOT NULL DEFAULT 100,
    imported_at     TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS special_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    UNIQUE NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    associated_to   TEXT    NOT NULL,
    association_type TEXT   NOT NULL,
    str_bonus       INTEGER NOT NULL DEFAULT 0,
    end_bonus       INTEGER NOT NULL DEFAULT 0,
    agi_bonus       INTEGER NOT NULL DEFAULT 0,
    lck_bonus       INTEGER NOT NULL DEFAULT 0,
    per_bonus       INTEGER NOT NULL DEFAULT 0,
    initiative_bonus    INTEGER NOT NULL DEFAULT 0,
    extra_attack        INTEGER NOT NULL DEFAULT 0,
    crit_chance_bonus   REAL    NOT NULL DEFAULT 0,
    crit_dmg_multiplier REAL    NOT NULL DEFAULT 0,
    ac_bonus            INTEGER NOT NULL DEFAULT 0,
    res_blade       INTEGER NOT NULL DEFAULT 0,
    res_blunt       INTEGER NOT NULL DEFAULT 0,
    res_ballistic   INTEGER NOT NULL DEFAULT 0,
    res_energy      INTEGER NOT NULL DEFAULT 0,
    res_arcane      INTEGER NOT NULL DEFAULT 0,
    res_explosive   INTEGER NOT NULL DEFAULT 0,
    res_venom       INTEGER NOT NULL DEFAULT 0,
    bonus_damage_type   TEXT,
    bonus_damage_amount INTEGER NOT NULL DEFAULT 0,
    xp_multiplier       REAL    NOT NULL DEFAULT 0,
    credit_multiplier   REAL    NOT NULL DEFAULT 0,
    steal_bonus         REAL    NOT NULL DEFAULT 0,
    bonus_ap            INTEGER NOT NULL DEFAULT 0,
    hp_regen_bonus      INTEGER NOT NULL DEFAULT 0,
    durability_reduction REAL   NOT NULL DEFAULT 0,
    shop_discount       REAL    NOT NULL DEFAULT 0,
    sell_bonus          REAL    NOT NULL DEFAULT 0,
    encounter_bonus     REAL    NOT NULL DEFAULT 0,
    credit_cost         INTEGER NOT NULL,
    drop_chance         REAL    NOT NULL,
    starting_durability INTEGER NOT NULL DEFAULT 100,
    imported_at         TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS random_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    UNIQUE NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    event_type    TEXT    NOT NULL,
    rarity        TEXT    NOT NULL,
    flavor_text   TEXT    NOT NULL,
    effect_type   TEXT    NOT NULL,
    effect_amount INTEGER NOT NULL,
    duration      TEXT    NOT NULL,
    imported_at   TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS master (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_name              TEXT    UNIQUE NOT NULL,
    is_active               INTEGER NOT NULL DEFAULT 1,
    boss_id                 INTEGER NOT NULL REFERENCES bosses(id),
    boss_weapon_id          INTEGER NOT NULL REFERENCES weapons(id),
    boss_armor_id           INTEGER NOT NULL REFERENCES armor(id),
    boss_special_item_id    INTEGER NOT NULL REFERENCES special_items(id),
    minion_id               INTEGER NOT NULL REFERENCES minions(id),
    minion_weapon_id        INTEGER NOT NULL REFERENCES weapons(id),
    minion_armor_id         INTEGER NOT NULL REFERENCES armor(id),
    minion_special_item_id  INTEGER NOT NULL REFERENCES special_items(id),
    imported_at             TEXT    NOT NULL DEFAULT (datetime("now"))
);

CREATE TABLE IF NOT EXISTS settings (
    constant_name TEXT PRIMARY KEY,
    value         TEXT NOT NULL,
    description   TEXT,
    imported_at   TEXT NOT NULL DEFAULT (datetime("now"))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_players_username        ON players(username);
CREATE INDEX IF NOT EXISTS idx_players_email           ON players(email);
CREATE INDEX IF NOT EXISTS idx_players_in_combat       ON players(in_combat);
CREATE INDEX IF NOT EXISTS idx_inventory_player        ON inventory_items(player_id);
CREATE INDEX IF NOT EXISTS idx_inventory_type          ON inventory_items(player_id, item_type);
CREATE INDEX IF NOT EXISTS idx_combat_sessions_status  ON combat_sessions(status);
CREATE INDEX IF NOT EXISTS idx_combat_sessions_attacker ON combat_sessions(attacker_player_id);
CREATE INDEX IF NOT EXISTS idx_combat_logs_session     ON combat_logs(combat_session_id);
CREATE INDEX IF NOT EXISTS idx_daily_feed_player       ON daily_feed(player_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_daily_feed_global       ON daily_feed(feed_scope, occurred_at);
CREATE INDEX IF NOT EXISTS idx_boss_instances_player   ON boss_instances(player_id);
CREATE INDEX IF NOT EXISTS idx_minion_instances_player ON minion_instances(player_id);
CREATE INDEX IF NOT EXISTS idx_action_queue_status     ON action_queue(status, created_at);
CREATE INDEX IF NOT EXISTS idx_item_history_player     ON item_history(player_id);
CREATE INDEX IF NOT EXISTS idx_special_registry_status ON special_item_registry(status);
'''


################################################################################
# FILE: database.py
################################################################################

# database.py
# Single point of contact for all DB operations.
# Provides: connection management, schema init, query helpers,
# exclusive transaction context manager, player/setting loaders.

import sqlite3
import logging
import math
import uuid
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
# FILE: queue_handler.py
################################################################################

# queue_handler.py
# Synchronous action queue: writes a receipt to action_queue, processes inline
# inside an exclusive DB transaction, marks done or failed.
# On server restart, startup_cleanup() handles any orphaned PROCESSING rows.

import json
import logging
from datetime import datetime, timedelta

from database import execute, execute_one, execute_write, exclusive_transaction
import config_defaults as cfg

logger = logging.getLogger(__name__)

ACTION_HANDLERS: dict = {}


def register_handler(action_type: str):
    """Decorator to register an action handler function.

    Usage:
        @register_handler('tavern_heal')
        def handle_tavern_heal(player_id, payload):
            ...
    """
    def decorator(fn):
        ACTION_HANDLERS[action_type] = fn
        return fn
    return decorator


def enqueue_and_process(player_id: int, action_type: str, payload: dict) -> dict:
    """Main entry point for all player write actions.
    Writes receipt, processes inline, marks done or failed."""
    if action_type not in ACTION_HANDLERS:
        raise ValueError(f"Unknown action_type: '{action_type}'")

    with exclusive_transaction():
        queue_id = execute_write(
            "INSERT INTO action_queue (player_id, action_type, payload, status) VALUES (?, ?, ?, 'PROCESSING')",
            (player_id, action_type, json.dumps(payload))
        )

    try:
        with exclusive_transaction():
            result = ACTION_HANDLERS[action_type](player_id, payload)

        with exclusive_transaction():
            execute_write(
                "UPDATE action_queue SET status = 'DONE', processed_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), queue_id)
            )
        return result

    except Exception as exc:
        try:
            with exclusive_transaction():
                execute_write(
                    "UPDATE action_queue SET status = 'FAILED', processed_at = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), queue_id)
                )
        except Exception:
            pass
        logger.exception("Action '%s' FAILED for player %d (queue_id=%d)", action_type, player_id, queue_id)
        raise RuntimeError(f"Action '{action_type}' failed: {exc}") from exc


def startup_cleanup():
    """Called once at app startup. Cleans up any PROCESSING rows from a prior crash.
    Refunds AP, clears in_combat, marks FAILED, logs to orphan log."""
    import sqlite3, os

    conn = sqlite3.connect(cfg.DB_PATH)
    conn.row_factory = lambda c, r: {col[0]: val for col, val in zip(c.description, r)}
    conn.execute("PRAGMA foreign_keys = ON")

    orphans = conn.execute("SELECT * FROM action_queue WHERE status = 'PROCESSING'").fetchall()
    if not orphans:
        conn.close()
        return

    logger.warning("startup_cleanup: %d orphaned actions found", len(orphans))
    os.makedirs(os.path.dirname(cfg.ORPHAN_LOG), exist_ok=True)

    with open(cfg.ORPHAN_LOG, "a") as log_file:
        for orphan in orphans:
            pid = orphan["player_id"]
            log_file.write(
                f"{datetime.utcnow().isoformat()} | ORPHAN | player={pid} "
                f"action={orphan['action_type']} queue_id={orphan['id']}\n"
            )
            ap_refund = _ap_cost_for_action(orphan["action_type"])
            conn.execute("BEGIN EXCLUSIVE")
            try:
                if ap_refund > 0:
                    conn.execute(
                        "UPDATE players SET current_ap = MIN(current_ap + ?, ?) WHERE id = ?",
                        (ap_refund, cfg.AP_CARRYOVER_CAP, pid)
                    )
                session = conn.execute(
                    """SELECT id, defender_player_id FROM combat_sessions
                       WHERE (attacker_player_id = ? OR defender_player_id = ?) AND status = 'ACTIVE'""",
                    (pid, pid)
                ).fetchone()
                if session:
                    conn.execute(
                        "UPDATE players SET in_combat = 0 WHERE id IN (?, ?)",
                        (pid, session["defender_player_id"] or pid)
                    )
                    conn.execute(
                        "UPDATE combat_sessions SET status = 'CANCELLED', result = 'CANCELLED' WHERE id = ?",
                        (session["id"],)
                    )
                conn.execute(
                    "UPDATE action_queue SET status = 'FAILED', processed_at = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), orphan["id"])
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                logger.exception("startup_cleanup failed on queue_id=%d", orphan["id"])

    conn.close()
    logger.info("startup_cleanup: cleaned %d orphaned actions", len(orphans))


def _ap_cost_for_action(action_type: str) -> int:
    costs = {
        "boss_fight": cfg.AP_COST_BOSS, "boss_confirm": cfg.AP_COST_BOSS,
        "pvp_start": cfg.AP_COST_PVP, "pvp_fight": cfg.AP_COST_PVP,
        "tavern_heal": cfg.AP_COST_TAVERN,
        "shop_buy": cfg.AP_COST_SHOP, "shop_sell": cfg.AP_COST_SHOP,
        "blacksmith_repair": cfg.AP_COST_BLACKSMITH,
    }
    return costs.get(action_type, 0)


def purge_old_done_rows():
    """Delete DONE rows older than 7 days. Called during midnight reset."""
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    with exclusive_transaction():
        deleted = execute_write(
            "DELETE FROM action_queue WHERE status = 'DONE' AND created_at < ?", (cutoff,)
        )
    logger.info("purge_old_done_rows: deleted %d rows", deleted)


################################################################################
# FILE: app.py
################################################################################

# app.py
# Main Flask application factory.

import logging
from datetime import datetime, timezone

from flask import Flask, session, redirect, url_for, g, request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config_defaults as cfg
from database import get_db, close_db, init_db, get_player, get_all_settings
from queue_handler import startup_cleanup

logger = logging.getLogger(__name__)

_AUTH_EXEMPT = {
    "auth.login", "auth.login_post",
    "auth.register", "auth.register_post",
    "static",
}
_LEVELUP_EXEMPT = {"auth.levelup", "auth.levelup_post", "auth.logout", "static"}


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = cfg.SECRET_KEY

    init_db()
    startup_cleanup()

    app.teardown_appcontext(close_db)
    _register_blueprints(app)
    app.context_processor(_context_processor)
    app.before_request(_check_auth)
    app.before_request(_load_player)
    app.before_request(_check_levelup)
    app.before_request(_set_blackout_flag)
    _start_scheduler(app)

    return app


def _register_blueprints(app: Flask):
    from routes.auth        import bp as auth_bp
    from routes.dashboard   import bp as dashboard_bp
    from routes.actions     import bp as actions_bp
    from routes.combat      import bp as combat_bp
    from routes.shop        import bp as shop_bp
    from routes.blacksmith  import bp as blacksmith_bp
    from routes.character   import bp as character_bp
    from routes.scoreboards import bp as scoreboards_bp
    from routes.feeds       import bp as feeds_bp

    for bp in [auth_bp, dashboard_bp, actions_bp, combat_bp, shop_bp,
               blacksmith_bp, character_bp, scoreboards_bp, feeds_bp]:
        app.register_blueprint(bp)


def _context_processor() -> dict:
    player = g.get("player")
    if not player:
        return {}
    return {"player": player, "settings": get_all_settings()}


def _check_auth():
    if request.endpoint in _AUTH_EXEMPT:
        return None
    if not session.get("player_id"):
        return redirect(url_for("auth.login"))
    return None


def _load_player():
    player_id = session.get("player_id")
    if not player_id:
        return None
    player = get_player(player_id)
    if player is None:
        session.clear()
        return redirect(url_for("auth.login"))
    g.player = player
    return None


def _check_levelup():
    if request.endpoint in _LEVELUP_EXEMPT:
        return None
    player = g.get("player")
    if player and player.get("pending_levelup") and not player.get("in_combat"):
        return redirect(url_for("auth.levelup"))
    return None


def _set_blackout_flag():
    settings = get_all_settings()
    blackout_mins = settings.get("MIDNIGHT_BLACKOUT_MINUTES", cfg.MIDNIGHT_BLACKOUT_MINUTES)
    now = datetime.now(timezone.utc)
    minutes_to_midnight = (24 * 60) - (now.hour * 60 + now.minute)
    g.blackout = (minutes_to_midnight <= blackout_mins)


def _start_scheduler(app: Flask):
    from scheduler import midnight_reset, ap_trickle

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        func=lambda: _run_with_context(app, midnight_reset),
        trigger=CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="midnight_reset", name="Midnight Reset",
        replace_existing=True, misfire_grace_time=300,
    )
    scheduler.add_job(
        func=lambda: _run_with_context(app, ap_trickle),
        trigger=CronTrigger(hour="3,9,15,21", minute=0, timezone="UTC"),
        id="ap_trickle", name="AP Trickle",
        replace_existing=True, misfire_grace_time=300,
    )
    scheduler.start()
    logger.info("APScheduler started")


def _run_with_context(app: Flask, fn):
    with app.app_context():
        try:
            fn()
        except Exception:
            logger.exception("Scheduled job '%s' raised an exception", fn.__name__)


################################################################################
# FILE: scheduler.py
################################################################################

# scheduler.py
# APScheduler job implementations.
# ap_trickle is fully implemented. midnight_reset has stubs for phases 7+.

import logging
from datetime import datetime

from database import execute, execute_write, exclusive_transaction, get_all_settings
from queue_handler import purge_old_done_rows
import config_defaults as cfg

logger = logging.getLogger(__name__)


def ap_trickle():
    """Award TRICKLE_AP_AMOUNT to all non-banned players, capped at AP_CARRYOVER_CAP.
    Runs at 03:00, 09:00, 15:00, 21:00 UTC daily."""
    settings = get_all_settings()
    trickle = settings.get("TRICKLE_AP_AMOUNT", cfg.TRICKLE_AP_AMOUNT)
    cap     = settings.get("AP_CARRYOVER_CAP",  cfg.AP_CARRYOVER_CAP)

    with exclusive_transaction():
        updated = execute_write(
            "UPDATE players SET current_ap = MIN(current_ap + ?, ?) WHERE is_banned = 0",
            (trickle, cap)
        )
    logger.info("ap_trickle: +%d AP to %d players at %s", trickle, updated, datetime.utcnow().isoformat())


def midnight_reset():
    """Full midnight reset sequence. Steps 2, 7, 8-11 are stubs until Phase 7."""
    logger.info("=== MIDNIGHT RESET START %s ===", datetime.utcnow().isoformat())

    _step0_clear_status_effects()
    purge_old_done_rows()              # step 1
    _step2_apply_import()              # stub
    _step3_archive_and_clear_feeds()
    _step4_5_award_daily_ap()
    _step6_restore_midnight_hp()
    _step7_midnight_encounters()       # stub
    _step8_11_shop_rotation()          # partial stub

    logger.info("=== MIDNIGHT RESET COMPLETE %s ===", datetime.utcnow().isoformat())


def _step0_clear_status_effects():
    with exclusive_transaction():
        deleted = execute_write("DELETE FROM status_effects")
    logger.info("step 0: cleared %d status effects", deleted)


def _step2_apply_import():
    import os
    if os.path.exists(cfg.PENDING_IMPORT_PATH):
        logger.info("step 2: pending import found — TODO Phase 7")
    else:
        logger.info("step 2: no pending import")


def _step3_archive_and_clear_feeds():
    settings = get_all_settings()
    if settings.get("LOG_DAILY_ARCHIVE", cfg.LOG_DAILY_ARCHIVE):
        logger.info("step 3: archive enabled — TODO Phase 7")
    with exclusive_transaction():
        deleted = execute_write("DELETE FROM daily_feed")
    logger.info("step 3: cleared %d feed entries", deleted)


def _step4_5_award_daily_ap():
    settings = get_all_settings()
    base_ap = settings.get("BASE_DAILY_AP",    cfg.BASE_DAILY_AP)
    cap     = settings.get("AP_CARRYOVER_CAP", cfg.AP_CARRYOVER_CAP)
    with exclusive_transaction():
        execute_write(
            "UPDATE players SET current_ap = MIN(current_ap + ? + (end_stat / 2), ?) WHERE is_banned = 0",
            (base_ap, cap)
        )
    logger.info("steps 4+5: awarded daily AP (base=%d, cap=%d)", base_ap, cap)


def _step6_restore_midnight_hp():
    settings   = get_all_settings()
    heal_pct   = settings.get("MIDNIGHT_HEAL_PERCENT", cfg.MIDNIGHT_HEAL_PERCENT)
    players    = execute("SELECT id, current_hp, end_stat, level FROM players WHERE is_banned = 0")
    with exclusive_transaction():
        for p in players:
            max_hp  = 10 + p["end_stat"] + (5 * p["level"])
            missing = max_hp - p["current_hp"]
            if missing > 0:
                restore = max(1, int(missing * heal_pct))
                execute_write(
                    "UPDATE players SET current_hp = MIN(current_hp + ?, ?) WHERE id = ?",
                    (restore, max_hp, p["id"])
                )
    logger.info("step 6: restored midnight HP")


def _step7_midnight_encounters():
    logger.info("step 7: midnight encounters — TODO Phase 7")


def _step8_11_shop_rotation():
    with exclusive_transaction():
        execute_write("DELETE FROM shop_listings WHERE listing_source = 'DAILY_ROTATION'")
    logger.info("steps 8-11: cleared daily rotation — full repopulation TODO Phase 7")
