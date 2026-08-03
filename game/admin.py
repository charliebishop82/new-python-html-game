"""Local admin application for operations, diagnostics, balance, and support."""
# admin.py  (Phase 8)
# Separate Flask app for admin tools.
# Run with: flask --app admin:create_admin_app run --port 5001
# Localhost only — never expose publicly.

import math
import json
import logging
import os
import re
import sqlite3
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
    """Handle the create admin app workflow."""
    init_db()
    app = Flask(__name__, template_folder="templates")
    app.secret_key = cfg.SECRET_KEY + "-admin"
    app.teardown_appcontext(close_db)

    @app.before_request
    def check_admin_auth():
        """Handle the check admin auth workflow."""
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
    """Provide the internal register routes operation used by this module."""
    app.add_url_rule("/", "admin_root", lambda: redirect(url_for("admin_index")))
    app.add_url_rule("/admin",                        "admin_index",        admin_index)
    app.add_url_rule("/admin/import",                 "admin_import",       admin_import,        methods=["GET","POST"])
    app.add_url_rule("/admin/players",                "admin_players",      admin_players)
    app.add_url_rule("/admin/players/<int:pid>",      "admin_player_detail",admin_player_detail)
    app.add_url_rule("/admin/players/<int:pid>/ban",  "admin_ban",          admin_ban,           methods=["POST"])
    app.add_url_rule("/admin/players/<int:pid>/retire", "admin_retire_player", admin_retire_player, methods=["POST"])
    app.add_url_rule("/admin/players/<int:pid>/edit", "admin_edit",         admin_edit,          methods=["POST"])
    app.add_url_rule("/admin/config",                 "admin_config",       admin_config,        methods=["GET","POST"])
    app.add_url_rule("/admin/reset/midnight",         "admin_midnight",     admin_midnight,      methods=["POST"])
    app.add_url_rule("/admin/reset/full",             "admin_full_reset",   admin_full_reset,    methods=["POST"])
    app.add_url_rule("/admin/logs",                   "admin_logs",         admin_logs)
    app.add_url_rule("/admin/players/<int:pid>/activity", "admin_player_activity", admin_player_activity)
    app.add_url_rule("/admin/health",                 "admin_health",       admin_health)
    app.add_url_rule("/admin/items",                  "admin_items",        admin_items)
    app.add_url_rule("/admin/items/<item_type>/<int:item_id>/edit", "admin_item_edit", admin_item_edit, methods=["POST"])
    app.add_url_rule("/admin/analytics",              "admin_analytics",    admin_analytics)
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
    """Render or process the index administrative workflow."""
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
    """Render or process the import administrative workflow."""
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
    """Render or process the players administrative workflow."""
    players = execute(
        """SELECT p.*, ps.pvp_kills, ps.times_reduced_to_1hp,
                  CASE WHEN np.player_id IS NULL THEN 0 ELSE 1 END AS is_npc
           FROM players p
           LEFT JOIN player_stats ps ON ps.player_id = p.id
           LEFT JOIN npc_profiles np ON np.player_id = p.id
           ORDER BY p.level DESC, p.xp DESC"""
    )
    return render_template("admin/players.html", players=players)


def _audit(action: str, target_type: str, target_id=None, reason=None, details=None):
    """Provide the internal audit operation used by this module."""
    execute_write(
        """INSERT INTO admin_audit_log(action,target_type,target_id,reason,details_json)
           VALUES(?,?,?,?,?)""",
        (action, target_type, target_id, reason, json.dumps(details or {}, default=str)[:8000])
    )


def _activity_combat_context(pid: int, session_id: int | None) -> dict:
    """Resolve readable combat context for new and historical activity rows."""
    if not session_id:
        return {}
    combat = execute_one(
        """SELECT cs.*,att.character_name attacker_name,def.character_name defender_name,
                  b.name boss_name,m.name minion_name
           FROM combat_sessions cs
           LEFT JOIN players att ON att.id=cs.attacker_player_id
           LEFT JOIN players def ON def.id=cs.defender_player_id
           LEFT JOIN boss_instances bi ON bi.id=cs.boss_instance_id
           LEFT JOIN bosses b ON b.id=bi.boss_id
           LEFT JOIN minion_instances mi ON mi.id=cs.minion_instance_id
           LEFT JOIN minions m ON m.id=mi.minion_id WHERE cs.id=?""", (session_id,)
    )
    if not combat:
        return {"combat_session_id": session_id}
    opponent = (combat["defender_name"] if pid == combat["attacker_player_id"]
                else combat["attacker_name"])
    if combat["combat_type"] == "BOSS": opponent = combat["boss_name"]
    if combat["combat_type"] == "MINION": opponent = combat["minion_name"]
    return {
        "combat_session_id": session_id, "combat_type": combat["combat_type"],
        "opponent": opponent, "round": combat["current_round"],
        "status": combat["status"], "result": combat["result"],
        "damage_dealt": (combat["attacker_total_damage_dealt"]
                         if pid == combat["attacker_player_id"] else combat["defender_total_damage_dealt"]),
        "damage_received": (combat["defender_total_damage_dealt"]
                            if pid == combat["attacker_player_id"] else combat["attacker_total_damage_dealt"]),
    }


def _combat_progress_at_queue(pid: int, session_id: int, queue_id: int | None) -> dict:
    """Reconstruct round and cumulative damage at a historical queued action."""
    if not queue_id:
        return {}
    round_number = 0
    for queued in execute(
        """SELECT id,payload FROM action_queue WHERE id<=?
           AND action_type IN ('combat_action','combat_steal') ORDER BY id""", (queue_id,)
    ):
        try: queued_payload = json.loads(queued["payload"] or "{}")
        except (TypeError, json.JSONDecodeError): continue
        if queued_payload.get("session_id") == session_id:
            round_number += 1
    if not round_number:
        return {}

    session = execute_one(
        "SELECT attacker_player_id FROM combat_sessions WHERE id=?", (session_id,)
    )
    player_side = "ATTACKER" if session and session["attacker_player_id"] == pid else "DEFENDER"
    dealt = received = 0
    for event in execute(
        """SELECT actor,outcome_detail FROM combat_logs
           WHERE combat_session_id=? AND round_number<=?""", (session_id, round_number)
    ):
        match = re.search(
            r"(?:→|->)?\s*(\d+)\s+(?:[A-Za-z]+\s+)?damage",
            event.get("outcome_detail") or "",
        )
        damage = int(match.group(1)) if match else 0
        if event["actor"] == player_side: dealt += damage
        else: received += damage
    return {"round": round_number, "damage_dealt": dealt, "damage_received": received}


def _format_activity_row(row: dict, pid: int) -> dict:
    """Turn stored action JSON into a compact audit summary plus pretty detail."""
    try: stored = json.loads(row.get("details_json") or "{}")
    except (TypeError, json.JSONDecodeError): stored = {"raw": row.get("details_json")}
    try: payload = json.loads(row.get("queue_payload") or "{}")
    except (TypeError, json.JSONDecodeError): payload = {"raw": row.get("queue_payload")}

    raw_result = stored.get("result", stored) if isinstance(stored, dict) else {}
    result = raw_result if isinstance(raw_result, dict) else {"value": raw_result}
    context = stored.get("context", {}) if isinstance(stored, dict) else {}
    session_id = (context.get("combat_session_id") or result.get("session_id")
                  or payload.get("session_id"))
    if not session_id and row["action"].startswith("start_"):
        session_id = result.get("session_id")
    resolved = _activity_combat_context(pid, session_id)
    context = {**resolved, **context}
    if session_id:
        historical = _combat_progress_at_queue(pid, session_id, row.get("queue_id"))
        context.update(historical)
        context["status"] = ("RESOLVED" if result.get("combat_ended") else "ACTIVE")
    if not context.get("opponent") and payload.get("target_id"):
        target = execute_one("SELECT character_name FROM players WHERE id=?", (payload["target_id"],))
        if target: context["opponent"] = target["character_name"]

    highlights = []
    for event in result.get("round_log", []) if isinstance(result, dict) else []:
        if event.get("flavor"): highlights.append(event["flavor"])
        elif event.get("outcome_detail"): highlights.append(event["outcome_detail"])
    final = result.get("final_result") if isinstance(result, dict) else None
    if isinstance(final, dict) and final.get("flavor"): highlights.append(final["flavor"])
    if not highlights and context.get("opponent"):
        highlights.append(f"Opponent: {context['opponent']}")
    if not highlights and isinstance(stored, dict) and stored.get("reason"):
        highlights.append(stored["reason"])
        if stored.get("result"): highlights.append(f"Outcome: {stored['result']}")

    snapshot = stored.get("player_state_after", {}) if isinstance(stored, dict) else {}
    technical = {"input": payload, "result": result, "context": context}
    if snapshot: technical["player_state_after"] = snapshot
    if isinstance(stored, dict) and stored.get("error"): technical["error"] = stored["error"]
    return {
        **row, "action_label": row["action"].replace("_", " ").title(),
        "context": context, "highlights": highlights,
        "technical_json": json.dumps(technical, indent=2, ensure_ascii=False, default=str),
    }


def admin_player_activity(pid: int):
    """Render or process the player activity administrative workflow."""
    player = execute_one("SELECT * FROM players WHERE id=?", (pid,))
    if not player:
        return redirect(url_for("admin_players"))
    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()
    category = request.args.get("category", "").strip().upper()
    errors_only = request.args.get("errors_only") == "1"
    page = max(1, request.args.get("page", type=int, default=1))
    where, params = ["l.player_id=?"], [pid]
    if start: where.append("l.occurred_at>=?"); params.append(start)
    if end: where.append("l.occurred_at<?"); params.append(end + " 23:59:59")
    if category: where.append("l.category=?"); params.append(category)
    if errors_only: where.append("l.status='FAILED'")
    clause = " AND ".join(where)
    total = execute_one(f"SELECT COUNT(*) cnt FROM player_activity_log l WHERE {clause}", tuple(params))["cnt"]
    rows = execute(
        f"""SELECT l.*,q.payload AS queue_payload FROM player_activity_log l
            LEFT JOIN action_queue q ON q.id=l.queue_id
            WHERE {clause} ORDER BY l.id DESC LIMIT 100 OFFSET ?""",
        (*params, (page - 1) * 100)
    )
    rows = [_format_activity_row(row, pid) for row in rows]
    categories = execute("SELECT DISTINCT category FROM player_activity_log WHERE player_id=? ORDER BY category", (pid,))
    return render_template("admin/player_activity.html", player=player, rows=rows,
                           categories=categories, page=page, total=total,
                           start=start, end=end, category=category, errors_only=errors_only)


def admin_health():
    """Render or process the health administrative workflow."""
    stats = {
        "failed_actions": execute_one("SELECT COUNT(*) cnt FROM action_queue WHERE status='FAILED'")["cnt"],
        "processing_actions": execute_one("SELECT COUNT(*) cnt FROM action_queue WHERE status='PROCESSING'")["cnt"],
        "active_combats": execute_one("SELECT COUNT(*) cnt FROM combat_sessions WHERE status='ACTIVE'")["cnt"],
        "stuck_flags": execute_one("""SELECT COUNT(*) cnt FROM players p WHERE p.in_combat=1 AND NOT EXISTS
                                      (SELECT 1 FROM combat_sessions c WHERE c.status='ACTIVE' AND
                                       (c.attacker_player_id=p.id OR c.defender_player_id=p.id))""")["cnt"],
        "orphan_equipment": execute_one("""SELECT COUNT(*) cnt FROM players p WHERE
            (p.equipped_weapon_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM inventory_items i WHERE i.id=p.equipped_weapon_id AND i.player_id=p.id)) OR
            (p.equipped_armor_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM inventory_items i WHERE i.id=p.equipped_armor_id AND i.player_id=p.id)) OR
            (p.equipped_special_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM inventory_items i WHERE i.id=p.equipped_special_id AND i.player_id=p.id))""")["cnt"],
        "special_mismatches": execute_one("""SELECT COUNT(*) cnt FROM special_item_registry r
            WHERE (r.status='IN_INVENTORY' AND (r.current_owner_player_id IS NULL OR r.inventory_item_id IS NULL))
               OR (r.status='IN_POOL' AND (r.current_owner_player_id IS NOT NULL OR r.inventory_item_id IS NOT NULL))""")["cnt"],
    }
    scheduler_runs = execute("SELECT * FROM scheduler_run_log ORDER BY id DESC LIMIT 30")
    failures = execute("""SELECT q.*,p.character_name FROM action_queue q JOIN players p ON p.id=q.player_id
                          WHERE q.status='FAILED' ORDER BY q.id DESC LIMIT 30""")
    audits = execute("SELECT * FROM admin_audit_log ORDER BY id DESC LIMIT 30")
    return render_template("admin/health.html", stats=stats, scheduler_runs=scheduler_runs,
                           failures=failures, audits=audits)


ITEM_TABLES = {"weapon": "weapons", "armor": "armor", "special": "special_items"}
ITEM_EDIT_FIELDS = {
    "weapon": ("name","is_active","level","weapon_type","damage_die","damage_type","str_bonus","end_bonus","agi_bonus","lck_bonus","per_bonus","credit_cost","drop_chance","starting_durability"),
    "armor": ("name","is_active","level","ac_bonus","res_blade","res_blunt","res_ballistic","res_energy","res_arcane","res_explosive","res_venom","str_bonus","end_bonus","agi_bonus","lck_bonus","per_bonus","credit_cost","drop_chance","starting_durability"),
    "special": ("name","is_active","associated_to","association_type","str_bonus","end_bonus","agi_bonus","lck_bonus","per_bonus","initiative_bonus","extra_attack","crit_chance_bonus","crit_dmg_multiplier","ac_bonus","credit_cost","drop_chance","starting_durability","steal_bonus","xp_multiplier","credit_multiplier","bonus_ap","hp_regen_bonus","durability_reduction","shop_discount","sell_bonus","encounter_bonus"),
}


def admin_items():
    """Render or process the items administrative workflow."""
    selected = request.args.get("type", "weapon").lower()
    if selected not in ITEM_TABLES: selected = "weapon"
    items = execute(f"SELECT * FROM {ITEM_TABLES[selected]} ORDER BY is_active DESC,name")
    registry = execute("""SELECT r.*,s.name,p.character_name FROM special_item_registry r
                          JOIN special_items s ON s.id=r.special_item_id
                          LEFT JOIN players p ON p.id=r.current_owner_player_id ORDER BY s.name""")
    return render_template("admin/items.html", items=items, selected=selected,
                           fields=ITEM_EDIT_FIELDS[selected], registry=registry)


def admin_item_edit(item_type: str, item_id: int):
    """Render or process the item edit administrative workflow."""
    item_type = item_type.lower()
    if item_type not in ITEM_TABLES:
        return redirect(url_for("admin_items", error="Unknown item type."))
    table, allowed = ITEM_TABLES[item_type], ITEM_EDIT_FIELDS[item_type]
    current = execute_one(f"SELECT * FROM {table} WHERE id=?", (item_id,))
    if not current:
        return redirect(url_for("admin_items", type=item_type, error="Item not found."))
    changes = {}
    for field in allowed:
        raw = request.form.get(field)
        if raw is None: continue
        old = current.get(field)
        try:
            value = int(raw) if isinstance(old, int) else float(raw) if isinstance(old, float) else raw.strip()
        except ValueError:
            return redirect(url_for("admin_items", type=item_type, error=f"Invalid value for {field}."))
        if value != old: changes[field] = value
    reason = request.form.get("reason", "").strip()
    if not reason:
        return redirect(url_for("admin_items", type=item_type, error="A balancing reason is required."))
    if changes:
        try:
            with exclusive_transaction():
                execute_write(f"UPDATE {table} SET " + ",".join(f"{f}=?" for f in changes) + " WHERE id=?",
                              (*changes.values(), item_id))
                _audit("EDIT_ITEM", item_type.upper(), item_id, reason,
                       {f: {"from": current.get(f), "to": v} for f, v in changes.items()})
        except sqlite3.IntegrityError as exc:
            return redirect(url_for("admin_items", type=item_type, error=str(exc)))
    return redirect(url_for("admin_items", type=item_type, feedback=f"Updated {current['name']}."))


def admin_analytics():
    """Render or process the analytics administrative workflow."""
    action_counts = execute("""SELECT action,status,COUNT(*) cnt FROM player_activity_log
                               GROUP BY action,status ORDER BY cnt DESC LIMIT 30""")
    economy = execute_one("""SELECT COUNT(*) players,COALESCE(SUM(credits),0) credits,
                              COALESCE(AVG(credits),0) avg_credits,COALESCE(AVG(level),0) avg_level
                              FROM players WHERE is_banned=0""")
    combats = execute("SELECT combat_type,result,COUNT(*) cnt FROM combat_sessions GROUP BY combat_type,result ORDER BY cnt DESC")
    item_events = execute("SELECT event_type,COUNT(*) cnt FROM item_history GROUP BY event_type ORDER BY cnt DESC LIMIT 25")
    npc_decisions = execute("SELECT decision,COUNT(*) cnt FROM npc_action_log GROUP BY decision ORDER BY cnt DESC")
    random_events = execute("""SELECT flavor_text,COUNT(*) cnt FROM daily_feed WHERE event_category='RANDOM_EVENT'
                               GROUP BY flavor_text ORDER BY cnt DESC LIMIT 20""")
    return render_template("admin/analytics.html", action_counts=action_counts, economy=economy,
                           combats=combats, item_events=item_events,
                           npc_decisions=npc_decisions, random_events=random_events)
def admin_player_detail(pid: int):
    """Render or process the player detail administrative workflow."""
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
    """Render or process the ban administrative workflow."""
    action = request.form.get("action", "ban")

    if action == "unban":
        with exclusive_transaction():
            execute_write("UPDATE players SET is_banned = 0 WHERE id = ?", (pid,))
            _audit("UNBAN_PLAYER", "PLAYER", pid)
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
        _audit("BAN_PLAYER", "PLAYER", pid)

    logger.info("Admin: banned player id=%d", pid)
    return redirect(url_for("admin_player_detail", pid=pid, feedback="Player banned."))


def admin_retire_player(pid: int):
    """Permanently retire a character without deleting its history."""
    player = execute_one("SELECT * FROM players WHERE id=?", (pid,))
    if not player:
        return redirect(url_for("admin_players"))
    if player.get("retired_at"):
        return redirect(url_for("admin_player_detail", pid=pid, error="Character is already retired."))
    now = datetime.utcnow().isoformat()
    with exclusive_transaction():
        sessions = execute(
            """SELECT id,attacker_player_id,defender_player_id FROM combat_sessions
               WHERE status='ACTIVE' AND (attacker_player_id=? OR defender_player_id=?)""", (pid, pid)
        )
        for combat in sessions:
            other = (combat["defender_player_id"] if combat["attacker_player_id"] == pid
                     else combat["attacker_player_id"])
            execute_write("UPDATE combat_sessions SET status='CANCELLED',result='PLAYER_RETIRED',resolved_at=? WHERE id=?",
                          (now, combat["id"]))
            if other:
                execute_write("UPDATE players SET in_combat=0 WHERE id=?", (other,))
        specials = execute("SELECT id,item_id FROM inventory_items WHERE player_id=? AND item_type='SPECIAL'", (pid,))
        for item in specials:
            execute_write(
                """UPDATE special_item_registry SET status='IN_POOL',current_owner_player_id=NULL,
                   inventory_item_id=NULL,last_released_method='PLAYER_RETIRED',updated_at=?
                   WHERE special_item_id=?""", (now, item["item_id"])
            )
        execute_write("DELETE FROM inventory_items WHERE player_id=? AND item_type='SPECIAL'", (pid,))
        execute_write(
            """UPDATE players SET retired_at=?,is_banned=1,in_combat=0,equipped_special_id=NULL
               WHERE id=?""", (now, pid)
        )
        execute_write("UPDATE npc_profiles SET enabled=0,retired=1 WHERE player_id=?", (pid,))
        _audit("RETIRE_PLAYER", "PLAYER", pid)
    logger.info("Admin: retired player id=%d", pid)
    return redirect(url_for("admin_player_detail", pid=pid, feedback="Character retired; unique specials returned to the pool."))


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
            _audit("EDIT_PLAYER", "PLAYER", pid, details=fields)
        logger.info("Admin: edited player id=%d fields=%s", pid, list(fields.keys()))

    return redirect(url_for("admin_player_detail", pid=pid, feedback="Player updated."))


# NPC MANAGEMENT
def admin_npcs():
    """Render or process the npcs administrative workflow."""
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
    """Render or process the npc edit administrative workflow."""
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
    """Render or process the npc run administrative workflow."""
    from npc import run_npc_turn
    try:
        result = run_npc_turn(pid)
        with exclusive_transaction():
            _audit("RUN_NPC_TURN", "PLAYER", pid, details=result)
        return redirect(url_for("admin_npcs", feedback=f"NPC turn: {result['decision']} - {result['result']}"))
    except Exception as exc:
        logger.exception("Manual NPC turn failed for %d", pid)
        return redirect(url_for("admin_npcs", error=str(exc)))


def admin_npc_spend_ap(pid: int):
    """Render or process the npc spend ap administrative workflow."""
    from npc import spend_npc_ap_now
    try:
        result = spend_npc_ap_now(pid)
        with exclusive_transaction():
            _audit("SPEND_NPC_AP", "PLAYER", pid, details=result)
        return redirect(url_for(
            "admin_npcs",
            feedback=(f"NPC ran {result['decisions']} decision(s) and spent "
                      f"{result['ap_spent']} AP; {result['ap_remaining']} AP remains.")
        ))
    except Exception as exc:
        logger.exception("Immediate NPC AP spending failed for %d", pid)
        return redirect(url_for("admin_npcs", error=str(exc)))


def admin_npc_retire(pid: int):
    """Render or process the npc retire administrative workflow."""
    from npc import retire_npc
    retire_npc(pid)
    with exclusive_transaction():
        _audit("RETIRE_NPC", "PLAYER", pid)
    return redirect(url_for("admin_npcs", feedback="NPC retired; unique specials returned to the pool."))


def admin_npc_grant(pid: int):
    """Render or process the npc grant administrative workflow."""
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
        _audit("GRANT_ITEM", "PLAYER", pid, details={"item_type": item_type, "item_id": item_id})
    return redirect(url_for("admin_npcs", feedback=f"Granted {item['name']}."))


def admin_npc_remove(pid: int, inv_id: int):
    """Render or process the npc remove administrative workflow."""
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
        _audit("REMOVE_ITEM", "PLAYER", pid, details={"inventory_id": inv_id})
    return redirect(url_for("admin_npcs", feedback="Inventory item removed."))


def _create_npc(form) -> int:
    """Provide the internal create npc operation used by this module."""
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
    # Presets populate the visible form in the browser. Always save the visible
    # values so an administrator can select a preset and then customize it.
    """Provide the internal npc scores from form operation used by this module."""
    return tuple(max(0, min(100, form.get(key, type=int, default=default)))
                 for key, default in (
                     ("player_hunter", 100), ("boss_killer", 0),
                     ("hoarder", 0), ("thief", 0), ("aggression", 85),
                     ("self_preservation", 35), ("repair_tendency", 55)))


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def admin_config():
    """Render or process the config administrative workflow."""
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
                _audit("EDIT_CONFIG", "SETTING", reason=constant, details={"value": value})
            feedback = f"Setting '{constant}' updated to '{value}'."
        else:
            error = "Both constant name and value are required."

    settings_rows = execute("SELECT * FROM settings ORDER BY constant_name")
    settings_map = {row["constant_name"]: row["value"] for row in settings_rows}
    defaults      = {k: v for k, v in vars(cfg).items()
                     if k.isupper() and not k.startswith("_")}
    return render_template("admin/config.html",
                           settings_rows=settings_rows,
                           settings_map=settings_map,
                           defaults=defaults,
                           feedback=feedback,
                           error=error)


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL MIDNIGHT RESET
# ─────────────────────────────────────────────────────────────────────────────

def admin_midnight():
    """Render or process the midnight administrative workflow."""
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
    """Render or process the logs administrative workflow."""
    import os

    def read_tail(path: str, n: int = 100) -> list[str]:
        """Handle the read tail workflow."""
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
