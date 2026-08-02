# Technical Specification

**Project:** BBS-Inspired Multiplayer Dueling Game  
**Stack:** Python/Flask, SQLite, HTML/CSS, APScheduler  
**Status:** Living document — updated as implementation decisions are made.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Module Dependency Map](#2-module-dependency-map)
3. [database.py](#3-databasepy)
4. [config_defaults.py](#4-config_defaultspy)
5. [app.py](#5-apppy)
6. [admin.py](#6-adminpy)
7. [queue_handler.py](#7-queue_handlerpy)
8. [scheduler.py](#8-schedulerpy)
9. [importer.py](#9-importerpy)
10. [combat/engine.py](#10-combatenginepy)
11. [combat/actions.py](#11-combatactionspy)
12. [combat/flavour.py](#12-combatflavourpy)
13. [routes/auth.py](#13-routesauthpy)
14. [routes/dashboard.py](#14-routesdashboardpy)
15. [routes/actions.py](#15-routesactionspy)
16. [routes/combat.py](#16-routescombatpy)
17. [routes/shop.py](#17-routesshoppy)
18. [routes/blacksmith.py](#18-routesblacksmithpy)
19. [routes/character.py](#19-routescharacterpy)
20. [routes/scoreboards.py](#20-routesscoreboardspy)
21. [routes/feeds.py](#21-routesfeedspy)
22. [static/terminal.js](#22-staticterminaljs)
23. [Templates Overview](#23-templates-overview)
24. [Build Order](#24-build-order)

---

## 1. Project Structure

```
game/
├── app.py                    # Main Flask app factory, blueprints, APScheduler, context processor
├── admin.py                  # Separate Flask admin app (localhost only, own process)
├── config_defaults.py        # Hardcoded fallback constants for all game settings
├── database.py               # DB connection, init, query helpers, exclusive transaction context
├── queue_handler.py          # Action queue write/process/cleanup
├── scheduler.py              # APScheduler jobs: midnight_reset, ap_trickle
├── importer.py               # Excel import: parse, validate, diff, apply
├── combat/
│   ├── __init__.py
│   ├── engine.py             # Core combat resolution: rolls, damage, dodge, durability
│   ├── actions.py            # Per-action handlers: attack, steal, brace, escape, swap, observe
│   └── flavour.py            # Flavor text generation for combat log and feeds
├── routes/
│   ├── __init__.py
│   ├── auth.py               # /login, /logout, /register, /character-create, /levelup
│   ├── dashboard.py          # / (main dashboard shell)
│   ├── actions.py            # /action/boss, /action/pvp, /action/tavern (terminal fragments)
│   ├── combat.py             # /combat/* (terminal fragments)
│   ├── shop.py               # /shop (full page)
│   ├── blacksmith.py         # /blacksmith (full page)
│   ├── character.py          # /character (full page)
│   ├── scoreboards.py        # /scoreboards (full page)
│   └── feeds.py              # /feed/*/latest (JSON polling endpoints)
├── templates/
│   ├── base.html             # Dark theme shell: left column, terminal area, bottom ticker
│   ├── dashboard.html        # Extends base, initialises terminal with history entries
│   ├── auth/
│   │   ├── login.html
│   │   ├── register.html
│   │   ├── character_create.html
│   │   └── levelup.html
│   ├── shop/
│   │   └── shop.html
│   ├── blacksmith/
│   │   └── blacksmith.html
│   ├── character/
│   │   └── character.html
│   ├── scoreboards/
│   │   └── scoreboards.html
│   ├── fragments/            # Terminal HTML fragments (returned by POST routes)
│   │   ├── event_result.html
│   │   ├── boss_confirm.html
│   │   ├── opponent_list.html
│   │   ├── combat_open.html
│   │   ├── combat_round.html
│   │   ├── combat_steal_confirm.html
│   │   ├── combat_extend.html
│   │   ├── combat_result.html
│   │   ├── tavern_result.html
│   │   └── error.html
│   └── admin/
│       ├── base_admin.html
│       ├── dashboard.html
│       ├── players.html
│       ├── player_detail.html
│       ├── import.html
│       ├── config.html
│       └── logs.html
├── static/
│   ├── style.css             # Dark theme, monospace terminal, left column, ticker
│   └── terminal.js           # Feed polling, left-column status updates, round-4 timer
└── data/
    ├── game.db               # SQLite database
    ├── pending_import.xlsx   # Staged Excel file (if any)
    └── logs/
        ├── import_errors.log
        ├── orphan_actions.log
        └── rejected/         # Rejected import files moved here with timestamp
```

---

## 2. Module Dependency Map

```
app.py
├── imports: database, config_defaults, scheduler, queue_handler
├── registers: all route blueprints
└── sets up: context processor, before_request hooks, APScheduler

admin.py
├── imports: database, config_defaults, importer
└── completely separate Flask app, own process, localhost only

database.py
└── imported by: everything (no dependencies of its own beyond sqlite3)

config_defaults.py
└── imported by: database, scheduler, importer, all routes, combat/*

queue_handler.py
├── imports: database, config_defaults
└── imported by: all POST routes (via routes/*)

scheduler.py
├── imports: database, config_defaults, importer
└── imported by: app.py (registers jobs on startup)

importer.py
├── imports: database, config_defaults
└── imported by: scheduler.py (midnight step), admin.py (manual trigger)

combat/engine.py
├── imports: database, config_defaults, combat/flavour
└── imported by: combat/actions.py

combat/actions.py
├── imports: database, config_defaults, combat/engine, combat/flavour
└── imported by: routes/actions.py, routes/combat.py, queue_handler.py

combat/flavour.py
├── imports: config_defaults (for boss/item names via DB lookup)
└── imported by: combat/engine.py, combat/actions.py

routes/*.py
├── imports: database, config_defaults, queue_handler, combat/actions
└── registered as blueprints in app.py
```

---

## 3. database.py

**Purpose:** Single point of contact for all DB operations. Provides connection management, schema initialisation, helper query functions, and the exclusive transaction context manager used by the queue.

**Key functions:**

```python
def get_db() -> sqlite3.Connection
    # Returns thread-local DB connection, creates if not exists
    # Called by every function that needs DB access

def init_db()
    # Creates all 26 tables and indexes if they don't exist
    # Called once at app startup
    # Also called by admin full-reset route (drops and recreates)

def close_db(e=None)
    # Closes thread-local connection
    # Registered as app.teardown_appcontext

class exclusive_transaction:
    # Context manager: BEGIN EXCLUSIVE ... COMMIT/ROLLBACK
    # Used by queue_handler for all write operations
    # Usage: with exclusive_transaction(): db_writes_here()

def get_player(player_id: int) -> dict | None
    # Returns full player row as dict including computed fields
    # max_hp, max_ap, inventory_limit calculated and included
    # Called by context processor on every request

def get_setting(constant_name: str, default=None)
    # Looks up settings table, falls back to config_defaults if missing
    # Logs a warning if falling back

def get_all_settings() -> dict
    # Returns full settings table as a dict
    # Called once per request cycle and cached on g

def execute(sql: str, params=()) -> list[dict]
    # Executes SELECT, returns list of row dicts

def execute_write(sql: str, params=()) -> int
    # Executes INSERT/UPDATE/DELETE, returns lastrowid or rowcount
    # Must be called inside exclusive_transaction context

def dict_factory(cursor, row) -> dict
    # sqlite3 row_factory for named column access
```

**Notes:**
- All DB access goes through this module — no raw `sqlite3` calls in route files
- `get_db()` uses Flask's `g` object for thread-local connection storage
- Schema SQL lives in a `schema.sql` file in the same directory, loaded by `init_db()`

---

## 4. config_defaults.py

**Purpose:** Hardcoded fallback values for every game constant. The `database.get_setting()` function always tries the `settings` DB table first, falling back here if the row is missing. Also holds non-game deployment constants that never go in the DB.

**Structure:**

```python
# ── Deployment constants (never in DB) ──────────────────────
PENDING_IMPORT_PATH = 'data/pending_import.xlsx'
REJECTED_IMPORT_PATH = 'data/logs/rejected/'
IMPORT_ERROR_LOG = 'data/logs/import_errors.log'
ORPHAN_LOG = 'data/logs/orphan_actions.log'
TERMINAL_HISTORY_ENTRIES = 20
DB_PATH = 'data/game.db'

# ── Game constants (fallbacks if missing from settings table) ─
BASE_DAILY_AP = 20
AP_CARRYOVER_CAP = 40
AP_COST_BOSS = 3
AP_COST_PVP = 3
AP_COST_TAVERN = 2
AP_COST_BLACKSMITH = 2
AP_COST_SHOP = 1
AP_COST_ESCAPE = 1
TRICKLE_AP_AMOUNT = 3
TRICKLE_AP_INTERVAL_HOURS = 6
COMBAT_EXTENSION_TIMEOUT = 20
MIDNIGHT_BLACKOUT_MINUTES = 10
STARTING_CREDITS = 25
STARTING_STAT_POINTS = 10
BASE_HP = 10
HP_PER_LEVEL = 5
END_HP_REGEN_DIVISOR = 2
TAVERN_HEAL_COST = 15
TAVERN_HEAL_PERCENT = 0.50
BRACE_HEAL_PERCENT = 0.25
BRACE_AC_BONUS_PERCENT = 0.25
BRACE_DODGE_BONUS = 5
MIDNIGHT_HEAL_PERCENT = 0.50
REPAIR_BASE_PERCENT = 0.50
REPAIR_LCK_MULTIPLIER = 2
REPAIR_LCK_CAP = 0.75
REPAIR_COST_PERCENT = 0.25
COMBAT_ROUNDS_DEFAULT = 4
COMBAT_ROUNDS_EXTENSION = 4
COMBAT_WIN_HP_WEIGHT = 0.40
COMBAT_WIN_DMG_WEIGHT = 0.60
CREDIT_STEAL_PERCENT = 0.10
CREDIT_STEAL_LUCK_MULTIPLIER = 2
ZERO_CREDIT_XP_BONUS = 25
STEAL_ACTION_CREDIT_PERCENT = 0.20
STEAL_BOSS_CREDIT_MULTIPLIER = 20
STEAL_SPECIAL_BASE_CHANCE = 0.03
ESCAPE_CREDIT_DROP_CHANCE = 0.10
INVENTORY_LIMIT = 10
OVERENCUMBERED_AP_MULTIPLIER = 2
OVERENCUMBERED_AC_PENALTY = 3
OVERENCUMBERED_ATTACK_PENALTY = 3
SWAP_GEAR_ACCURACY_PENALTY = 0.30
SWAP_GEAR_AC_PENALTY = 0.30
SHOP_WEAPONS_COUNT = 10
SHOP_ARMOR_COUNT = 10
SHOP_DISCOUNT_MAX = 0.50
RANDOM_EVENT_BASE_CHANCE = 0.20
RANDOM_EVENT_MAX_CHANCE = 0.60
RANDOM_EVENT_GOOD_BASE = 0.50
RANDOM_EVENT_GOOD_MAX = 0.90
RANDOM_EVENT_BAD_MIN = 0.10
RANDOM_EVENT_LCK_BONUS = 0.05
AP_PASSIVE_HP_REGEN = 1
CRIT_BASE_THRESHOLD = 20
CRIT_LCK_DIVISOR = 5
CRIT_MIN_THRESHOLD = 15
RESISTANCE_STACK_MIN_DAMAGE_PERCENT = 0.25
XP_LOSS_DIVISOR = 3
SELL_PRICE_PERCENT = 0.50
COMBAT_PREF_BALANCED_SPLIT = 0.50
COMBAT_PREF_OPPORTUNIST_SPLIT = 0.50
WEALTH_TIER_POOR_MAX = 0.33
WEALTH_TIER_MIDDLE_MAX = 0.66
INACTIVE_DAYS_THRESHOLD = 7
MINION_ENCOUNTER_CHANCE = 0.50
CURSE_AP_REDUCTION = 0.20
SPECIAL_ITEM_DURABILITY_LOSS_PER_ROUND = 0.02
BOSS_LEVEL_WARNING_THRESHOLD = 3
LOG_DAILY_ARCHIVE = False
LOG_ARCHIVE_PATH = 'data/logs/daily/'

XP_CURVE = {
    2: 100, 3: 250, 4: 500, 5: 900,
    6: 1400, 7: 2000, 8: 2700, 9: 3500,
    10: 4400, 11: 5500, 12: 7000, 13: 9000,
    14: 12000, 15: 16000
}
```

---

## 5. app.py

**Purpose:** Main Flask app factory. Registers blueprints, sets up APScheduler, context processor, and before_request hooks.

**Key functions:**

```python
def create_app() -> Flask
    # Creates and configures the Flask app
    # Calls: init_db(), startup_cleanup(), register_blueprints()
    # Sets up: APScheduler, context processor, before_request hooks

def register_blueprints(app)
    # Registers all route blueprints:
    # auth, dashboard, actions, combat, shop, blacksmith, character, scoreboards, feeds

@app.context_processor
def inject_player() -> dict
    # Loads player from DB using session['player_id']
    # Injects 'player' dict into every template
    # Returns {} if not logged in

@app.before_request
def check_auth()
    # Redirects to /login if not logged in
    # Exempt routes: /login, /register, /static/*

@app.before_request
def check_levelup()
    # If player.pending_levelup AND NOT player.in_combat:
    # Redirect to /levelup
    # Exempt routes: /levelup, /logout, /static/*

@app.before_request
def check_blackout()
    # If current UTC time within MIDNIGHT_BLACKOUT_MINUTES of midnight:
    # Sets g.blackout = True (routes check this before allowing combat)
```

**Notes:**
- `create_app()` is the entry point — run with `flask run` or `gunicorn`
- APScheduler is initialised here and jobs are added from `scheduler.py`
- `startup_cleanup()` from `queue_handler.py` is called inside `create_app()`

---

## 6. admin.py

**Purpose:** Completely separate Flask app for admin tools. Runs on localhost only, own process (e.g. `flask --app admin run --port 5001`). Shares `database.py` and `config_defaults.py` with the main app but has no shared routes, sessions, or blueprints.

**Routes and their handlers:**

```python
GET  /admin                     → render dashboard: player count, AP, import status, recent errors
GET  /admin/import              → show staged file status, upload form
POST /admin/import              → save uploaded file to PENDING_IMPORT_PATH
GET  /admin/players             → list all players with key stats
GET  /admin/players/<id>        → full player detail: stats, inventory, history
POST /admin/players/<id>/ban    → ban_player(id): wipe credits/gear, return specials to pool
POST /admin/players/<id>/edit   → manual field edits (credits, HP, AP, stats)
GET  /admin/config              → display all settings with current DB values vs defaults
POST /admin/config              → upsert settings rows
POST /admin/reset/midnight      → call midnight_reset() from scheduler.py directly
POST /admin/reset/full          → full_game_reset(): drop all operational tables, re-init, re-import
GET  /admin/logs                → display recent import_errors.log and orphan_actions.log entries
```

**Key functions:**

```python
def ban_player(player_id: int)
    # Sets is_banned = True
    # Deletes all inventory_items for player
    # NULLs equipped_*_id on players row
    # Returns any special items to pool (registry status -> IN_POOL)
    # Clears in_combat, pending_levelup flags
    # Logs to item_history with event_type = RETIRED_BY_ADMIN for specials

def full_game_reset()
    # Drops all operational tables (players and everything cascading)
    # Re-runs init_db() to recreate clean schema
    # If pending_import.xlsx exists: runs importer immediately
    # Logs the reset event
```

---

## 7. queue_handler.py

**Purpose:** Provides the synchronous action queue pattern. Every player write action goes through here — writes a receipt to `action_queue`, processes inline inside an exclusive transaction, marks done or failed.

**Key functions:**

```python
def enqueue_and_process(player_id: int, action_type: str, payload: dict) -> dict
    # 1. INSERT into action_queue (status=PROCESSING)
    # 2. Call ACTION_HANDLERS[action_type](player_id, payload) inside exclusive_transaction
    # 3. On success: UPDATE status=DONE, processed_at=now()
    # 4. On exception: UPDATE status=FAILED, re-raise
    # Returns: result dict from handler (contains terminal fragment HTML or redirect info)

def startup_cleanup()
    # Called once at app startup (from create_app)
    # Finds all action_queue rows with status=PROCESSING
    # For each: refund AP, clear in_combat, mark FAILED, log to orphan_actions.log

def purge_old_done_rows()
    # Deletes action_queue rows where status=DONE AND created_at < NOW - 7 days
    # Called as part of midnight reset sequence

ACTION_HANDLERS = {
    'boss_fight':         handle_boss_fight,
    'boss_confirm':       handle_boss_confirm,
    'pvp_start':          handle_pvp_start,
    'pvp_fight':          handle_pvp_fight,
    'tavern_heal':        handle_tavern_heal,
    'combat_action':      handle_combat_action,
    'combat_steal':       handle_combat_steal,
    'combat_steal_confirm': handle_combat_steal_confirm,
    'combat_extend':      handle_combat_extend,
    'combat_resolve':     handle_combat_resolve,
    'shop_buy':           handle_shop_buy,
    'shop_sell':          handle_shop_sell,
    'blacksmith_repair':  handle_blacksmith_repair,
    'equip':              handle_equip,
    'unequip':            handle_unequip,
    'drop_item':          handle_drop_item,
    'set_preference':     handle_set_preference,
    'assign_levelup':     handle_assign_levelup,
}
```

**Notes:**
- All handler functions live in their respective route modules and are imported here
- The `ACTION_HANDLERS` dict is the central registry of all write operations
- No handler should ever write to DB outside of the `exclusive_transaction` context

---

## 8. scheduler.py

**Purpose:** Defines the two APScheduler jobs and their full implementation. Imported by `app.py` which registers the jobs on startup.

**Key functions:**

```python
def register_jobs(scheduler: APScheduler)
    # Registers both jobs with the scheduler
    # Called from create_app() after scheduler is initialised
    # midnight_reset: cron trigger, hour=0, minute=0, timezone='UTC'
    # ap_trickle: cron trigger, hour='3,9,15,21', minute=0, timezone='UTC'

def midnight_reset()
    # Full 12-step reset sequence (see SchemaReference Section 10.5)
    # Step 0:  clear status_effects
    # Step 1:  purge old action_queue DONE rows (calls queue_handler.purge_old_done_rows)
    # Step 2:  check for pending_import.xlsx, validate + apply if present (calls importer)
    # Step 3:  archive + clear daily_feed (calls archive_feeds if LOG_DAILY_ARCHIVE)
    # Step 4:  calculate AP carryover per player
    # Step 5:  award new daily AP
    # Step 6:  restore midnight HP
    # Step 7:  trigger midnight random encounters
    # Step 8:  rotate shop (clear DAILY_ROTATION, populate new 10+10)
    # Step 9:  clear unsold special items from shop, return to pool
    # Step 10: populate special item shop slots
    # Step 11: process pending feed entries
    # All steps wrapped in exclusive_transaction for atomicity

def ap_trickle()
    # Awards TRICKLE_AP_AMOUNT to all non-banned players
    # Caps each player at AP_CARRYOVER_CAP
    # Single UPDATE statement: current_ap = MIN(current_ap + TRICKLE_AP_AMOUNT, AP_CARRYOVER_CAP)
    # Runs inside exclusive_transaction

def archive_feeds()
    # Exports daily_feed to LOG_ARCHIVE_PATH/game_log_YYYY_MM_DD.txt
    # Called from midnight_reset step 3 if LOG_DAILY_ARCHIVE = True

def award_midnight_encounters()
    # For each active non-banned player: run random event check
    # Uses same random event logic as in-game events
    # Inserts results to daily_feed (PERSONAL scope)
    # Called from midnight_reset step 7
```

---

## 9. importer.py

**Purpose:** Reads the staged Excel file, validates it, diffs against current DB content, and applies changes atomically. Called by `scheduler.py` (midnight) and `admin.py` (manual trigger / full reset).

**Key functions:**

```python
def run_import(filepath: str, full_reset: bool = False) -> dict
    # Main entry point. Returns {'success': bool, 'errors': list, 'changes': dict}
    # 1. parse_workbook(filepath) -> raw data dict
    # 2. validate(raw_data) -> errors list
    # 3. If errors: log, move file to rejected/, return failure
    # 4. diff_content(raw_data) -> changes dict (what changed vs current DB)
    # 5. apply_changes(changes) inside exclusive_transaction
    # 6. clear_stale_intel(changes) — clears boss_intel for changed resistance/damage cols
    # 7. auto_populate_associated_to(changes) — updates weapons/armor associated_to from master
    # 8. Move/delete staged file
    # 9. Return success result

def parse_workbook(filepath: str) -> dict
    # Uses openpyxl to read all sheets
    # Returns nested dict: {'bosses': [...], 'minions': [...], 'weapons': [...], ...}
    # Each sheet becomes a list of row dicts keyed by column header

def validate(raw_data: dict) -> list[str]
    # Returns list of error strings (empty = valid)
    # Checks: required sheets present, required columns per sheet,
    # value ranges (level 1-15, drop_chance 0-1, etc.),
    # cross-references (master boss_name exists in bosses sheet, etc.),
    # damage type values are one of the 7 supported types,
    # buff types are one of the 6 supported types,
    # no duplicate names within a sheet

def diff_content(raw_data: dict) -> dict
    # Compares raw_data against current DB content tables
    # Returns: {'bosses': {'insert': [...], 'update': [...]}, 'weapons': {...}, ...}
    # Match is by name (unique key per table)
    # Never produces 'delete' entries (daily refresh is additive only)

def apply_changes(changes: dict)
    # Executes INSERT/UPDATE for all changed rows across all content tables
    # Settings rows use INSERT OR REPLACE (upsert by constant_name)
    # Must be called inside exclusive_transaction

def clear_stale_intel(changes: dict)
    # For each updated boss: check if any intel-sensitive columns changed
    # Intel-sensitive: res_*, weak_*, special_attack_damage_type, special_buff_damage_type
    # If changed: DELETE FROM boss_intel WHERE boss_id = <id>

def auto_populate_associated_to(changes: dict)
    # After master table is updated: query master to rebuild associated_to
    # on all weapons and armor rows referenced by master
    # Format: "MovieName (Boss)" or "MovieName (Minion)"
    # Leaves non-master-referenced items untouched
```

---

## 10. combat/engine.py

**Purpose:** Core combat math. All dice rolls, stat modifier calculations, damage resolution, resistance/weakness checks, dodge, crit, and durability. Stateless functions — takes input, returns results. Never writes to DB directly.

**Key functions:**

```python
def roll(die: int) -> int
    # Rolls a single die (e.g. roll(20) returns 1-20)

def stat_mod(stat: int) -> int
    # Returns floor(stat / 2)

def calc_ac(player: dict, armor: dict | None) -> int
    # 10 + stat_mod(AGI) + armor.ac_bonus (if equipped)

def calc_max_hp(player: dict) -> int
    # 10 + player.end_stat + (5 * player.level)

def calc_max_ap(player: dict, is_cursed: bool = False) -> int
    # BASE_DAILY_AP + stat_mod(END), reduced by CURSE_AP_REDUCTION if cursed

def calc_passive_regen(player: dict) -> int
    # AP_PASSIVE_HP_REGEN + stat_mod(END) + hp_regen_bonus (if special equipped)

def calc_initiative(player: dict, initiative_bonus: int = 0) -> int
    # roll(20) + stat_mod(AGI) + initiative_bonus

def calc_attack_roll(attacker: dict, weapon: dict) -> int
    # Melee: roll(20) + stat_mod(STR)
    # Ranged: roll(20) + stat_mod(AGI)
    # Returns raw roll total

def calc_damage(attacker: dict, weapon: dict, is_crit: bool) -> int
    # Rolls weapon.damage_die + stat_mod(STR or AGI)
    # Doubles if is_crit
    # Returns raw damage before resistance

def calc_crit_threshold(player: dict, special: dict | None) -> int
    # max(CRIT_MIN_THRESHOLD, 20 - floor(LCK / CRIT_LCK_DIVISOR))
    # Further reduced by special.crit_chance_bonus if equipped

def is_crit(roll_total: int, threshold: int) -> bool

def resolve_resistance(damage: int, damage_type: str, 
                       armor: dict | None, special: dict | None) -> int
    # Applies resistance stacking rule:
    # 0 sources: full damage
    # 1 source (armor OR special): half damage
    # 2 sources (armor AND special): floor at RESISTANCE_STACK_MIN_DAMAGE_PERCENT
    # Returns final damage (min 1)

def resolve_weakness(damage: int, damage_type: str, boss: dict) -> int
    # If boss has weakness to damage_type: double damage
    # Returns modified damage

def resolve_dodge(defender: dict, attacker: dict, 
                  brace_active: bool = False) -> bool
    # Defender: roll(20) + stat_mod(AGI) + stat_mod(LCK) + BRACE_DODGE_BONUS if active
    # Attacker: roll(20) + stat_mod(AGI)
    # Returns True if dodged (defender wins, ties go to attacker)

def resolve_full_attack(attacker: dict, defender: dict,
                        attacker_weapon: dict, attacker_special: dict | None,
                        defender_armor: dict | None, defender_special: dict | None,
                        boss: dict | None = None) -> dict
    # Runs the full attack sequence:
    # 1. Dodge check
    # 2. If not dodged: attack roll vs AC
    # 3. If hit: damage roll, resistance, weakness, bonus damage from special
    # 4. Crit check and doubling
    # 5. Durability effects
    # Returns: {hit: bool, dodged: bool, damage: int, is_crit: bool,
    #           weapon_durability_loss: int, armor_durability_loss: int,
    #           roll_detail: str, outcome_detail: str}

def calc_pvp_score(session: dict, attacker_max_hp: int, 
                   defender_max_hp: int) -> tuple[float, float]
    # Returns (attacker_score, defender_score) for tiebreak formula
    # (HP% * COMBAT_WIN_HP_WEIGHT) + (damage_dealt% * COMBAT_WIN_DMG_WEIGHT)

def calc_durability_loss(base_loss: int, durability_reduction: float) -> int
    # Applies special item durability_reduction modifier
    # base_loss * (1 - durability_reduction), min 1
```

---

## 11. combat/actions.py

**Purpose:** Per-action handlers for all 6 combat actions. Each handler takes the current combat state, resolves the action, updates the DB, and returns a result dict including roll details and outcome text for the combat log.

**Key functions:**

```python
def handle_attack(session_id: int, player: dict, combat_state: dict) -> dict
    # Resolves a full attack using engine.resolve_full_attack
    # Writes combat_log row
    # Updates HP, durability on both sides
    # Returns result dict with roll_detail, outcome_detail, updated HPs

def handle_steal(session_id: int, player: dict, combat_state: dict) -> dict
    # Checks steal roll (engine.resolve_opposed_roll with AGI+LCK)
    # On success: cascades item -> credits -> XP
    # On failure: applies AC penalty (inserts combat_buff row)
    # Writes combat_log row
    # Returns result dict

def handle_brace(session_id: int, player: dict, combat_state: dict) -> dict
    # Calculates HP restore (BRACE_HEAL_PERCENT of missing)
    # Inserts BRACE_AC_BONUS and BRACE_DODGE_BONUS rows into combat_buffs
    # Updates player.current_hp
    # Writes combat_log row
    # Returns result dict

def handle_escape(session_id: int, player: dict, combat_state: dict) -> dict
    # Deducts AP_COST_ESCAPE
    # Resolves escape roll (engine.resolve_opposed_roll with AGI+LCK)
    # On success: ends combat, rolls ESCAPE_CREDIT_DROP_CHANCE for PvP
    # On failure: inserts ESCAPE_FAIL_AC_PENALTY into combat_buffs
    # Writes combat_log row
    # Returns result dict with escaped: bool

def handle_swap_gear(session_id: int, player: dict, 
                     combat_state: dict, payload: dict) -> dict
    # Validates new item exists in inventory
    # Inserts SWAP_GEAR penalties into combat_buffs
    # Updates players.equipped_*_id
    # Writes combat_log row
    # Returns result dict

def handle_observe(session_id: int, player: dict, combat_state: dict) -> dict
    # Resolves observe roll (engine.resolve_opposed_roll with PER)
    # On success: sets session.attacker_observed = True
    #             If boss fight: inserts boss_intel row
    # Writes combat_log row
    # Returns result dict with success: bool, revealed: dict

def handle_opponent_action(session_id: int, combat_state: dict) -> dict
    # Automated opponent action based on combat_preference (PvP) or boss phase
    # For PvP defender: weighted random from preference splits
    # For boss: 33/33/33 -> 50/50 -> 100% attack probability
    # May trigger boss special attack or special buff
    # Returns result dict same format as player actions

def resolve_opposed_roll(actor_agi: int, actor_lck: int,
                         defender_agi: int, defender_lck: int,
                         actor_per: int = 0, defender_per: int = 0) -> dict
    # Generic opposed roll for steal, escape, observe, dodge
    # Returns {actor_roll: int, defender_roll: int, success: bool, detail: str}
```

---

## 12. combat/flavour.py

**Purpose:** Generates all flavor text strings for combat logs, feed entries, and event results. Keeps narrative text out of logic files.

**Key functions:**

```python
def combat_intro(combat_type: str, opponent_name: str, 
                 boss_phase: int = 1) -> str
    # Opening terminal text when combat begins

def round_header(round_num: int) -> str

def attack_flavor(attacker_name: str, weapon_name: str, 
                  hit: bool, dodged: bool, is_crit: bool,
                  damage: int, damage_type: str, resisted: bool) -> str
    # e.g. "[Player] swings the Plasma Caster — The Predator sidesteps! (Dodged)"
    # e.g. "[Player] fires the Plasma Caster — CRITICAL HIT! 18 Energy damage!"

def steal_flavor(attacker_name: str, success: bool, 
                 item_name: str = None, credits: int = 0) -> str

def brace_flavor(player_name: str, hp_restored: int) -> str

def escape_flavor(player_name: str, success: bool, credits_lost: int = 0) -> str

def observe_flavor(player_name: str, success: bool, 
                   opponent_name: str) -> str

def boss_special_attack_flavor(boss_name: str, attack_name: str, 
                                damage: int) -> str

def boss_special_buff_flavor(boss_name: str, buff_name: str) -> str

def combat_result_flavor(winner_name: str, loser_name: str,
                         combat_type: str, credits_stolen: int,
                         item_stolen: str = None) -> str
    # Global feed entry for combat outcome

def random_event_flavor(event: dict, player_name: str) -> str
    # Renders event.flavor_text with player name substituted

def level_up_flavor(player_name: str, new_level: int) -> str
    # Global feed entry for level up
```

---

## 13. routes/auth.py

**Purpose:** Handles all auth and character creation routes.

**Routes:**
```
GET  /login              → render login.html
POST /login              → validate credentials, set session['player_id'], redirect /
POST /logout             → clear session, redirect /login
GET  /register           → render register.html
POST /register           → create players row, create player_stats row,
                           award starter gear (random level 1 weapon + armor),
                           award STARTING_CREDITS, redirect /character-create
GET  /character-create   → render character_create.html (class list, stat allocation)
POST /character-create   → validate stat allocation (sum = STARTING_STAT_POINTS,
                           each >= 1 after class bonus), apply class bonuses,
                           set current_hp to starting max_hp, set current_ap,
                           redirect /
GET  /levelup            → render levelup.html (current stats, which to increase)
POST /levelup            → validate stat choice, increment stat, set pending_levelup=False,
                           recalc and fully restore HP to new max,
                           log to level_up_history, redirect /
```

**Key helpers:**

```python
def hash_password(password: str) -> str
def check_password(password: str, hash: str) -> bool
def award_starter_gear(player_id: int)
    # Selects random level 1 weapon and armor from content tables
    # Inserts into inventory_items with acquired_method='STARTER'
    # Logs to item_history
```

---

## 14. routes/dashboard.py

**Purpose:** Renders the main dashboard shell. Only one GET route — the terminal area is populated with recent feed history on load, then polling takes over.

**Routes:**
```
GET  /    → loads last TERMINAL_HISTORY_ENTRIES personal feed entries,
            renders dashboard.html with terminal history, AP action button states,
            checks g.blackout for combat button availability
```

**Key helpers:**

```python
def get_terminal_history(player_id: int) -> list[dict]
    # Returns last TERMINAL_HISTORY_ENTRIES rows from daily_feed
    # where player_id = X OR feed_scope = 'GLOBAL'
    # Ordered by occurred_at ASC (oldest first, terminal scrolls down)

def get_button_states(player: dict) -> dict
    # Returns dict of {action: enabled/disabled/reason} for left column buttons
    # Checks: in_combat, blackout, AP balance, current_hp for tavern,
    #         credits for blacksmith, all_items_full_durability for blacksmith
```

---

## 15. routes/actions.py

**Purpose:** Handles the terminal-fragment POST routes for boss fight, PvP initiation, and tavern. All return rendered HTML fragments that get appended to the terminal.

**Routes:**
```
POST /action/boss         → random event check first
                            if event: return event_result.html fragment
                            if blackout: return error.html fragment
                            else: 50/50 boss/minion roll, PER check,
                            return boss_confirm.html or combat_open.html fragment

POST /action/boss/confirm → validate confirm token, enqueue 'boss_confirm',
                            return combat_open.html fragment

POST /action/pvp          → random event check, blackout check,
                            if event: return event_result.html fragment
                            else: load eligible opponent list,
                            return opponent_list.html fragment

POST /action/pvp/fight    → validate target eligibility (re-check server-side),
                            enqueue 'pvp_fight', return combat_open.html fragment

POST /action/tavern       → enqueue 'tavern_heal', return tavern_result.html fragment
```

**Key helpers:**

```python
def check_random_event(player: dict) -> dict | None
    # Rolls trigger chance, good/bad split, rarity tier
    # If event fires: applies effect, writes feed entries
    # Returns event dict if fired, None if not

def get_eligible_opponents(player: dict) -> list[dict]
    # Returns players eligible for PvP attack:
    # Same level or higher (up to 2 levels below player)
    # Not level 1-2, not 1 HP, not in_combat, not banned, not inactive
    # Includes: name, level, hp_status_tier, wealth_tier, in_combat flag

def roll_boss_or_minion(master_row: dict) -> str
    # Returns 'boss' or 'minion' based on MINION_ENCOUNTER_CHANCE
    
def check_per_minion(player: dict, minion: dict) -> bool
    # Runs PER observe roll against minion
    # Returns True if player spots the minion (can choose to avoid)
```

---

## 16. routes/combat.py

**Purpose:** Handles all in-combat action POST routes. All return terminal fragments appended to the dashboard terminal. Uses `session['combat_session_id']` to identify the active fight.

**Routes:**
```
POST /combat/action         → validate action type, enqueue 'combat_action',
                              resolve player action + opponent action,
                              return combat_round.html fragment
                              (includes next action buttons if fight ongoing,
                               or combat_result.html if fight ended)

POST /combat/steal          → return combat_steal_confirm.html fragment
                              (shows risk/reward before committing)

POST /combat/steal/confirm  → enqueue 'combat_steal', return combat_round.html fragment

POST /combat/extend         → validate AP available, enqueue 'combat_extend',
                              return combat_round.html fragment with new round

POST /combat/resolve        → enqueue 'combat_resolve' (score formula),
                              return combat_result.html fragment
```

**Key helpers:**

```python
def get_combat_state(session_id: int) -> dict
    # Loads combat_session + both sides' current state
    # Includes: player, opponent/boss/minion, equipped gear,
    #           active combat_buffs, current HP, damage totals

def check_combat_end(combat_state: dict) -> bool
    # Returns True if fight should end (1HP for PvP, 0HP for boss/minion)

def finalize_combat(session_id: int, winner: str, reason: str)
    # Runs full post-combat resolution sequence (SchemaReference Section 11.11):
    # XP, credits, item steal, durability, over-encumbered check,
    # feed entries, boss intel, clears in_combat + session['combat_session_id']
```

---

## 17. routes/shop.py

**Purpose:** Full-page shop with live buy/sell functionality. Every transaction is a POST that redirects back to GET /shop so the page always shows current state.

**Routes:**
```
GET  /shop          → load all shop_listings, player inventory (for sell panel),
                      calculate discounts, render shop.html

POST /shop/buy      → validate item still available (re-check), validate credits,
                      enqueue 'shop_buy', redirect /shop

POST /shop/sell     → validate item owned + unequipped,
                      enqueue 'shop_sell', redirect /shop
```

---

## 18. routes/blacksmith.py

**Purpose:** Full-page repair interface.

**Routes:**
```
GET  /blacksmith    → load player inventory with durability values,
                      calculate repair cost per item,
                      render blacksmith.html
                      blocked if: credits = 0 OR all items at 100 durability

POST /blacksmith/repair → validate selected items + credit total,
                          enqueue 'blacksmith_repair', redirect /blacksmith
```

---

## 19. routes/character.py

**Purpose:** Full-page character sheet with inventory management and live stat preview.

**Routes:**
```
GET  /character         → load player + full inventory + equipped gear,
                          calculate all derived stats with current equipment,
                          render character.html

POST /character/equip   → validate item owned + slot valid,
                          enqueue 'equip', redirect /character

POST /character/unequip → enqueue 'unequip', redirect /character

POST /character/drop    → validate item unequipped,
                          enqueue 'drop_item', redirect /character

POST /character/preference → validate preference value,
                             enqueue 'set_preference', redirect /character
```

**Live stat preview note:**
- `character.html` includes a small JS snippet (part of terminal.js)
- On equip/unequip checkbox change: sends lightweight AJAX to a helper endpoint
- `GET /character/preview?weapon=<id>&armor=<id>&special=<id>` returns JSON of computed stats
- JS updates the stat display inline without a full page reload

This is the third and final JS feature (alongside feed polling and round-4 timer).

---

## 20. routes/scoreboards.py

**Purpose:** Full-page leaderboards. All data is computed via live DB queries.

**Routes:**
```
GET  /scoreboards   → runs all leaderboard queries, renders scoreboards.html
                      Excludes inactive players (last_login_at < NOW - 7 days)
```

**Queries:**
```python
def get_top_level_xp(limit=20) -> list
    # ORDER BY level DESC, xp DESC, exclude inactive + banned

def get_top_pvp_kills(limit=20) -> list
    # JOIN player_stats, ORDER BY pvp_kills DESC

def get_top_boss_kills_global(limit=20) -> list
    # SUM(boss_instances.kill_count) GROUP BY player_id

def get_top_boss_kills_per_boss() -> dict
    # {boss_name: [top players]} for each active boss

def get_top_minion_kills_global(limit=20) -> list
def get_top_minion_kills_per_minion() -> dict

def get_top_credits(limit=20) -> list
    # ORDER BY credits DESC

def get_shame_board(limit=20) -> list
    # ORDER BY player_stats.times_reduced_to_1hp DESC
```

---

## 21. routes/feeds.py

**Purpose:** Lightweight JSON polling endpoints for the live feed updates. Called every 5 seconds by terminal.js.

**Routes:**
```
GET /feed/personal/latest?since=<timestamp>
    → SELECT from daily_feed WHERE player_id = ? AND occurred_at > since
    → returns JSON: [{flavor_text, event_category, occurred_at, combat_session_id}]

GET /feed/global/latest?since=<timestamp>
    → SELECT from daily_feed WHERE feed_scope='GLOBAL' AND occurred_at > since
    → returns JSON: [{flavor_text, event_category, occurred_at}]
```

**Notes:**
- `since` is a UTC ISO timestamp string sent by the JS client
- Returns empty list `[]` if no new entries (normal, happens every poll)
- No auth required beyond being logged in (checked by before_request)
- These are the only two JSON-returning routes in the main app

---

## 22. static/terminal.js

**Purpose:** The entire client-side JS for the game. Three responsibilities only.

**Section 1 — Feed Polling:**
```javascript
const POLL_INTERVAL = 5000;
let lastPersonalTimestamp = initialTimestamp;  // injected by dashboard.html
let lastGlobalTimestamp = initialTimestamp;

function pollFeeds() {
    fetch(`/feed/personal/latest?since=${lastPersonalTimestamp}`)
        .then(r => r.json())
        .then(entries => entries.forEach(appendToTerminal));

    fetch(`/feed/global/latest?since=${lastGlobalTimestamp}`)
        .then(r => r.json())
        .then(entries => entries.forEach(appendToTicker));
}

function appendToTerminal(entry) { /* append styled div to terminal area */ }
function appendToTicker(entry) { /* append to bottom ticker */ }

setInterval(pollFeeds, POLL_INTERVAL);
```

**Section 2 — Left Column Status Updates:**
```javascript
// Called after every terminal fragment POST response
// The server includes updated HP/AP/Credits in a data attribute on the fragment
function updateStatusBlock(hp, maxHp, ap, maxAp, credits) {
    document.getElementById('status-hp').textContent = `${hp}/${maxHp}`;
    document.getElementById('status-ap').textContent = `${ap}/${maxAp}`;
    document.getElementById('status-credits').textContent = credits;
}
```

**Section 3 — Round-4 PvP Countdown Timer:**
```javascript
// Only active when combat_extend.html fragment is present in terminal
function startExtensionTimer(seconds, resolveUrl) {
    let remaining = seconds;
    const interval = setInterval(() => {
        remaining--;
        document.getElementById('extend-timer').textContent = remaining;
        if (remaining <= 0) {
            clearInterval(interval);
            fetch(resolveUrl, {method: 'POST'})
                .then(r => r.text())
                .then(html => appendToTerminal({html}));
        }
    }, 1000);
}
```

---

## 23. Templates Overview

**base.html** — the outer shell every page extends:
- `<div id="left-col">` — status block + action buttons + nav links
- `<div id="terminal">` — main content area (monospace, dark, scrollable)
- `<div id="ticker">` — fixed bottom bar, scrolling global feed
- Loads `style.css` and `terminal.js`
- Injects `player` from context processor into status block

**dashboard.html** — extends base:
- Pre-populates `#terminal` with last N personal feed entries on load
- Sets `initialTimestamp` JS variable for polling to start from
- Action button forms POST to `/action/*` routes
- Returned terminal fragments appended to `#terminal` via JS

**Full pages** (shop, blacksmith, character, scoreboards) — extend base but:
- Replace `#terminal` with a page-specific content area
- Include a small `<div id="terminal-output">` panel for error/result fragments
- Include a "Back to Dashboard" link

**fragments/** — partial HTML snippets returned by POST routes, appended to terminal:
- No `<html>`, `<head>`, or `<body>` tags
- Each includes a `data-hp`, `data-ap`, `data-credits` attribute for JS status updates
- Styled with terminal color classes: `.term-green`, `.term-red`, `.term-amber`, `.term-grey`

---

## 24. Build Order

### Phase 1 — Foundation
1. `config_defaults.py` — all constants
2. `database.py` — connection, init, helpers, schema.sql
3. `queue_handler.py` — enqueue_and_process, startup_cleanup, ACTION_HANDLERS stub
4. `app.py` — create_app, register blueprints (stubs), before_request hooks, context processor
5. `scheduler.py` — APScheduler setup, job stubs

### Phase 2 — Auth & Character
6. `routes/auth.py` + auth templates — login, register, character create, levelup
7. Test: register → create character → login → dashboard stub

### Phase 3 — Dashboard & Feeds
8. `base.html` + `dashboard.html` + `style.css` — full dark theme shell
9. `routes/dashboard.py` + `routes/feeds.py`
10. `terminal.js` — feed polling section only
11. Test: login → see dashboard terminal → feed polling works

### Phase 4 — Core Non-Combat Actions
12. `routes/actions.py` — tavern only (simplest queue pattern test)
13. `routes/shop.py` + shop templates
14. `routes/blacksmith.py` + blacksmith templates
15. `routes/character.py` + character templates + stat preview JS
16. Test: full economy loop works

### Phase 5 — Boss & Minion Combat
17. `combat/engine.py` — all math functions
18. `combat/flavour.py` — all flavor text functions
19. `combat/actions.py` — all action handlers
20. `routes/actions.py` — boss fight flow (random event, boss/minion roll, confirm)
21. `routes/combat.py` — all combat round routes + fragments
22. Test: full boss fight, minion fight, all 6 actions, post-combat resolution

### Phase 6 — PvP
23. `routes/actions.py` — PvP flow (opponent list, fight initiation)
24. `routes/combat.py` — round extension + score formula
25. `terminal.js` — countdown timer section
26. Test: full PvP loop

### Phase 7 — Scheduled Jobs & Import
27. `importer.py` — full parse, validate, diff, apply
28. `scheduler.py` — full midnight_reset and ap_trickle implementations
29. Test: midnight reset runs, import works, trickle fires

### Phase 8 — Admin App
30. `admin.py` + admin templates — all routes

### Phase 9 — Polish
31. `routes/scoreboards.py` + scoreboards template
32. All warning/blocked states across every route
33. Full flavor text pass across all events
34. End-to-end testing of complete game loop
