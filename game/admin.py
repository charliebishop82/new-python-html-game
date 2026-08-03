# admin.py  (Phase 8)
# Separate Flask app for admin tools.
# Run with: flask --app admin:create_admin_app run --port 5001
# Localhost only — never expose publicly.

import math
import logging
import os
import re
import uuid
from datetime import datetime

from flask import (Flask, render_template, request, redirect,
                   url_for, g, jsonify, Response)
from werkzeug.security import generate_password_hash

import config_defaults as cfg
from database import (execute, execute_one, execute_write,
                      exclusive_transaction, init_db, close_db,
                      get_all_settings)

logger = logging.getLogger(__name__)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


# ─────────────────────────────────────────────────────────────────────────────
# APP FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def create_admin_app() -> Flask:
    init_db()
    app = Flask(__name__, template_folder="templates")
    app.secret_key = cfg.SECRET_KEY + "-admin"
    app.teardown_appcontext(close_db)

    @app.before_request
    def check_admin_auth():
        if not ADMIN_PASSWORD:
            return None
        auth = request.authorization
        if not auth or auth.password != ADMIN_PASSWORD:
            return Response(
                "Admin access required.", 401,
                {"WWW-Authenticate": 'Basic realm="Admin"'}
            )
        return None

    _register_routes(app)
    return app


def _register_routes(app: Flask):
    app.add_url_rule("/admin",                        "admin_index",        admin_index)
    app.add_url_rule("/admin/import",                 "admin_import",       admin_import,        methods=["GET","POST"])
    app.add_url_rule("/admin/players",                "admin_players",      admin_players)
    app.add_url_rule("/admin/players/<int:pid>",      "admin_player_detail",admin_player_detail)
    app.add_url_rule("/admin/players/<int:pid>/ban",  "admin_ban",          admin_ban,           methods=["POST"])
    app.add_url_rule("/admin/players/<int:pid>/edit", "admin_edit",         admin_edit,          methods=["POST"])
    app.add_url_rule("/admin/config",                 "admin_config",       admin_config,        methods=["GET","POST"])
    app.add_url_rule("/admin/reset/midnight",         "admin_midnight",     admin_midnight,      methods=["POST"])
    app.add_url_rule("/admin/reset/full",             "admin_full_reset",   admin_full_reset,    methods=["POST"])
    app.add_url_rule("/admin/logs",                   "admin_logs",         admin_logs)
    app.add_url_rule("/admin/npcs",                   "admin_npcs",         admin_npcs,          methods=["GET","POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/edit",    "admin_npc_edit",     admin_npc_edit,      methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/run",     "admin_npc_run",      admin_npc_run,       methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/spend-ap", "admin_npc_spend_ap", admin_npc_spend_ap, methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/retire",  "admin_npc_retire",   admin_npc_retire,    methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/inventory/grant", "admin_npc_grant", admin_npc_grant, methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/inventory/<int:inv_id>/remove", "admin_npc_remove", admin_npc_remove, methods=["POST"])


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

def admin_index():
    import os
    player_count  = execute_one("SELECT COUNT(*) as cnt FROM players WHERE is_banned = 0")["cnt"]
    active_combat = execute_one("SELECT COUNT(*) as cnt FROM combat_sessions WHERE status='ACTIVE'")["cnt"]
    pending_import = os.path.exists(cfg.PENDING_IMPORT_PATH)
    queue_failed   = execute_one("SELECT COUNT(*) as cnt FROM action_queue WHERE status='FAILED'")["cnt"]
    boss_count     = execute_one("SELECT COUNT(*) as cnt FROM bosses WHERE is_active=1")["cnt"]
    special_pool   = execute_one(
        "SELECT COUNT(*) as cnt FROM special_item_registry WHERE status='IN_POOL'"
    )["cnt"]

    recent_errors = []
    if os.path.exists(cfg.IMPORT_ERROR_LOG):
        with open(cfg.IMPORT_ERROR_LOG) as f:
            recent_errors = f.readlines()[-10:]

    return render_template("admin/dashboard.html",
        player_count=player_count,
        active_combat=active_combat,
        pending_import=pending_import,
        queue_failed=queue_failed,
        boss_count=boss_count,
        special_pool=special_pool,
        recent_errors=recent_errors,
        now=datetime.utcnow().isoformat()
    )


# ─────────────────────────────────────────────────────────────────────────────
# IMPORT
# ─────────────────────────────────────────────────────────────────────────────

def admin_import():
    import os, shutil
    feedback = error = None

    if request.method == "POST":
        file = request.files.get("excel_file")
        if not file or not file.filename.endswith(".xlsx"):
            error = "Please upload a valid .xlsx file."
        else:
            os.makedirs(os.path.dirname(cfg.PENDING_IMPORT_PATH), exist_ok=True)
            file.save(cfg.PENDING_IMPORT_PATH)
            feedback = f"File staged at {cfg.PENDING_IMPORT_PATH}. Will be applied at next midnight reset."

    pending = os.path.exists(cfg.PENDING_IMPORT_PATH)
    return render_template("admin/import.html",
                           pending=pending, feedback=feedback, error=error)


# ─────────────────────────────────────────────────────────────────────────────
# PLAYERS
# ─────────────────────────────────────────────────────────────────────────────

def admin_players():
    players = execute(
        """SELECT p.*, ps.pvp_kills, ps.times_reduced_to_1hp,
                  CASE WHEN np.player_id IS NULL THEN 0 ELSE 1 END AS is_npc
           FROM players p
           LEFT JOIN player_stats ps ON ps.player_id = p.id
           LEFT JOIN npc_profiles np ON np.player_id = p.id
           ORDER BY p.level DESC, p.xp DESC"""
    )
    return render_template("admin/players.html", players=players)


def admin_player_detail(pid: int):
    player    = execute_one("SELECT * FROM players WHERE id = ?", (pid,))
    if not player:
        return redirect(url_for("admin_players"))
    stats     = execute_one("SELECT * FROM player_stats WHERE player_id = ?", (pid,))
    inventory = execute(
        "SELECT ii.*, "
        "CASE ii.item_type WHEN 'WEAPON' THEN w.name WHEN 'ARMOR' THEN a.name ELSE si.name END as item_name "
        "FROM inventory_items ii "
        "LEFT JOIN weapons w ON w.id = ii.item_id AND ii.item_type='WEAPON' "
        "LEFT JOIN armor   a ON a.id = ii.item_id AND ii.item_type='ARMOR' "
        "LEFT JOIN special_items si ON si.id = ii.item_id AND ii.item_type='SPECIAL' "
        "WHERE ii.player_id = ?", (pid,)
    )
    history   = execute(
        "SELECT * FROM item_history WHERE player_id = ? ORDER BY occurred_at DESC LIMIT 50", (pid,)
    )
    boss_kills = execute(
        """SELECT b.name, bi.kill_count, bi.discovered_at
           FROM boss_instances bi JOIN bosses b ON b.id = bi.boss_id
           WHERE bi.player_id = ? ORDER BY bi.kill_count DESC""", (pid,)
    )
    return render_template("admin/player_detail.html",
                           player=player, stats=stats,
                           inventory=inventory, history=history,
                           boss_kills=boss_kills,
                           feedback=request.args.get("feedback"),
                           error=request.args.get("error"))


# ─────────────────────────────────────────────────────────────────────────────
# BAN
# ─────────────────────────────────────────────────────────────────────────────

def admin_ban(pid: int):
    action = request.form.get("action", "ban")

    if action == "unban":
        with exclusive_transaction():
            execute_write("UPDATE players SET is_banned = 0 WHERE id = ?", (pid,))
        return redirect(url_for("admin_player_detail", pid=pid, feedback="Player unbanned."))

    # Ban: wipe credits, remove gear, return specials to pool, clear in_combat
    player = execute_one("SELECT * FROM players WHERE id = ?", (pid,))
    if not player:
        return redirect(url_for("admin_players"))

    with exclusive_transaction():
        execute_write("UPDATE players SET is_banned = 1, credits = 0, in_combat = 0, "
                      "equipped_weapon_id = NULL, equipped_armor_id = NULL, "
                      "equipped_special_id = NULL WHERE id = ?", (pid,))

        # Return any special items to pool
        specials = execute(
            "SELECT * FROM inventory_items WHERE player_id = ? AND item_type = 'SPECIAL'", (pid,)
        )
        for s in specials:
            execute_write(
                """UPDATE special_item_registry
                   SET status='IN_POOL', current_owner_player_id=NULL,
                       inventory_item_id=NULL, last_released_method='BANNED',
                       updated_at=?
                   WHERE special_item_id=?""",
                (datetime.utcnow().isoformat(), s["item_id"])
            )

        # Delete all inventory
        execute_write("DELETE FROM inventory_items WHERE player_id = ?", (pid,))

        # Cancel any active combat sessions
        execute_write(
            """UPDATE combat_sessions SET status='CANCELLED', result='CANCELLED'
               WHERE (attacker_player_id=? OR defender_player_id=?) AND status='ACTIVE'""",
            (pid, pid)
        )

    logger.info("Admin: banned player id=%d", pid)
    return redirect(url_for("admin_player_detail", pid=pid, feedback="Player banned."))


# ─────────────────────────────────────────────────────────────────────────────
# EDIT PLAYER
# ─────────────────────────────────────────────────────────────────────────────

def admin_edit(pid: int):
    """Manual field edits — credits, HP, AP, stat overrides."""
    fields = {}
    for field in ("credits", "current_hp", "current_ap",
                  "str_stat", "end_stat", "agi_stat", "lck_stat", "per_stat", "level", "xp"):
        val = request.form.get(field)
        if val is not None and val.strip() != "":
            try:
                fields[field] = max(0, int(val))
            except ValueError:
                pass

    if fields:
        sets   = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [pid]
        with exclusive_transaction():
            execute_write(f"UPDATE players SET {sets} WHERE id = ?", values)
        logger.info("Admin: edited player id=%d fields=%s", pid, list(fields.keys()))

    return redirect(url_for("admin_player_detail", pid=pid, feedback="Player updated."))


# NPC MANAGEMENT
def admin_npcs():
    if request.method == "POST":
        try:
            pid = _create_npc(request.form)
            return redirect(url_for("admin_npcs", feedback=f"NPC created (player {pid})."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("admin_npcs", error=str(exc)))

    npcs = execute(
        """SELECT p.*,np.*,c.name class_name,
                  (SELECT COUNT(*) FROM inventory_items ii WHERE ii.player_id=p.id AND ii.item_type='SPECIAL') special_count
           FROM npc_profiles np JOIN players p ON p.id=np.player_id
           LEFT JOIN classes c ON c.id=p.class_id ORDER BY np.retired,p.level DESC,p.character_name"""
    )
    classes = execute("SELECT id,name FROM classes WHERE is_active=1 ORDER BY name")
    items = execute(
        """SELECT 'WEAPON' item_type,id,name,level,credit_cost FROM weapons WHERE is_active=1
           UNION ALL SELECT 'ARMOR',id,name,level,credit_cost FROM armor WHERE is_active=1
           UNION ALL SELECT 'SPECIAL',id,name,1 AS level,credit_cost FROM special_items WHERE is_active=1
           ORDER BY item_type,level,name"""
    )
    logs = execute(
        """SELECT nal.*,p.character_name FROM npc_action_log nal JOIN players p ON p.id=nal.player_id
           ORDER BY nal.id DESC LIMIT 50"""
    )
    inventory = execute(
        """SELECT ii.*,CASE ii.item_type WHEN 'WEAPON' THEN w.name WHEN 'ARMOR' THEN a.name ELSE si.name END item_name
           FROM inventory_items ii LEFT JOIN weapons w ON w.id=ii.item_id AND ii.item_type='WEAPON'
           LEFT JOIN armor a ON a.id=ii.item_id AND ii.item_type='ARMOR'
           LEFT JOIN special_items si ON si.id=ii.item_id AND ii.item_type='SPECIAL'
           WHERE ii.player_id IN (SELECT player_id FROM npc_profiles) ORDER BY ii.player_id,ii.item_type"""
    )
    return render_template("admin/npcs.html", npcs=npcs, classes=classes, items=items,
                           inventory=inventory, logs=logs)


def admin_npc_edit(pid: int):
    fields = {}
    for name in ("player_hunter", "boss_killer", "hoarder", "thief", "aggression",
                 "self_preservation", "repair_tendency"):
        fields[name] = max(0, min(100, request.form.get(name, type=int, default=0)))
    fields["enabled"] = 1 if request.form.get("enabled") else 0
    with exclusive_transaction():
        execute_write(
            """UPDATE npc_profiles SET player_hunter=?,boss_killer=?,hoarder=?,thief=?,aggression=?,
               self_preservation=?,repair_tendency=?,enabled=? WHERE player_id=?""",
            (*fields.values(), pid)
        )
    return redirect(url_for("admin_npcs", feedback="NPC behavior updated."))


def admin_npc_run(pid: int):
    from npc import run_npc_turn
    try:
        result = run_npc_turn(pid)
        return redirect(url_for("admin_npcs", feedback=f"NPC turn: {result['decision']} - {result['result']}"))
    except Exception as exc:
        logger.exception("Manual NPC turn failed for %d", pid)
        return redirect(url_for("admin_npcs", error=str(exc)))


def admin_npc_spend_ap(pid: int):
    from npc import spend_npc_ap_now
    try:
        result = spend_npc_ap_now(pid)
        return redirect(url_for(
            "admin_npcs",
            feedback=(f"NPC ran {result['decisions']} decision(s) and spent "
                      f"{result['ap_spent']} AP; {result['ap_remaining']} AP remains.")
        ))
    except Exception as exc:
        logger.exception("Immediate NPC AP spending failed for %d", pid)
        return redirect(url_for("admin_npcs", error=str(exc)))


def admin_npc_retire(pid: int):
    from npc import retire_npc
    retire_npc(pid)
    return redirect(url_for("admin_npcs", feedback="NPC retired; unique specials returned to the pool."))


def admin_npc_grant(pid: int):
    try:
        item_type, raw_item_id = request.form.get("item_key", "").upper().split(":", 1)
        item_id = int(raw_item_id)
    except (TypeError, ValueError):
        return redirect(url_for("admin_npcs", error="Invalid inventory item."))
    table = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}.get(item_type)
    if not table or not item_id:
        return redirect(url_for("admin_npcs", error="Invalid inventory item."))
    item = execute_one(f"SELECT * FROM {table} WHERE id=? AND is_active=1", (item_id,))
    if not item:
        return redirect(url_for("admin_npcs", error="Content item not found."))
    if item_type == "SPECIAL":
        registry = execute_one("SELECT * FROM special_item_registry WHERE special_item_id=?", (item_id,))
        if not registry or registry["status"] != "IN_POOL":
            return redirect(url_for("admin_npcs", error="That special item is not currently available."))
    with exclusive_transaction():
        inv_id = execute_write(
            """INSERT INTO inventory_items(player_id,item_type,item_id,current_durability,acquired_method)
               VALUES(?,?,?,?, 'ADMIN_GRANT')""", (pid, item_type, item_id, item.get("starting_durability", 100))
        )
        execute_write(
            """INSERT INTO item_history(player_id,item_type,item_id,item_name,event_type)
               VALUES(?,?,?,?, 'ADMIN_GRANTED')""", (pid, item_type, item_id, item["name"])
        )
        if item_type == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry SET status='IN_INVENTORY',current_owner_player_id=?,
                   inventory_item_id=?,last_acquired_method='ADMIN_GRANT',updated_at=? WHERE special_item_id=?""",
                (pid, inv_id, datetime.utcnow().isoformat(), item_id)
            )
    return redirect(url_for("admin_npcs", feedback=f"Granted {item['name']}."))


def admin_npc_remove(pid: int, inv_id: int):
    item = execute_one("SELECT * FROM inventory_items WHERE id=? AND player_id=?", (inv_id, pid))
    if not item:
        return redirect(url_for("admin_npcs", error="Inventory item not found."))
    with exclusive_transaction():
        execute_write(
            """UPDATE players SET equipped_weapon_id=CASE WHEN equipped_weapon_id=? THEN NULL ELSE equipped_weapon_id END,
               equipped_armor_id=CASE WHEN equipped_armor_id=? THEN NULL ELSE equipped_armor_id END,
               equipped_special_id=CASE WHEN equipped_special_id=? THEN NULL ELSE equipped_special_id END WHERE id=?""",
            (inv_id, inv_id, inv_id, pid)
        )
        execute_write("DELETE FROM inventory_items WHERE id=?", (inv_id,))
        if item["item_type"] == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry SET status='IN_POOL',current_owner_player_id=NULL,
                   inventory_item_id=NULL,last_released_method='ADMIN_REMOVED',updated_at=? WHERE special_item_id=?""",
                (datetime.utcnow().isoformat(), item["item_id"])
            )
    return redirect(url_for("admin_npcs", feedback="Inventory item removed."))


def _create_npc(form) -> int:
    name = form.get("character_name", "").strip()
    if not name:
        raise ValueError("NPC character name is required.")
    class_id = form.get("class_id", type=int)
    cls = execute_one("SELECT * FROM classes WHERE id=? AND is_active=1", (class_id,))
    if not cls:
        raise ValueError("Select an active class.")
    level = max(2, min(3, form.get("level", type=int, default=3)))
    scores = _npc_scores_from_form(form)
    # Balanced creation allocation plus one earned point per level after first.
    stat_points = get_all_settings().get("STARTING_STAT_POINTS", cfg.STARTING_STAT_POINTS)
    alloc = [0, 0, 0, 0, 0]
    for i in range(stat_points): alloc[i % 5] += 1
    for i in range(level - 1): alloc[i % 5] += 1
    stats = [1 + cls[key] + alloc[i] for i, key in enumerate(
        ("str_bonus", "end_bonus", "agi_bonus", "lck_bonus", "per_bonus"))]
    max_hp = 10 + stats[1] + 5 * level
    current_ap = get_all_settings().get("BASE_DAILY_AP", cfg.BASE_DAILY_AP) + math.floor(stats[1] / 2)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "npc"
    username = f"npc_{slug}_{uuid.uuid4().hex[:6]}"
    email = f"{username}@npc.local"
    with exclusive_transaction():
        pid = execute_write(
            """INSERT INTO players(username,password_hash,email,character_name,sex,class_id,
               str_stat,end_stat,agi_stat,lck_stat,per_stat,level,xp,current_hp,current_ap,credits)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (username, generate_password_hash(uuid.uuid4().hex), email, name, form.get("sex", "Other"),
             class_id, *stats, level, 0, max_hp, current_ap, max(100, cfg.STARTING_CREDITS))
        )
        execute_write("INSERT INTO player_stats(player_id) VALUES(?)", (pid,))
        execute_write(
            """INSERT INTO npc_profiles(player_id,player_hunter,boss_killer,hoarder,thief,aggression,
               self_preservation,repair_tendency) VALUES(?,?,?,?,?,?,?,?)""",
            (pid, *scores)
        )
    from routes.auth import _award_starter_gear
    from npc import _equip_best_core_items
    _award_starter_gear(pid)
    _equip_best_core_items(pid)
    return pid


def _npc_scores_from_form(form):
    preset = form.get("preset", "custom")
    presets = {
        "hunter": (100, 0, 0, 0), "boss": (0, 100, 0, 0),
        "hoarder": (0, 0, 100, 0), "thief": (0, 0, 0, 100),
        "hybrid": (60, 60, 60, 0),
    }
    motivations = presets.get(preset, tuple(max(0, min(100, form.get(k, type=int, default=0)))
                                            for k in ("player_hunter", "boss_killer", "hoarder", "thief")))
    return (*motivations,
            max(0, min(100, form.get("aggression", type=int, default=50))),
            max(0, min(100, form.get("self_preservation", type=int, default=50))),
            max(0, min(100, form.get("repair_tendency", type=int, default=50))))


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def admin_config():
    feedback = error = None

    if request.method == "POST":
        constant = request.form.get("constant_name", "").strip()
        value    = request.form.get("value", "").strip()
        if constant and value:
            with exclusive_transaction():
                execute_write(
                    """INSERT OR REPLACE INTO settings (constant_name, value, imported_at)
                       VALUES (?, ?, ?)""",
                    (constant, value, datetime.utcnow().isoformat())
                )
            feedback = f"Setting '{constant}' updated to '{value}'."
        else:
            error = "Both constant name and value are required."

    settings_rows = execute("SELECT * FROM settings ORDER BY constant_name")
    defaults      = {k: v for k, v in vars(cfg).items()
                     if k.isupper() and not k.startswith("_")}
    return render_template("admin/config.html",
                           settings_rows=settings_rows,
                           defaults=defaults,
                           feedback=feedback,
                           error=error)


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL MIDNIGHT RESET
# ─────────────────────────────────────────────────────────────────────────────

def admin_midnight():
    from scheduler import midnight_reset
    try:
        midnight_reset()
        return redirect(url_for("admin_index") + "?feedback=Midnight+reset+complete.")
    except Exception as e:
        logger.exception("Admin triggered midnight reset failed")
        return redirect(url_for("admin_index") + f"?error={str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# FULL GAME RESET
# ─────────────────────────────────────────────────────────────────────────────

def admin_full_reset():
    """Wipe all player data, reinitialise schema, re-import Excel if staged."""
    confirm = request.form.get("confirm", "")
    if confirm != "RESET":
        return redirect(
            url_for("admin_index") + "?error=Full+reset+requires+typing+RESET+to+confirm."
        )

    import sqlite3, os

    logger.warning("Admin: initiating FULL GAME RESET")

    # Drop all operational tables (content tables survive)
    operational = [
        "combat_buffs", "combat_logs", "combat_sessions",
        "boss_instances", "minion_instances", "boss_intel",
        "inventory_items", "item_history", "special_item_registry",
        "shop_listings", "daily_feed", "action_queue",
        "player_stats", "level_up_history", "status_effects", "players",
    ]
    conn = sqlite3.connect(cfg.DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    for tbl in operational:
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()

    # Reinitialise schema (recreates dropped tables)
    init_db()

    # Rebuild special_item_registry from existing special_items content
    with exclusive_transaction():
        specials = execute("SELECT id FROM special_items WHERE is_active = 1")
        for s in specials:
            execute_write(
                "INSERT OR IGNORE INTO special_item_registry (special_item_id, status) VALUES (?, 'IN_POOL')",
                (s["id"],)
            )

    # Re-import if staged file exists
    if os.path.exists(cfg.PENDING_IMPORT_PATH):
        from importer import run_import
        result = run_import(cfg.PENDING_IMPORT_PATH, full_reset=True)
        logger.info("Post-reset import: %s", result)

    logger.warning("Admin: FULL GAME RESET complete")
    return redirect(url_for("admin_index") + "?feedback=Full+game+reset+complete.")


# ─────────────────────────────────────────────────────────────────────────────
# LOGS
# ─────────────────────────────────────────────────────────────────────────────

def admin_logs():
    import os

    def read_tail(path: str, n: int = 100) -> list[str]:
        if not os.path.exists(path):
            return []
        with open(path, "r") as f:
            return f.readlines()[-n:]

    import_errors = read_tail(cfg.IMPORT_ERROR_LOG)
    orphan_log    = read_tail(cfg.ORPHAN_LOG)
    failed_queue  = execute(
        "SELECT * FROM action_queue WHERE status='FAILED' ORDER BY created_at DESC LIMIT 50"
    )

    return render_template("admin/logs.html",
                           import_errors=import_errors,
                           orphan_log=orphan_log,
                           failed_queue=failed_queue)


################################################################################
