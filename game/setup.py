#!/usr/bin/env python3
"""
setup.py
Run once before first launch.
Creates directories, installs dependencies, initialises DB, imports content.
"""
import os, sys, subprocess, shutil

print("=== Game Setup ===")
print()

# 1. Check for Excel
IMPORT_SRC = "GameContent_Filled.xlsx"
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
    print("No content staged. Place GameContent_Filled.xlsx and re-run.")

print()
print("=== Setup Complete ===")
print()
print("Next steps:")
print("  export GAME_SECRET_KEY='80489f7f9c611d9322c97a791a55f5df6e1ea9632f743d4f16c254088b1141c8'")
print("  export ADMIN_PASSWORD='your-chosen-password'")
print("  python run.py")
print("  # In a second terminal:")
print("  flask --app admin:create_admin_app run --port 5001")
print()
print("  Game:  http://localhost:5000")
print("  Admin: http://localhost:5001/admin")
