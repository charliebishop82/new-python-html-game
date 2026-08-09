import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GAME = os.path.join(ROOT, "game")
sys.path.insert(0, GAME)
os.chdir(GAME)

import config_defaults as cfg

temp_root = os.path.join(ROOT, ".codex_tmp", "verification")
os.makedirs(temp_root, exist_ok=True)
cfg.DB_PATH = os.path.join(temp_root, "game.db")
cfg.REJECTED_IMPORT_PATH = os.path.join(temp_root, "rejected")
cfg.IMPORT_ERROR_LOG = os.path.join(temp_root, "import_errors.log")

from flask import Flask
from database import execute, execute_one, init_db, close_db
from importer import run_import

source = os.path.join(ROOT, "data", "GameContent_Perks_Worldbosses.xlsx")
staged = os.path.join(temp_root, "pending_import.xlsx")
if os.path.exists(cfg.DB_PATH):
    os.remove(cfg.DB_PATH)
shutil.copy2(source, staged)

app = Flask(__name__)
app.teardown_appcontext(close_db)
with app.app_context():
    init_db()
    result = run_import(staged)
    assert result["success"], result
    assert execute_one("SELECT COUNT(*) n FROM perks")["n"] == 23
    assert execute_one("SELECT COUNT(*) n FROM world_bosses")["n"] == 10
    assert execute_one("SELECT COUNT(*) n FROM world_boss_loot")["n"] == 10
    assert execute_one("SELECT COUNT(*) n FROM classes WHERE description<>''")["n"] == 5
    assert execute_one("SELECT COUNT(*) n FROM random_events WHERE flavor_text<>''")["n"] > 0
    print(result["summary"])
    print("perks", execute_one("SELECT COUNT(*) n FROM perks")["n"])
    print("world_bosses", execute_one("SELECT COUNT(*) n FROM world_bosses")["n"])
    print("world_boss_loot", execute_one("SELECT COUNT(*) n FROM world_boss_loot")["n"])
