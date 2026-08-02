################################################################################
# PHASE 15 CODE — Pre-Launch Consolidation
# BBS-Inspired Multiplayer Dueling Game
#
# Contents:
#   1. ADMIN_AUTH_PATCH     — HTTP Basic Auth gate for admin app (env var based)
#   2. STARTING_CREDITS_PATCH — change 25 -> 50 in config_defaults.py
#   3. SCHEMA_UPDATE        — protagonist columns added to master table
#   4. SETUP_SCRIPT         — setup.py (new file, run once before first launch)
#   5. RUN_PY               — updated run.py with env var warnings
#   6. SUMMARY              — full launch sequence
#
# Secret key (set as GAME_SECRET_KEY env var):
#   replace-with-a-random-secret
#
# PvP protection and UTC midnight — both confirmed correct, no changes needed.
################################################################################

# =============================================================================
# PHASE 15 — Pre-Launch Consolidation
# =============================================================================
# Covers:
#   1. Admin password gate
#   2. Starting credits changed to 50
#   3. Schema update (protagonist columns in master table)
#   4. setup.py — one-shot setup script
#   5. Updated run.py with env var guidance
# =============================================================================

ADMIN_AUTH_PATCH = '''
# In admin.py, add at the top after imports:

import os
from functools import wraps
from flask import request, Response

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# In create_admin_app(), add before _register_routes(app):

    @app.before_request
    def check_admin_auth():
        if not ADMIN_PASSWORD:
            return None  # no password set — localhost only, no gate
        auth = request.authorization
        if not auth or auth.password != ADMIN_PASSWORD:
            return Response(
                "Admin access required.",
                401,
                {"WWW-Authenticate": \'Basic realm="Admin"\'}
            )
        return None
'''

STARTING_CREDITS_PATCH = '''
# In config_defaults.py, change:
#   STARTING_CREDITS = 25
# To:
#   STARTING_CREDITS = 50

# routes/auth.py already reads cfg.STARTING_CREDITS at runtime — no change needed.
'''

SCHEMA_UPDATE = '''
-- Updated CREATE TABLE master in schema.sql (add protagonist columns):

CREATE TABLE IF NOT EXISTS master (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_name                  TEXT    UNIQUE NOT NULL,
    is_active                   INTEGER NOT NULL DEFAULT 1,
    boss_id                     INTEGER NOT NULL REFERENCES bosses(id),
    boss_weapon_id              INTEGER NOT NULL REFERENCES weapons(id),
    boss_armor_id               INTEGER NOT NULL REFERENCES armor(id),
    boss_special_item_id        INTEGER NOT NULL REFERENCES special_items(id),
    minion_id                   INTEGER NOT NULL REFERENCES minions(id),
    minion_weapon_id            INTEGER NOT NULL REFERENCES weapons(id),
    minion_armor_id             INTEGER NOT NULL REFERENCES armor(id),
    minion_special_item_id      INTEGER NOT NULL REFERENCES special_items(id),
    protagonist_name            TEXT,
    protagonist_weapon_id       INTEGER REFERENCES weapons(id),
    protagonist_armor_id        INTEGER REFERENCES armor(id),
    protagonist_special_item_id INTEGER REFERENCES special_items(id),
    imported_at                 TEXT    NOT NULL DEFAULT (datetime("now"))
);

-- For existing DBs run once:
-- ALTER TABLE master ADD COLUMN protagonist_name              TEXT;
-- ALTER TABLE master ADD COLUMN protagonist_weapon_id         INTEGER REFERENCES weapons(id);
-- ALTER TABLE master ADD COLUMN protagonist_armor_id          INTEGER REFERENCES armor(id);
-- ALTER TABLE master ADD COLUMN protagonist_special_item_id   INTEGER REFERENCES special_items(id);
'''

SETUP_SCRIPT = '''#!/usr/bin/env python3
"""
setup.py
Run once before first launch.
Creates directories, installs dependencies, initialises DB, imports content.
"""
import os, sys, subprocess, shutil

print("=== Game Setup ===")
print()

# 1. Check for Excel
IMPORT_CANDIDATES = ("GameContent Filled.xlsx", "GameContent_Filled.xlsx")
IMPORT_SRC = next((name for name in IMPORT_CANDIDATES if os.path.exists(name)),
                  IMPORT_CANDIDATES[0])
IMPORT_DST = "data/pending_import.xlsx"
if not os.path.exists(IMPORT_SRC):
    print(f"WARNING: {IMPORT_SRC} not found. Place it here before running setup.")

# 2. Directory structure
for d in ["data", "data/logs", "data/logs/rejected", "data/logs/daily"]:
    os.makedirs(d, exist_ok=True)
    print(f"  Created: {d}/")

# 3. Stage Excel
if os.path.exists(IMPORT_SRC):
    shutil.copy(IMPORT_SRC, IMPORT_DST)
    print(f"  Staged:  {IMPORT_SRC} -> {IMPORT_DST}")

# 4. Install dependencies
print()
print("Installing dependencies...")
subprocess.check_call([sys.executable, "-m", "pip", "install",
    "flask", "apscheduler", "openpyxl", "werkzeug", "--quiet"])
print("  Done.")

# 5. Initialise database
print()
print("Initialising database...")
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("GAME_SECRET_KEY", "setup-temp-key")
from database import init_db
init_db()
print("  data/game.db created.")

# 6. Apply protagonist column migrations
print()
print("Applying schema migrations...")
import sqlite3
conn = sqlite3.connect("data/game.db")
migrations = [
    "ALTER TABLE master ADD COLUMN protagonist_name              TEXT",
    "ALTER TABLE master ADD COLUMN protagonist_weapon_id         INTEGER REFERENCES weapons(id)",
    "ALTER TABLE master ADD COLUMN protagonist_armor_id          INTEGER REFERENCES armor(id)",
    "ALTER TABLE master ADD COLUMN protagonist_special_item_id   INTEGER REFERENCES special_items(id)",
]
for sql in migrations:
    col = sql.split("ADD COLUMN")[1].strip().split()[0]
    try:
        conn.execute(sql); conn.commit()
        print(f"  Added:   {col}")
    except sqlite3.OperationalError:
        print(f"  Exists:  {col}")
conn.close()

# 7. Import content
if os.path.exists(IMPORT_DST):
    print()
    print("Importing game content...")
    from app import create_app
    app = create_app()
    with app.app_context():
        from importer import run_import
        result = run_import(IMPORT_DST)
        if result["success"]:
            print("  Import successful!")
            for sheet, counts in result["summary"].items():
                print(f"    {sheet}: {counts}")
        else:
            print("  Import FAILED:")
            for err in result["errors"]:
                print(f"    ERROR: {err}")
else:
    print()
    print("No content staged. Place the game-content workbook here and re-run.")

print()
print("=== Setup Complete ===")
print()
print("Next steps:")
print("  export GAME_SECRET_KEY=\'replace-with-a-random-secret\'")
print("  export ADMIN_PASSWORD=\'your-chosen-password\'")
print("  python run.py")
print("  # In a second terminal:")
print("  flask --app admin:create_admin_app run --port 5001")
print()
print("  Game:  http://localhost:5000")
print("  Admin: http://localhost:5001/admin")
'''

RUN_PY = '''#!/usr/bin/env python3
"""
run.py — Development entry point.

Production:
  gunicorn "app:create_app()" --bind 0.0.0.0:5000 --workers 1
  Single worker only — SQLite + APScheduler are not multi-process safe.

Environment variables:
  GAME_SECRET_KEY  — Flask secret key (required in production)
  ADMIN_PASSWORD   — Admin panel HTTP Basic Auth password (optional)
"""
import logging, os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

if not os.environ.get("GAME_SECRET_KEY"):
    logging.warning(
        "GAME_SECRET_KEY not set — using insecure default. "
        "Set this before exposing to a network."
    )

from app import create_app
app = create_app()

if __name__ == "__main__":
    app.run(
        debug=True,
        use_reloader=False,  # Prevents APScheduler from running twice in debug mode
        port=5000,
        host="127.0.0.1"
    )
'''

SUMMARY = """
Phase 15 — Pre-Launch Consolidation
=====================================

Decisions:
  UTC midnight reset    — no scheduler change needed
  Starting credits: 50  — update config_defaults.py: STARTING_CREDITS = 50
  PvP protection        — no change needed (already correct)
  Secret key            — replace-with-a-random-secret

Files to patch:
  config_defaults.py  — STARTING_CREDITS = 50
  admin.py            — add check_admin_auth before_request
  schema.sql          — add protagonist columns to master table
  run.py              — replace with updated version above

New files:
  setup.py            — one-shot setup (run before first launch)

Launch sequence:
  1. Place GameContent Filled.xlsx in the project root
  2. python setup.py
  3. export GAME_SECRET_KEY=replace-with-a-random-secret
  4. export ADMIN_PASSWORD=your-chosen-password
  5. python run.py                                          (terminal 1)
  6. flask --app admin:create_admin_app run --port 5001    (terminal 2)
  7. http://localhost:5000  — register first player
  8. http://localhost:5001/admin — verify import, check content tables
"""
