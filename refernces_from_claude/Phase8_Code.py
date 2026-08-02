################################################################################
# PHASE 8 CODE — Admin App
# BBS-Inspired Multiplayer Dueling Game
#
# Files included:
#   1. admin.py                  — Separate Flask admin app (localhost only)
#   2. templates/admin/          — All admin templates (combined in one file):
#      base_admin.html, dashboard.html, import.html, players.html,
#      player_detail.html, config.html, logs.html
#
# Run the admin app separately:
#   flask --app admin:create_admin_app run --port 5001
#
# NEVER expose port 5001 publicly — bind to localhost only.
################################################################################

################################################################################
# FILE: admin.py (Phase 8 — full admin app)
################################################################################

# admin.py  (Phase 8)
# Separate Flask app for admin tools.
# Run with: flask --app admin:create_admin_app run --port 5001
# Localhost only — never expose publicly.

import math
import logging
from datetime import datetime

from flask import (Flask, render_template, request, redirect,
                   url_for, g, jsonify)

import config_defaults as cfg
from database import (execute, execute_one, execute_write,
                      exclusive_transaction, init_db, close_db,
                      get_all_settings)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# APP FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def create_admin_app() -> Flask:
    app = Flask(__name__, template_folder="templates/admin")
    app.secret_key = cfg.SECRET_KEY + "-admin"
    app.teardown_appcontext(close_db)
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
        """SELECT p.*, ps.pvp_kills, ps.times_reduced_to_1hp
           FROM players p
           LEFT JOIN player_stats ps ON ps.player_id = p.id
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
# FILE: templates/admin/ (all admin templates)
################################################################################

<!-- ============================================================ -->
<!-- FILE: templates/admin/base_admin.html                      -->
<!-- ============================================================ -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Admin — {% block title %}Dashboard{% endblock %}</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Courier New', monospace; background: #0a0a0a;
               color: #dddddd; font-size: 13px; }
        #admin-wrap { display: flex; min-height: 100vh; }
        #admin-nav  { width: 180px; background: #111; border-right: 1px solid #222;
                      padding: 16px 12px; flex-shrink: 0; }
        #admin-nav h2 { color: #ffaa00; font-size: 13px; margin-bottom: 16px;
                        text-transform: uppercase; letter-spacing: 1px; }
        #admin-nav a  { display: block; color: #666; text-decoration: none;
                        padding: 5px 0; font-size: 12px; }
        #admin-nav a:hover { color: #fff; }
        #admin-main { flex: 1; padding: 24px; overflow-y: auto; }
        h1 { color: #ffaa00; font-size: 16px; margin-bottom: 16px; }
        h2 { color: #4499ff; font-size: 14px; margin: 20px 0 10px; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
        th { background: #1a1a1a; color: #ffaa00; padding: 6px 10px;
             text-align: left; border: 1px solid #222; }
        td { padding: 5px 10px; border: 1px solid #1a1a1a; }
        tr:nth-child(even) td { background: #0d0d0d; }
        .btn { background: #1a1a1a; color: #00cc66; border: 1px solid #222;
               padding: 5px 14px; cursor: pointer; font-family: inherit;
               font-size: 12px; text-decoration: none; display: inline-block; }
        .btn:hover { border-color: #00cc66; }
        .btn-danger { color: #cc2222; }
        .btn-danger:hover { border-color: #cc2222; }
        .feedback { color: #00cc66; margin-bottom: 12px; }
        .error    { color: #cc2222; margin-bottom: 12px; }
        input, select, textarea { background: #1a1a1a; border: 1px solid #333;
                                   color: #ddd; padding: 5px 8px; font-family: inherit;
                                   font-size: 12px; }
        input:focus, select:focus { border-color: #4499ff; outline: none; }
        .stat-grid { display: grid; grid-template-columns: repeat(5,1fr); gap: 8px; }
        .stat-box  { background: #111; border: 1px solid #222; padding: 8px;
                     text-align: center; }
        .stat-val  { color: #ffaa00; font-size: 18px; display: block; }
        .stat-lbl  { color: #666; font-size: 10px; }
    </style>
</head>
<body>
<div id="admin-wrap">
    <nav id="admin-nav">
        <h2>⚙ Admin</h2>
        <a href="/admin">Dashboard</a>
        <a href="/admin/import">Import Excel</a>
        <a href="/admin/players">Players</a>
        <a href="/admin/config">Config</a>
        <a href="/admin/logs">Logs</a>
        <br>
        <form method="POST" action="/admin/reset/midnight"
              onsubmit="return confirm('Trigger midnight reset now?');">
            <button type="submit" class="btn" style="width:100%;margin-top:8px;">
                ↺ Midnight Reset
            </button>
        </form>
    </nav>
    <main id="admin-main">
        {% if request.args.get('feedback') %}
        <div class="feedback">✓ {{ request.args.get('feedback') }}</div>
        {% endif %}
        {% if request.args.get('error') %}
        <div class="error">⚠ {{ request.args.get('error') }}</div>
        {% endif %}
        {% block content %}{% endblock %}
    </main>
</div>
</body>
</html>


<!-- ============================================================ -->
<!-- FILE: templates/admin/dashboard.html                        -->
<!-- ============================================================ -->
{% extends "admin/base_admin.html" %}
{% block title %}Dashboard{% endblock %}
{% block content %}
<h1>Admin Dashboard</h1>
<p style="color:#666;margin-bottom:16px;">{{ now }} UTC</p>

<div class="stat-grid" style="margin-bottom:24px;">
    <div class="stat-box">
        <span class="stat-val">{{ player_count }}</span>
        <span class="stat-lbl">Active Players</span>
    </div>
    <div class="stat-box">
        <span class="stat-val">{{ active_combat }}</span>
        <span class="stat-lbl">Active Fights</span>
    </div>
    <div class="stat-box">
        <span class="stat-val" style="color:{% if pending_import %}#ffaa00{% else %}#666{% endif %}">
            {{ 'YES' if pending_import else 'NO' }}
        </span>
        <span class="stat-lbl">Pending Import</span>
    </div>
    <div class="stat-box">
        <span class="stat-val" style="color:{% if queue_failed %}#cc2222{% else %}#00cc66{% endif %}">
            {{ queue_failed }}
        </span>
        <span class="stat-lbl">Failed Queue Rows</span>
    </div>
    <div class="stat-box">
        <span class="stat-val">{{ special_pool }}</span>
        <span class="stat-lbl">Specials In Pool</span>
    </div>
</div>

{% if recent_errors %}
<h2>Recent Import Errors</h2>
<div style="background:#0d0d0d;padding:10px;border:1px solid #222;
            font-size:11px;color:#cc2222;max-height:150px;overflow-y:auto;">
    {% for line in recent_errors %}{{ line }}{% endfor %}
</div>
{% endif %}

<h2>Danger Zone</h2>
<form method="POST" action="/admin/reset/full"
      onsubmit="return confirm('⚠ THIS WIPES ALL PLAYER DATA. Are you absolutely sure?');"
      style="display:flex;gap:8px;align-items:center;">
    <input type="text" name="confirm" placeholder='Type RESET to confirm' style="width:220px;">
    <button type="submit" class="btn btn-danger">Full Game Reset</button>
</form>
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/admin/import.html                           -->
<!-- ============================================================ -->
{% extends "admin/base_admin.html" %}
{% block title %}Import{% endblock %}
{% block content %}
<h1>Excel Import</h1>

{% if feedback %}<div class="feedback">✓ {{ feedback }}</div>{% endif %}
{% if error %}<div class="error">⚠ {{ error }}</div>{% endif %}

<p style="color:#666;margin-bottom:16px;">
    Upload a new GameContent_Template.xlsx to stage it for the next midnight reset.
    Validation errors will reject the entire file without changing live content.
</p>

{% if pending %}
<div style="color:#ffaa00;margin-bottom:12px;">
    ⚠ A staged file is already waiting at <code>{{ cfg.PENDING_IMPORT_PATH if cfg else 'data/pending_import.xlsx' }}</code>.
    Uploading a new file will replace it.
</div>
{% endif %}

<form method="POST" enctype="multipart/form-data">
    <div style="margin-bottom:12px;">
        <input type="file" name="excel_file" accept=".xlsx" required>
    </div>
    <button type="submit" class="btn">Stage for Next Midnight Reset</button>
</form>
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/admin/players.html                          -->
<!-- ============================================================ -->
{% extends "admin/base_admin.html" %}
{% block title %}Players{% endblock %}
{% block content %}
<h1>Players ({{ players|length }})</h1>

<table>
    <tr>
        <th>ID</th><th>Username</th><th>Character</th><th>Level</th>
        <th>HP</th><th>AP</th><th>Credits</th><th>PvP Kills</th>
        <th>Last Login</th><th>Status</th><th></th>
    </tr>
    {% for p in players %}
    <tr>
        <td style="color:#666">{{ p.id }}</td>
        <td>{{ p.username }}</td>
        <td>{{ p.character_name }}</td>
        <td>{{ p.level }}</td>
        <td>{{ p.current_hp }}</td>
        <td>{{ p.current_ap }}</td>
        <td>{{ p.credits }}</td>
        <td>{{ p.pvp_kills or 0 }}</td>
        <td style="font-size:11px;color:#666">
            {{ p.last_login_at[:10] if p.last_login_at else 'Never' }}
        </td>
        <td>
            {% if p.is_banned %}
            <span style="color:#cc2222">BANNED</span>
            {% elif p.in_combat %}
            <span style="color:#ffaa00">In Combat</span>
            {% else %}
            <span style="color:#666">Active</span>
            {% endif %}
        </td>
        <td>
            <a href="/admin/players/{{ p.id }}" class="btn">View</a>
        </td>
    </tr>
    {% endfor %}
</table>
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/admin/player_detail.html                    -->
<!-- ============================================================ -->
{% extends "admin/base_admin.html" %}
{% block title %}Player: {{ player.character_name }}{% endblock %}
{% block content %}
<h1>{{ player.character_name }} <span style="color:#666;font-size:13px">({{ player.username }})</span></h1>

{% if feedback %}<div class="feedback">✓ {{ feedback }}</div>{% endif %}
{% if error %}<div class="error">⚠ {{ error }}</div>{% endif %}

<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">

<div>
    <h2>Stats</h2>
    <table>
        <tr><td>Level</td><td>{{ player.level }}</td></tr>
        <tr><td>XP</td><td>{{ player.xp }}</td></tr>
        <tr><td>HP</td><td>{{ player.current_hp }}</td></tr>
        <tr><td>AP</td><td>{{ player.current_ap }}</td></tr>
        <tr><td>Credits</td><td>{{ player.credits }}</td></tr>
        <tr><td>STR/END/AGI/LCK/PER</td>
            <td>{{ player.str_stat }}/{{ player.end_stat }}/{{ player.agi_stat }}/{{ player.lck_stat }}/{{ player.per_stat }}</td>
        </tr>
        <tr><td>In Combat</td><td>{{ 'Yes' if player.in_combat else 'No' }}</td></tr>
        <tr><td>Banned</td><td>{{ 'Yes' if player.is_banned else 'No' }}</td></tr>
        <tr><td>Last Login</td><td>{{ player.last_login_at or 'Never' }}</td></tr>
    </table>

    <h2>Edit Fields</h2>
    <form method="POST" action="/admin/players/{{ player.id }}/edit">
        {% for field in ['credits','current_hp','current_ap','level','xp',
                         'str_stat','end_stat','agi_stat','lck_stat','per_stat'] %}
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <label style="width:100px;color:#666;font-size:11px;">{{ field }}</label>
            <input type="number" name="{{ field }}" min="0"
                   placeholder="{{ player[field] }}" style="width:80px;">
        </div>
        {% endfor %}
        <button type="submit" class="btn" style="margin-top:8px;">Save Changes</button>
    </form>
</div>

<div>
    <h2>Actions</h2>
    {% if player.is_banned %}
    <form method="POST" action="/admin/players/{{ player.id }}/ban">
        <input type="hidden" name="action" value="unban">
        <button type="submit" class="btn">Unban Player</button>
    </form>
    {% else %}
    <form method="POST" action="/admin/players/{{ player.id }}/ban"
          onsubmit="return confirm('Ban {{ player.username }}? This wipes credits, gear, and returns special items.');">
        <input type="hidden" name="action" value="ban">
        <button type="submit" class="btn btn-danger">Ban Player</button>
    </form>
    {% endif %}

    <h2>Boss Kill Records</h2>
    {% if boss_kills %}
    <table>
        <tr><th>Boss</th><th>Kills</th><th>First Seen</th></tr>
        {% for row in boss_kills %}
        <tr>
            <td>{{ row.name }}</td>
            <td>{{ row.kill_count }}</td>
            <td style="font-size:11px;color:#666">{{ row.discovered_at[:10] }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color:#666">No boss encounters yet.</p>
    {% endif %}
</div>
</div>

<h2>Inventory ({{ inventory|length }} items)</h2>
{% if inventory %}
<table>
    <tr><th>Item</th><th>Type</th><th>Durability</th><th>Acquired</th></tr>
    {% for item in inventory %}
    <tr>
        <td>{{ item.item_name or 'Unknown' }}</td>
        <td>{{ item.item_type }}</td>
        <td>{{ item.current_durability }}%</td>
        <td style="font-size:11px;color:#666">{{ item.acquired_method }}</td>
    </tr>
    {% endfor %}
</table>
{% else %}
<p style="color:#666">Empty inventory.</p>
{% endif %}

<h2>Recent Item History (last 50)</h2>
{% if history %}
<table>
    <tr><th>Date</th><th>Item</th><th>Event</th><th>Credits</th></tr>
    {% for h in history %}
    <tr>
        <td style="font-size:11px;color:#666">{{ h.occurred_at[:16] }}</td>
        <td>{{ h.item_name }}</td>
        <td>{{ h.event_type }}</td>
        <td>{{ h.credit_amount or '' }}</td>
    </tr>
    {% endfor %}
</table>
{% endif %}
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/admin/config.html                           -->
<!-- ============================================================ -->
{% extends "admin/base_admin.html" %}
{% block title %}Config{% endblock %}
{% block content %}
<h1>Game Config</h1>

{% if feedback %}<div class="feedback">✓ {{ feedback }}</div>{% endif %}
{% if error %}<div class="error">⚠ {{ error }}</div>{% endif %}

<p style="color:#666;margin-bottom:16px;">
    Edit individual constants. These take effect immediately (no reset needed).
    Changes here override Excel-imported values until the next import.
</p>

<form method="POST" style="margin-bottom:24px;display:flex;gap:8px;align-items:center;">
    <input type="text" name="constant_name" placeholder="CONSTANT_NAME" style="width:240px;">
    <input type="text" name="value"         placeholder="value"          style="width:160px;">
    <button type="submit" class="btn">Update</button>
</form>

<table>
    <tr><th>Constant</th><th>DB Value</th><th>Default</th></tr>
    {% for row in settings_rows %}
    <tr>
        <td style="color:#4499ff">{{ row.constant_name }}</td>
        <td>{{ row.value }}</td>
        <td style="color:#666;font-size:11px;">
            {{ defaults.get(row.constant_name, '—') }}
        </td>
    </tr>
    {% endfor %}
</table>
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/admin/logs.html                             -->
<!-- ============================================================ -->
{% extends "admin/base_admin.html" %}
{% block title %}Logs{% endblock %}
{% block content %}
<h1>Logs</h1>

<h2>Import Errors (last 100 lines)</h2>
{% if import_errors %}
<pre style="background:#0d0d0d;padding:10px;border:1px solid #222;
            font-size:11px;color:#cc2222;max-height:200px;overflow-y:auto;">
{%- for line in import_errors %}{{ line }}{%- endfor %}
</pre>
{% else %}
<p style="color:#666">No import errors.</p>
{% endif %}

<h2>Orphaned Actions (last 100 lines)</h2>
{% if orphan_log %}
<pre style="background:#0d0d0d;padding:10px;border:1px solid #222;
            font-size:11px;color:#ffaa00;max-height:200px;overflow-y:auto;">
{%- for line in orphan_log %}{{ line }}{%- endfor %}
</pre>
{% else %}
<p style="color:#666">No orphaned actions.</p>
{% endif %}

<h2>Failed Queue Rows (last 50)</h2>
{% if failed_queue %}
<table>
    <tr><th>ID</th><th>Player</th><th>Action</th><th>Created</th><th>Payload</th></tr>
    {% for row in failed_queue %}
    <tr>
        <td>{{ row.id }}</td>
        <td>{{ row.player_id }}</td>
        <td>{{ row.action_type }}</td>
        <td style="font-size:11px;color:#666">{{ row.created_at[:16] }}</td>
        <td style="font-size:11px;color:#666;max-width:300px;overflow:hidden;text-overflow:ellipsis;">
            {{ row.payload[:100] }}
        </td>
    </tr>
    {% endfor %}
</table>
{% else %}
<p style="color:#666">No failed queue rows.</p>
{% endif %}
{% endblock %}


