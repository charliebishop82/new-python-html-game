"""Local admin application for operations, diagnostics, balance, and support."""
# Administrative dashboard, auditing, content balancing, and support tools.
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
                      get_all_settings, reconcile_combat_state)

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
    with app.app_context():
        reconcile_combat_state()

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
    app.add_url_rule("/admin/rules",                  "admin_rules",        admin_rules)
    app.add_url_rule("/admin/world-boss",             "admin_world_boss",   admin_world_boss)
    app.add_url_rule("/admin/world-boss/activate",    "admin_world_boss_activate", admin_world_boss_activate, methods=["POST"])
    app.add_url_rule("/admin/world-boss/close",       "admin_world_boss_close", admin_world_boss_close, methods=["POST"])
    app.add_url_rule("/admin/world-boss/rescale",     "admin_world_boss_rescale", admin_world_boss_rescale, methods=["POST"])
    app.add_url_rule("/admin/world-boss/process-rewards", "admin_world_boss_process_rewards", admin_world_boss_process_rewards, methods=["POST"])
    app.add_url_rule("/admin/auctions",               "admin_auctions", admin_auctions)
    app.add_url_rule("/admin/auctions/<int:listing_id>/cancel", "admin_auction_cancel", admin_auction_cancel, methods=["POST"])
    app.add_url_rule("/admin/auctions/settle",        "admin_auction_settle", admin_auction_settle, methods=["POST"])
    app.add_url_rule("/admin/contracts",              "admin_contracts", admin_contracts)
    app.add_url_rule("/admin/contracts/<int:assignment_id>/complete", "admin_contract_complete", admin_contract_complete, methods=["POST"])
    app.add_url_rule("/admin/perks",                  "admin_perks", admin_perks)
    app.add_url_rule("/admin/scenes",                 "admin_scenes", admin_scenes)
    app.add_url_rule("/admin/reputation",             "admin_reputation", admin_reputation)
    app.add_url_rule("/admin/operations",             "admin_operations", admin_operations)
    app.add_url_rule("/admin/queue/<int:queue_id>/acknowledge", "admin_queue_acknowledge", admin_queue_acknowledge, methods=["POST"])
    app.add_url_rule("/admin/queue/acknowledge-all", "admin_queue_acknowledge_all", admin_queue_acknowledge_all, methods=["POST"])
    app.add_url_rule("/admin/combat/<int:session_id>", "admin_combat_detail", admin_combat_detail)
    app.add_url_rule("/admin/players/<int:pid>/repair-state", "admin_repair_player_state", admin_repair_player_state, methods=["POST"])
    app.add_url_rule("/admin/import",                 "admin_import",       admin_import,        methods=["GET","POST"])
    app.add_url_rule("/admin/players",                "admin_players",      admin_players)
    app.add_url_rule("/admin/players/<int:pid>",      "admin_player_detail",admin_player_detail)
    app.add_url_rule("/admin/players/<int:pid>/ban",  "admin_ban",          admin_ban,           methods=["POST"])
    app.add_url_rule("/admin/players/<int:pid>/retire", "admin_retire_player", admin_retire_player, methods=["POST"])
    app.add_url_rule("/admin/players/<int:pid>/edit", "admin_edit",         admin_edit,          methods=["POST"])
    app.add_url_rule("/admin/players/<int:pid>/replenish-ap", "admin_player_replenish_ap",
                     admin_player_replenish_ap, methods=["POST"])
    app.add_url_rule("/admin/players/replenish-ap-all", "admin_replenish_all_ap",
                     admin_replenish_all_ap, methods=["POST"])
    app.add_url_rule("/admin/config",                 "admin_config",       admin_config,        methods=["GET","POST"])
    app.add_url_rule("/admin/reset/midnight",         "admin_midnight",     admin_midnight,      methods=["POST"])
    app.add_url_rule("/admin/reset/full",             "admin_full_reset",   admin_full_reset,    methods=["POST"])
    app.add_url_rule("/admin/logs",                   "admin_logs",         admin_logs)
    app.add_url_rule("/admin/players/<int:pid>/activity", "admin_player_activity", admin_player_activity)
    app.add_url_rule("/admin/health",                 "admin_health",       admin_health)
    app.add_url_rule("/admin/items",                  "admin_items",        admin_items)
    app.add_url_rule("/admin/items/<item_type>/<int:item_id>/edit", "admin_item_edit", admin_item_edit, methods=["POST"])
    app.add_url_rule("/admin/shop",                   "admin_shop",         admin_shop)
    app.add_url_rule("/admin/shop/populate",          "admin_shop_populate", admin_shop_populate, methods=["POST"])
    app.add_url_rule("/admin/shop/add",               "admin_shop_add",     admin_shop_add, methods=["POST"])
    app.add_url_rule("/admin/shop/<int:listing_id>/remove", "admin_shop_remove", admin_shop_remove, methods=["POST"])
    app.add_url_rule("/admin/analytics",              "admin_analytics",    admin_analytics)
    app.add_url_rule("/admin/npcs",                   "admin_npcs",         admin_npcs,          methods=["GET","POST"])
    app.add_url_rule("/admin/crews",                  "admin_crews",        admin_crews)
    app.add_url_rule("/admin/crews/member/<int:pid>/remove", "admin_crew_remove", admin_crew_remove, methods=["POST"])
    app.add_url_rule("/admin/npcs/audit",             "admin_npc_audit",    admin_npc_audit)
    app.add_url_rule("/admin/npcs/<int:pid>/edit",    "admin_npc_edit",     admin_npc_edit,      methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/run",     "admin_npc_run",      admin_npc_run,       methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/spend-ap", "admin_npc_spend_ap", admin_npc_spend_ap, methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/replenish-ap", "admin_npc_replenish_ap", admin_npc_replenish_ap, methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/retire",  "admin_npc_retire",   admin_npc_retire,    methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/inventory/grant", "admin_npc_grant", admin_npc_grant, methods=["POST"])
    app.add_url_rule("/admin/npcs/<int:pid>/inventory/<int:inv_id>/remove", "admin_npc_remove", admin_npc_remove, methods=["POST"])


def admin_crews():
    """Inspect membership, pools, pending requests, scores, and recent crew events."""
    crews = execute("""SELECT c.*,(SELECT COUNT(*) FROM crew_memberships WHERE crew_id=c.id) members,
      COALESCE((SELECT SUM(points) FROM crew_score_events WHERE crew_id=c.id),0) score
      FROM crews c WHERE c.disbanded_at IS NULL ORDER BY score DESC""")
    members = execute("""SELECT cm.*,p.character_name,c.name crew_name,
      CASE WHEN np.player_id IS NULL THEN 'PLAYER' ELSE 'NPC' END character_type
      FROM crew_memberships cm JOIN players p ON p.id=cm.player_id JOIN crews c ON c.id=cm.crew_id
      LEFT JOIN npc_profiles np ON np.player_id=p.id ORDER BY c.name,cm.role,p.character_name""")
    requests = execute("""SELECT r.*,p.character_name,c.name crew_name FROM crew_requests r
      JOIN players p ON p.id=r.player_id JOIN crews c ON c.id=r.crew_id
      WHERE r.status='PENDING' ORDER BY r.id DESC""")
    logs = execute("SELECT * FROM crew_logs ORDER BY id DESC LIMIT 100")
    from crews import crew_capacity
    return render_template("admin/crews.html",crews=crews,members=members,requests=requests,
                           logs=logs,capacity=crew_capacity())


def admin_crew_remove(pid):
    """Remove a member using the ordinary audited leave path and its PvP cooldown."""
    from crews import leave_crew
    leave_crew(pid)
    return redirect(url_for("admin_crews",feedback="Crew member returned to Free Agent status."))


def admin_auctions():
    """Inspect live and recently completed player auctions and escrowed bids."""
    rows = execute(
        """SELECT a.*,seller.character_name seller_name,bidder.character_name bidder_name,
                  si.name item_name,ii.current_durability
           FROM auction_listings a
           JOIN players seller ON seller.id=a.seller_player_id
           LEFT JOIN players bidder ON bidder.id=a.current_bidder_id
           LEFT JOIN inventory_items ii ON ii.id=a.inventory_item_id
           LEFT JOIN special_items si ON si.id=ii.item_id
           ORDER BY CASE a.status WHEN 'ACTIVE' THEN 0 ELSE 1 END,datetime(a.ends_at),a.id DESC
           LIMIT 250"""
    )
    escrow = sum(int(row.get("current_bid") or 0) for row in rows if row["status"] == "ACTIVE")
    return render_template("admin/auctions.html", listings=rows, escrow=escrow)


def admin_auction_cancel(listing_id: int):
    """Cancel one auction, refund its high bidder, and release the held item."""
    listing = execute_one("SELECT * FROM auction_listings WHERE id=? AND status='ACTIVE'", (listing_id,))
    if not listing:
        return redirect(url_for("admin_auctions", error="Active auction not found."))
    with exclusive_transaction():
        if listing.get("current_bidder_id") and listing.get("current_bid"):
            execute_write("UPDATE players SET credits=credits+? WHERE id=?",
                          (listing["current_bid"], listing["current_bidder_id"]))
        execute_write("UPDATE auction_listings SET status='CANCELLED',settled_at=datetime('now') WHERE id=?",
                      (listing_id,))
        execute_write("UPDATE special_item_registry SET status='IN_INVENTORY',updated_at=datetime('now') WHERE inventory_item_id=?",
                      (listing["inventory_item_id"],))
        _audit("CANCEL_AUCTION", "AUCTION", listing_id, "Administrator cancelled listing",
               {"refunded_bid": listing.get("current_bid"), "bidder_id": listing.get("current_bidder_id")})
    return redirect(url_for("admin_auctions", feedback="Auction cancelled; held bid refunded and item released."))


def admin_auction_settle():
    """Run the ordinary auction settlement path for every listing whose timer elapsed."""
    from routes.auction import settle_expired_auctions
    result = settle_expired_auctions()
    return redirect(url_for("admin_auctions", feedback=f"Settled {result['settled']} expired auction(s)."))


def admin_contracts():
    """Inspect imported objectives and current or recent player assignments."""
    definitions = execute("SELECT * FROM contracts ORDER BY is_active DESC,min_level,name")
    assignments = execute(
        """SELECT pdc.*,p.character_name,c.name,c.metric,c.target,c.reward_xp,c.reward_credits,c.reward_ap
           FROM player_daily_contracts pdc JOIN players p ON p.id=pdc.player_id
           JOIN contracts c ON c.id=pdc.contract_id
           ORDER BY pdc.contract_date DESC,p.character_name LIMIT 300"""
    )
    return render_template("admin/contracts.html", definitions=definitions, assignments=assignments)


def admin_contract_complete(assignment_id: int):
    """Complete an assignment through the normal reward function for controlled testing."""
    row = execute_one(
        """SELECT pdc.*,c.metric,c.target FROM player_daily_contracts pdc
           JOIN contracts c ON c.id=pdc.contract_id WHERE pdc.id=?""", (assignment_id,)
    )
    if (not row or row["status"] != "ACTIVE" or
            row["contract_date"] != datetime.utcnow().date().isoformat()):
        return redirect(url_for("admin_contracts", error="Active contract assignment not found."))
    from contracts import record_progress
    record_progress(row["player_id"], row["metric"], max(0, row["target"] - row["progress"]))
    with exclusive_transaction():
        _audit("COMPLETE_CONTRACT", "CONTRACT_ASSIGNMENT", assignment_id, "Administrator test completion")
    return redirect(url_for("admin_contracts", feedback="Contract completed through the normal reward path."))


def admin_perks():
    """Inspect imported perk definitions, effective scaling, ownership, and pending choices."""
    from database import scale_perk_effects
    perks = execute("SELECT * FROM perks ORDER BY level,name")
    for perk in perks:
        perk["effective"] = scale_perk_effects(perk)
        perk["owners"] = execute_one("SELECT COUNT(*) cnt FROM player_perks WHERE perk_id=?", (perk["id"],))["cnt"]
    pending = execute("SELECT id,character_name,level,pending_perk FROM players WHERE pending_perk>0 ORDER BY pending_perk DESC")
    return render_template("admin/perks.html", perks=perks, pending=pending,
                           scale=get_all_settings().get("PERK_EFFECT_SCALE", cfg.PERK_EFFECT_SCALE))


def admin_scenes():
    """Inspect imported cinematic content while its player feature gate is off."""
    from scenes import scene_catalog
    scenes = scene_catalog()
    selected_id = request.args.get("scene_id", type=int)
    selected = next((scene for scene in scenes if scene["id"] == selected_id), None)
    choices = execute(
        "SELECT * FROM scene_choices WHERE scene_id=? ORDER BY attribute", (selected_id,)
    ) if selected_id else []
    attempts = execute(
        """SELECT sa.*,p.character_name,s.scene_name,sc.attribute
           FROM scene_attempts sa JOIN players p ON p.id=sa.player_id
           JOIN scenes s ON s.id=sa.scene_id
           LEFT JOIN scene_choices sc ON sc.id=sa.choice_id
           ORDER BY sa.id DESC LIMIT 50"""
    )
    return render_template("admin/scenes.html", scenes=scenes, selected=selected,
                           choices=choices, attempts=attempts,
                           enabled=bool(get_all_settings().get("SCENES_PLAYER_ENABLED", False)))


def admin_reputation():
    """Display behavior-derived titles and the counters behind every character's reputation."""
    from reputations import reputation_profile
    players = execute(
        """SELECT p.id,p.character_name,p.level,CASE WHEN np.player_id IS NULL THEN 0 ELSE 1 END is_npc
           FROM players p LEFT JOIN npc_profiles np ON np.player_id=p.id
           WHERE p.is_banned=0 AND p.retired_at IS NULL ORDER BY p.level DESC,p.character_name"""
    )
    for player in players:
        player["reputation"] = reputation_profile(player["id"])
    return render_template("admin/reputation.html", players=players)


def admin_operations():
    """Central operational view of combat, queue failures, interruptions, and scheduling."""
    show_reviewed = request.args.get("show") == "all"
    combats = execute(
        """SELECT cs.*,a.character_name attacker,d.character_name defender,
          CASE cs.combat_type WHEN 'BOSS' THEN b.name WHEN 'MINION' THEN m.name
               WHEN 'WORLD_BOSS' THEN wb.name ELSE d.character_name END opponent
          FROM combat_sessions cs JOIN players a ON a.id=cs.attacker_player_id
          LEFT JOIN players d ON d.id=cs.defender_player_id
          LEFT JOIN boss_instances bi ON bi.id=cs.boss_instance_id LEFT JOIN bosses b ON b.id=bi.boss_id
          LEFT JOIN minion_instances mi ON mi.id=cs.minion_instance_id LEFT JOIN minions m ON m.id=mi.minion_id
          LEFT JOIN world_boss_events we ON we.id=cs.world_boss_event_id LEFT JOIN world_bosses wb ON wb.id=we.world_boss_id
          ORDER BY CASE cs.status WHEN 'ACTIVE' THEN 0 ELSE 1 END,cs.id DESC LIMIT 150"""
    )
    failures = execute(
        """SELECT q.*,p.character_name FROM action_queue q JOIN players p ON p.id=q.player_id
           WHERE q.status='FAILED' AND (? OR q.admin_acknowledged_at IS NULL)
           ORDER BY q.id DESC LIMIT 100""", (int(show_reviewed),)
    )
    failure_counts = execute_one(
        """SELECT SUM(CASE WHEN admin_acknowledged_at IS NULL THEN 1 ELSE 0 END) unreviewed,
                  SUM(CASE WHEN admin_acknowledged_at IS NOT NULL THEN 1 ELSE 0 END) reviewed
           FROM action_queue WHERE status='FAILED'"""
    )
    interruptions = execute(
        """SELECT pia.*,p.character_name FROM pending_interrupted_actions pia
           JOIN players p ON p.id=pia.player_id ORDER BY pia.created_at"""
    )
    npcs = execute(
        """SELECT np.*,p.character_name,p.current_ap,p.in_combat FROM npc_profiles np
           JOIN players p ON p.id=np.player_id WHERE np.retired=0 ORDER BY np.last_action_at"""
    )
    scheduler = execute("SELECT * FROM scheduler_run_log ORDER BY id DESC LIMIT 40")
    return render_template("admin/operations.html", combats=combats, failures=failures,
                           interruptions=interruptions, npcs=npcs, scheduler=scheduler,
                           failure_counts=failure_counts, show_reviewed=show_reviewed)


def admin_queue_acknowledge(queue_id: int):
    """Mark a historical failure reviewed without deleting its audit evidence."""
    note = request.form.get("note", "").strip()[:500]
    with exclusive_transaction():
        execute_write(
            """UPDATE action_queue SET admin_acknowledged_at=datetime('now'),admin_note=?
               WHERE id=? AND status='FAILED'""", (note, queue_id)
        )
        _audit("ACKNOWLEDGE_QUEUE_FAILURE", "ACTION_QUEUE", queue_id, note or "Reviewed")
    return redirect(url_for("admin_operations", feedback=f"Queue failure #{queue_id} marked reviewed."))


def admin_queue_acknowledge_all():
    """Acknowledge every unreviewed failure while preserving its audit row."""
    note = request.form.get("note", "").strip()[:500] or "Bulk acknowledged after review"
    return_to = request.form.get("return_to", "operations")
    count = execute_one(
        "SELECT COUNT(*) cnt FROM action_queue WHERE status='FAILED' AND admin_acknowledged_at IS NULL"
    )["cnt"]
    if count:
        with exclusive_transaction():
            execute_write(
                """UPDATE action_queue SET admin_acknowledged_at=datetime('now'),admin_note=?
                   WHERE status='FAILED' AND admin_acknowledged_at IS NULL""", (note,)
            )
            _audit("ACKNOWLEDGE_ALL_QUEUE_FAILURES", "ACTION_QUEUE", None,
                   f"{count} failures reviewed: {note}")
    endpoint = "admin_logs" if return_to == "logs" else "admin_operations"
    feedback = (f"Acknowledged {count} failed queue row(s). Audit history was preserved."
                if count else "There were no unreviewed queue failures.")
    return redirect(url_for(endpoint, feedback=feedback))


def admin_combat_detail(session_id: int):
    """Render the authoritative session plus its round-by-round calculation ledger."""
    combat = execute_one(
        """SELECT cs.*,a.character_name attacker,d.character_name defender
           FROM combat_sessions cs JOIN players a ON a.id=cs.attacker_player_id
           LEFT JOIN players d ON d.id=cs.defender_player_id WHERE cs.id=?""", (session_id,)
    )
    if not combat:
        return redirect(url_for("admin_operations", error="Combat session not found."))
    logs = execute("SELECT * FROM combat_logs WHERE combat_session_id=? ORDER BY id", (session_id,))
    buffs = execute("SELECT * FROM combat_buffs WHERE combat_session_id=? ORDER BY id", (session_id,))
    activity = execute(
        """SELECT * FROM player_activity_log WHERE json_valid(details_json)=1 AND
           (json_extract(details_json,'$.session_id')=? OR json_extract(details_json,'$.combat_id')=?)
           ORDER BY id""", (session_id, session_id)
    )
    return render_template("admin/combat_detail.html", combat=combat, logs=logs, buffs=buffs, activity=activity)


def admin_repair_player_state(pid: int):
    """Run conservative state reconciliation for one character and audit the result."""
    result = reconcile_combat_state(pid)
    with exclusive_transaction():
        _audit("REPAIR_PLAYER_STATE", "PLAYER", pid, "Conservative combat-state reconciliation", result)
    return redirect(url_for("admin_player_detail", pid=pid, feedback=f"State checked: {result}."))


def admin_world_boss():
    """Inspect the weekly encounter, ranking ledger, rewards, and live audit log."""
    from world_boss import get_active_event, standings
    active = get_active_event()
    latest = active or execute_one(
        """SELECT e.*,w.name,w.flavor_text FROM world_boss_events e
           JOIN world_bosses w ON w.id=e.world_boss_id ORDER BY e.id DESC LIMIT 1"""
    )
    return render_template(
        "admin/world_boss.html", event=latest,
        standings=standings(latest["id"]) if latest else [],
        rewards=(execute(
            """SELECT r.*,p.character_name,
               CASE r.item_type WHEN 'WEAPON' THEN w.name WHEN 'ARMOR' THEN a.name
                    WHEN 'SPECIAL' THEN s.name END item_name
               FROM world_boss_rewards r JOIN players p ON p.id=r.player_id
               LEFT JOIN weapons w ON r.item_type='WEAPON' AND w.id=r.item_id
               LEFT JOIN armor a ON r.item_type='ARMOR' AND a.id=r.item_id
               LEFT JOIN special_items s ON r.item_type='SPECIAL' AND s.id=r.item_id
               WHERE r.event_id=? ORDER BY r.place""",
            (latest["id"],)) if latest else []),
        crew_standings=(execute(
            """SELECT c.name,c.tag,SUM(wbc.damage) damage,COUNT(DISTINCT wbc.player_id) participants
               FROM world_boss_contributions wbc JOIN crew_memberships cm ON cm.player_id=wbc.player_id
               JOIN crews c ON c.id=cm.crew_id WHERE wbc.event_id=?
               GROUP BY c.id ORDER BY damage DESC""", (latest["id"],)) if latest else []),
        logs=(execute(
            """SELECT * FROM world_boss_event_log WHERE event_id=? ORDER BY id DESC LIMIT 100""",
            (latest["id"],)) if latest else []),
        bosses=execute(
            """SELECT w.*,EXISTS(SELECT 1 FROM world_boss_events e WHERE e.world_boss_id=w.id) used
               FROM world_bosses w ORDER BY w.name"""
        ),
    )


def admin_world_boss_activate():
    """Force activation of one unused imported boss when no workflow blocks it."""
    from world_boss import activate_next_event
    boss_id = request.form.get("boss_id", type=int)
    event = activate_next_event(forced_boss_id=boss_id)
    if not event:
        return redirect(url_for("admin_world_boss", error="An active event or pending reward workflow blocks activation."))
    return redirect(url_for("admin_world_boss", feedback=f"Activated {event['name']}."))


def admin_world_boss_close():
    """Close the active event and lock its current damage standings."""
    from world_boss import get_active_event, close_event
    event = get_active_event()
    if not event:
        return redirect(url_for("admin_world_boss", error="No active world boss."))
    close_event(event["id"], "ADMIN_CLOSED")
    return redirect(url_for("admin_world_boss", feedback="Event closed and rewards locked."))


def admin_world_boss_rescale():
    """Apply the safety multiplier to the live pool without erasing damage."""
    from world_boss import rescale_active_event
    try:
        multiplier = request.form.get("multiplier", type=float)
        event = rescale_active_event(multiplier)
        with exclusive_transaction():
            execute_write("UPDATE settings SET value=? WHERE constant_name='WORLD_BOSS_HP_MULTIPLIER'",
                          (str(event["hp_multiplier"]),))
        return redirect(url_for("admin_world_boss",
                                feedback=f"Active HP scale updated; {event['current_hp']} HP remains."))
    except (ValueError, TypeError) as exc:
        return redirect(url_for("admin_world_boss", error=str(exc)))


def admin_world_boss_process_rewards():
    """Run deadline-based automatic reward selection without altering unexpired choices."""
    from world_boss import process_expired_rewards
    awarded = process_expired_rewards()
    with exclusive_transaction():
        _audit("PROCESS_WORLD_BOSS_REWARDS", "WORLD_BOSS", reason="Admin deadline check",
               details={"reward_ids": awarded})
    return redirect(url_for("admin_world_boss", feedback=f"Processed {len(awarded)} expired reward choice(s)."))


def admin_rules():
    """Render the creator-facing map of gameplay formulas and control settings."""
    return render_template(
        "admin/rules.html", settings=get_all_settings(), xp_curve=cfg.XP_CURVE
    )


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

def admin_index():
    """Render or process the index administrative workflow."""
    import os
    player_count  = execute_one("SELECT COUNT(*) as cnt FROM players WHERE is_banned = 0")["cnt"]
    active_combat = execute_one("SELECT COUNT(*) as cnt FROM combat_sessions WHERE status='ACTIVE'")["cnt"]
    pending_import = os.path.exists(cfg.PENDING_IMPORT_PATH)
    queue_failed   = execute_one("SELECT COUNT(*) as cnt FROM action_queue WHERE status='FAILED' AND admin_acknowledged_at IS NULL")["cnt"]
    boss_count     = execute_one("SELECT COUNT(*) as cnt FROM bosses WHERE is_active=1")["cnt"]
    special_pool   = execute_one(
        "SELECT COUNT(*) as cnt FROM special_item_registry WHERE status='IN_POOL'"
    )["cnt"]
    active_auctions = execute_one("SELECT COUNT(*) cnt FROM auction_listings WHERE status='ACTIVE'")["cnt"]
    pending_rewards = execute_one("SELECT COUNT(*) cnt FROM world_boss_rewards WHERE status='PENDING'")["cnt"]
    pending_choices = execute_one("SELECT COALESCE(SUM(pending_levelup+pending_perk),0) cnt FROM players WHERE is_banned=0")["cnt"]
    interruptions = execute_one("SELECT COUNT(*) cnt FROM pending_interrupted_actions")["cnt"]

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
        active_auctions=active_auctions, pending_rewards=pending_rewards,
        pending_choices=pending_choices, interruptions=interruptions,
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
    return render_template(
        "admin/players.html", players=players,
        feedback=request.args.get("feedback"), error=request.args.get("error")
    )


def admin_player_replenish_ap(pid: int):
    """Restore an active player to their calculated AP maximum for testing."""
    from database import get_player
    player = get_player(pid)
    if not player:
        return redirect(url_for("admin_players", error="Player not found."))
    if player["retired_at"] or player["is_banned"]:
        return redirect(url_for(
            "admin_players", error="A retired or banned player cannot be replenished."
        ))

    before = player["current_ap"]
    restored = player["max_ap"]
    with exclusive_transaction():
        execute_write("UPDATE players SET current_ap=? WHERE id=?", (restored, pid))
        _audit("REPLENISH_PLAYER_AP", "PLAYER", pid, "Admin testing refill",
               {"before": before, "after": restored})
    return redirect(url_for(
        "admin_players",
        feedback=f"{player['character_name'] or player['username']} AP replenished from {before} to {restored}."
    ))


def admin_replenish_all_ap():
    """Restore every active human and NPC character to their calculated AP maximum."""
    from database import get_player
    rows = execute(
        """SELECT p.id, CASE WHEN np.player_id IS NULL THEN 0 ELSE 1 END AS is_npc
           FROM players p
           LEFT JOIN npc_profiles np ON np.player_id=p.id
           WHERE p.retired_at IS NULL AND p.is_banned=0
             AND (np.player_id IS NULL OR (np.enabled=1 AND np.retired=0))
           ORDER BY p.id"""
    )
    changed = []
    npc_count = 0
    player_count = 0
    with exclusive_transaction():
        for row in rows:
            player = get_player(row["id"])
            if not player:
                continue
            before = player["current_ap"]
            restored = player["max_ap"]
            execute_write("UPDATE players SET current_ap=? WHERE id=?", (restored, row["id"]))
            changed.append({"player_id": row["id"], "before": before, "after": restored})
            if row["is_npc"]:
                npc_count += 1
            else:
                player_count += 1
        _audit(
            "REPLENISH_ALL_AP", "SYSTEM", reason="Admin testing refill",
            details={"players": player_count, "npcs": npc_count, "changes": changed},
        )
    return redirect(url_for(
        "admin_index",
        feedback=f"AP replenished for {player_count} player(s) and {npc_count} NPC(s)."
    ))


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
        "unreviewed_failed_actions": execute_one("SELECT COUNT(*) cnt FROM action_queue WHERE status='FAILED' AND admin_acknowledged_at IS NULL")["cnt"],
        "reviewed_failed_actions": execute_one("SELECT COUNT(*) cnt FROM action_queue WHERE status='FAILED' AND admin_acknowledged_at IS NOT NULL")["cnt"],
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
    failures = execute("""SELECT q.*,p.character_name,
                          (SELECT l.message FROM player_activity_log l
                           WHERE l.queue_id=q.id AND l.status='FAILED'
                           ORDER BY l.id DESC LIMIT 1) AS error_message
                          FROM action_queue q JOIN players p ON p.id=q.player_id
                          WHERE q.status='FAILED' ORDER BY q.id DESC LIMIT 30""")
    audits = execute("SELECT * FROM admin_audit_log ORDER BY id DESC LIMIT 30")
    return render_template("admin/health.html", stats=stats, scheduler_runs=scheduler_runs,
                           failures=failures, audits=audits)


ITEM_TABLES = {"weapon": "weapons", "armor": "armor", "special": "special_items"}
ITEM_EDIT_FIELDS = {
    "weapon": ("name","description","is_active","level","weapon_type","damage_die","damage_type","str_bonus","end_bonus","agi_bonus","lck_bonus","per_bonus","credit_cost","drop_chance","starting_durability"),
    "armor": ("name","description","is_active","level","ac_bonus","res_blade","res_blunt","res_ballistic","res_energy","res_arcane","res_explosive","res_venom","str_bonus","end_bonus","agi_bonus","lck_bonus","per_bonus","credit_cost","drop_chance","starting_durability"),
    "special": ("name","description","is_active","associated_to","association_type","str_bonus","end_bonus","agi_bonus","lck_bonus","per_bonus","initiative_bonus","extra_attack","crit_chance_bonus","crit_dmg_multiplier","ac_bonus","res_blade","res_blunt","res_ballistic","res_energy","res_arcane","res_explosive","res_venom","bonus_damage_type","bonus_damage_amount","credit_cost","drop_chance","starting_durability","steal_bonus","xp_multiplier","credit_multiplier","bonus_ap","hp_regen_bonus","durability_reduction","shop_discount","sell_bonus","encounter_bonus"),
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


def admin_shop():
    """Display current stock and the item definitions available for manual listing."""
    listings = execute("SELECT * FROM shop_listings ORDER BY item_type, listed_at, id")
    tables = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}
    displayed = []
    for listing in listings:
        table = tables.get(listing["item_type"])
        item = execute_one(f"SELECT name FROM {table} WHERE id=?", (listing["item_id"],)) if table else None
        seller = (execute_one("SELECT character_name FROM players WHERE id=?", (listing["seller_player_id"],))
                  if listing.get("seller_player_id") else None)
        displayed.append({**listing, "name": item["name"] if item else "Missing item definition",
                          "seller_name": seller["character_name"] if seller else None})
    choices = {
        "WEAPON": execute("SELECT id,name,credit_cost FROM weapons WHERE is_active=1 ORDER BY name"),
        "ARMOR": execute("SELECT id,name,credit_cost FROM armor WHERE is_active=1 ORDER BY name"),
        "SPECIAL": execute(
            """SELECT s.id,s.name,s.credit_cost FROM special_items s
               JOIN special_item_registry r ON r.special_item_id=s.id
               WHERE s.is_active=1 AND r.status='IN_POOL' ORDER BY s.name"""
        ),
    }
    return render_template("admin/shop.html", listings=displayed, choices=choices)


def admin_shop_populate():
    """Top up system stock to configured rotation sizes without removing existing listings."""
    from scheduler import _populate_shop_rotation, _populate_special_slots
    settings = get_all_settings()
    targets = {
        "WEAPON": int(settings.get("SHOP_WEAPONS_COUNT", cfg.SHOP_WEAPONS_COUNT)),
        "ARMOR": int(settings.get("SHOP_ARMOR_COUNT", cfg.SHOP_ARMOR_COUNT)),
    }
    added = 0
    with exclusive_transaction():
        for item_type, target in targets.items():
            current = execute_one("SELECT COUNT(*) cnt FROM shop_listings WHERE item_type=?", (item_type,))["cnt"]
            needed = max(0, target - current)
            if needed:
                _populate_shop_rotation("weapons" if item_type == "WEAPON" else "armor", needed)
                added += needed
        players = execute_one("SELECT COUNT(*) cnt FROM players WHERE is_banned=0")["cnt"]
        special_target = players // 2
        special_current = execute_one("SELECT COUNT(*) cnt FROM shop_listings WHERE item_type='SPECIAL'")["cnt"]
        special_needed = max(0, special_target - special_current)
        if special_needed:
            before = special_current
            _populate_special_slots(special_needed)
            after = execute_one("SELECT COUNT(*) cnt FROM shop_listings WHERE item_type='SPECIAL'")["cnt"]
            added += after - before
        _audit("POPULATE_SHOP", "SHOP", reason="Admin requested stock top-up",
               details={"listings_added": added, "targets": {**targets, "SPECIAL": special_target}})
    return redirect(url_for("admin_shop", feedback=f"Shop populated: {added} listing(s) added."))


def admin_shop_add():
    """Add one administrator-controlled listing while preserving unique-special ownership."""
    item_type = request.form.get("item_type", "").upper()
    item_id = request.form.get("item_id", type=int)
    price = request.form.get("price", type=int)
    tables = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}
    if item_type not in tables or not item_id or price is None or price < 0:
        return redirect(url_for("admin_shop", error="Select an item and enter a non-negative price."))
    item = execute_one(f"SELECT * FROM {tables[item_type]} WHERE id=? AND is_active=1", (item_id,))
    if not item:
        return redirect(url_for("admin_shop", error="That active item could not be found."))
    with exclusive_transaction():
        if item_type == "SPECIAL":
            registry = execute_one("SELECT * FROM special_item_registry WHERE special_item_id=?", (item_id,))
            if not registry or registry["status"] != "IN_POOL":
                return redirect(url_for("admin_shop", error="That unique special is no longer in the available pool."))
        listing_id = execute_write(
            """INSERT INTO shop_listings(item_type,item_id,listing_source,price)
               VALUES(?,?,'ADMIN',?)""", (item_type, item_id, price))
        if item_type == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry SET status='IN_SHOP',shop_listing_price=?,updated_at=?
                   WHERE special_item_id=?""", (price, datetime.utcnow().isoformat(), item_id))
        _audit("ADD_SHOP_LISTING", item_type, item_id, "Admin manually added shop stock",
               {"listing_id": listing_id, "name": item["name"], "price": price})
    return redirect(url_for("admin_shop", feedback=f"Added {item['name']} to the shop."))


def admin_shop_remove(listing_id: int):
    """Remove one listing; unique specials safely return to the global pool."""
    listing = execute_one("SELECT * FROM shop_listings WHERE id=?", (listing_id,))
    if not listing:
        return redirect(url_for("admin_shop", error="Listing not found."))
    with exclusive_transaction():
        execute_write("DELETE FROM shop_listings WHERE id=?", (listing_id,))
        if listing["item_type"] == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry SET status='IN_POOL',current_owner_player_id=NULL,
                   inventory_item_id=NULL,shop_listing_price=NULL,last_released_method='ADMIN_REMOVED',updated_at=?
                   WHERE special_item_id=?""", (datetime.utcnow().isoformat(), listing["item_id"]))
        _audit("REMOVE_SHOP_LISTING", listing["item_type"], listing["item_id"],
               "Admin removed shop stock", {"listing_id": listing_id, "source": listing["listing_source"]})
    return redirect(url_for("admin_shop", feedback="Listing removed."))


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
    combat_metrics = execute_one(
        """SELECT COUNT(*) total,COALESCE(AVG(current_round),0) avg_rounds,
           SUM(CASE WHEN result LIKE '%ATTACKER%' OR result LIKE '%VICTORY%' THEN 1 ELSE 0 END) attacker_wins,
           SUM(CASE WHEN result LIKE '%DEFENDER%' OR result LIKE '%DEFEAT%' THEN 1 ELSE 0 END) defender_wins
           FROM combat_sessions WHERE status='RESOLVED'"""
    )
    roll_metrics = execute_one(
        """SELECT COUNT(*) actions,
           SUM(CASE WHEN upper(outcome_detail) LIKE '%MISS%' THEN 1 ELSE 0 END) misses,
           SUM(CASE WHEN upper(outcome_detail) LIKE '%DODG%' THEN 1 ELSE 0 END) dodges,
           SUM(CASE WHEN upper(outcome_detail) LIKE '%DAMAGE%' OR upper(outcome_detail) LIKE '%HIT%' THEN 1 ELSE 0 END) hits
           FROM combat_logs"""
    )
    contracts = execute("SELECT status,COUNT(*) cnt FROM player_daily_contracts GROUP BY status ORDER BY cnt DESC")
    auctions = execute("SELECT status,COUNT(*) cnt FROM auction_listings GROUP BY status ORDER BY cnt DESC")
    perks = execute("""SELECT p.name action,'' status,COUNT(pp.id) cnt FROM perks p
                       LEFT JOIN player_perks pp ON pp.perk_id=p.id GROUP BY p.id ORDER BY cnt DESC,p.name""")
    crews = execute("""SELECT c.name action,'' status,COUNT(cm.player_id) cnt FROM crews c
                       LEFT JOIN crew_memberships cm ON cm.crew_id=c.id WHERE c.disbanded_at IS NULL
                       GROUP BY c.id ORDER BY cnt DESC""")
    return render_template("admin/analytics.html", action_counts=action_counts, economy=economy,
                           combats=combats, item_events=item_events,
                           npc_decisions=npc_decisions, random_events=random_events,
                           combat_metrics=combat_metrics, roll_metrics=roll_metrics,
                           contracts=contracts, auctions=auctions, perks=perks, crews=crews)
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
    from database import get_player_bonus_profile, get_player_perks
    from reputations import reputation_profile
    perks = get_player_perks(pid)
    bonuses = get_player_bonus_profile(pid)
    contract = execute_one(
        """SELECT pdc.*,c.name,c.description,c.metric,c.target,c.reward_xp,c.reward_credits,c.reward_ap
           FROM player_daily_contracts pdc JOIN contracts c ON c.id=pdc.contract_id
           WHERE pdc.player_id=? ORDER BY pdc.contract_date DESC LIMIT 1""", (pid,)
    )
    crew = execute_one(
        """SELECT cm.*,c.name,c.tag FROM crew_memberships cm JOIN crews c ON c.id=cm.crew_id
           WHERE cm.player_id=?""", (pid,)
    )
    world_boss = execute(
        """SELECT wbc.*,wb.name,we.status FROM world_boss_contributions wbc
           JOIN world_boss_events we ON we.id=wbc.event_id JOIN world_bosses wb ON wb.id=we.world_boss_id
           WHERE wbc.player_id=? ORDER BY wbc.event_id DESC LIMIT 20""", (pid,)
    )
    level_history = execute("SELECT * FROM level_up_history WHERE player_id=? ORDER BY level_reached DESC", (pid,))
    effects = execute("SELECT * FROM status_effects WHERE player_id=? ORDER BY id", (pid,))
    active_combat = execute_one(
        """SELECT * FROM combat_sessions WHERE status='ACTIVE'
           AND (attacker_player_id=? OR defender_player_id=?) ORDER BY id DESC LIMIT 1""", (pid, pid)
    )
    interrupted = execute_one("SELECT * FROM pending_interrupted_actions WHERE player_id=?", (pid,))
    auctions = execute("SELECT * FROM auction_listings WHERE seller_player_id=? OR current_bidder_id=? ORDER BY id DESC LIMIT 20", (pid, pid))
    return render_template("admin/player_detail.html",
                           player=player, stats=stats,
                           inventory=inventory, history=history,
                           boss_kills=boss_kills, perks=perks, bonuses=bonuses,
                           reputation=reputation_profile(pid), contract=contract, crew=crew,
                           world_boss=world_boss, level_history=level_history, effects=effects,
                           active_combat=active_combat, interrupted=interrupted, auctions=auctions,
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
        from routes.auction import release_player_auctions
        release_player_auctions(pid)
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
        from routes.auction import release_player_auctions
        release_player_auctions(pid)
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
                  (SELECT COUNT(*) FROM inventory_items ii WHERE ii.player_id=p.id AND ii.item_type='SPECIAL') special_count,
                  (SELECT COUNT(*) FROM player_perks pp WHERE pp.player_id=p.id) perk_count,
                  (SELECT cr.name FROM crew_memberships cm JOIN crews cr ON cr.id=cm.crew_id WHERE cm.player_id=p.id) crew_name,
                  (SELECT ct.name FROM player_daily_contracts dc JOIN contracts ct ON ct.id=dc.contract_id
                   WHERE dc.player_id=p.id ORDER BY dc.contract_date DESC LIMIT 1) contract_name
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
    for log in logs:
        try:
            log["details"] = json.loads(log.get("details_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            log["details"] = {}
    inventory = execute(
        """SELECT ii.*,CASE ii.item_type WHEN 'WEAPON' THEN w.name WHEN 'ARMOR' THEN a.name ELSE si.name END item_name
           FROM inventory_items ii LEFT JOIN weapons w ON w.id=ii.item_id AND ii.item_type='WEAPON'
           LEFT JOIN armor a ON a.id=ii.item_id AND ii.item_type='ARMOR'
           LEFT JOIN special_items si ON si.id=ii.item_id AND ii.item_type='SPECIAL'
           WHERE ii.player_id IN (SELECT player_id FROM npc_profiles) ORDER BY ii.player_id,ii.item_type"""
    )
    return render_template("admin/npcs.html", npcs=npcs, classes=classes, items=items,
                           inventory=inventory, logs=logs)


def admin_npc_audit():
    """Compare NPC profiles with decisions, combat behavior, and rule warnings."""
    today = datetime.utcnow().date().isoformat()
    start = request.args.get("start", today)
    end = request.args.get("end", today)
    try:
        datetime.strptime(start, "%Y-%m-%d")
        datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        return redirect(url_for("admin_npc_audit", error="Dates must use YYYY-MM-DD."))
    npc_id = request.args.get("npc_id", type=int)
    profiles = execute(
        """SELECT p.id,p.character_name,p.current_ap,p.in_combat,np.*
           FROM npc_profiles np JOIN players p ON p.id=np.player_id
           ORDER BY np.retired,p.character_name"""
    )
    selected_profiles = [p for p in profiles if not npc_id or p["id"] == npc_id]
    start_at, end_at = f"{start} 00:00:00", f"{end} 23:59:59"
    ids = {p["id"] for p in selected_profiles}
    summaries = {}
    for profile in selected_profiles:
        motivations = {"Hunter": profile["player_hunter"], "Boss Killer": profile["boss_killer"],
                       "World Boss Hunter": profile["world_boss_hunter"],
                       "Hoarder": profile["hoarder"], "Thief": profile["thief"]}
        leaders = [name for name, score in motivations.items() if score == max(motivations.values())]
        summaries[profile["id"]] = {
            "profile": profile, "archetype": leaders[0] if len(leaders) == 1 else "Hybrid",
            "decisions": {}, "actions": {}, "results": {}, "combats": 0,
            "escapes": 0, "round_limits": 0, "round_total": 0, "max_round": 0,
            "failures": 0, "alerts": [],
        }

    decision_rows = execute(
        """SELECT l.*,p.character_name FROM npc_action_log l JOIN players p ON p.id=l.player_id
           WHERE l.occurred_at BETWEEN ? AND ? ORDER BY l.id DESC""", (start_at, end_at))
    decision_rows = [row for row in decision_rows if row["player_id"] in ids]
    for row in decision_rows:
        summary = summaries[row["player_id"]]
        summary["decisions"][row["decision"]] = summary["decisions"].get(row["decision"], 0) + 1
        lowered = row["result"].lower()
        if any(term in lowered for term in ("not enough", "failed", "remains active", "error")):
            summary["failures"] += 1

    combat_rows = execute(
        """SELECT cs.* FROM combat_sessions cs
           WHERE cs.started_at BETWEEN ? AND ? ORDER BY cs.id DESC""", (start_at, end_at))
    combat_rows = [row for row in combat_rows if row["attacker_player_id"] in ids]
    for combat in combat_rows:
        summary = summaries[combat["attacker_player_id"]]
        summary["combats"] += 1
        summary["round_total"] += combat["current_round"]
        summary["max_round"] = max(summary["max_round"], combat["current_round"])
        result_label = combat["result"] or combat["status"]
        summary["results"][result_label] = summary["results"].get(result_label, 0) + 1
        if combat["result"] == "ESCAPE": summary["escapes"] += 1
        if combat["result"] == "SCORE_WIN": summary["round_limits"] += 1

    action_rows = execute(
        """SELECT cs.attacker_player_id,cl.action_type,COUNT(*) cnt
           FROM combat_logs cl JOIN combat_sessions cs ON cs.id=cl.combat_session_id
           WHERE cs.started_at BETWEEN ? AND ? AND cl.actor='ATTACKER'
           GROUP BY cs.attacker_player_id,cl.action_type""", (start_at, end_at))
    for row in action_rows:
        if row["attacker_player_id"] in ids:
            summaries[row["attacker_player_id"]]["actions"][row["action_type"]] = row["cnt"]

    for summary in summaries.values():
        profile = summary["profile"]
        if profile["current_ap"] < 0:
            summary["alerts"].append("Negative AP")
        if profile["in_combat"] and not execute_one(
            """SELECT 1 FROM combat_sessions WHERE status='ACTIVE'
               AND (attacker_player_id=? OR defender_player_id=?)""", (profile["id"], profile["id"])):
            summary["alerts"].append("Combat flag has no active session")
        if summary["failures"]:
            summary["alerts"].append(f"{summary['failures']} failed or blocked decisions")
        if summary["max_round"] > 20:
            summary["alerts"].append(f"Combat reached round {summary['max_round']}")
        summary["avg_round"] = (summary["round_total"] / summary["combats"]
                                if summary["combats"] else 0)

    return render_template(
        "admin/npc_audit.html", profiles=profiles, summaries=list(summaries.values()),
        recent=decision_rows[:100], start=start, end=end, selected_npc=npc_id,
        total_decisions=len(decision_rows), total_combats=len(combat_rows),
        total_alerts=sum(len(s["alerts"]) for s in summaries.values()),
    )


def admin_npc_edit(pid: int):
    """Render or process the npc edit administrative workflow."""
    fields = {}
    for name in ("player_hunter", "boss_killer", "world_boss_hunter", "hoarder", "thief", "aggression",
                 "self_preservation", "repair_tendency"):
        fields[name] = max(0, min(100, request.form.get(name, type=int, default=0)))
    fields["actions_per_day"] = max(1, min(24, request.form.get(
        "actions_per_day", type=int, default=4
    )))
    fields["enabled"] = 1 if request.form.get("enabled") else 0
    with exclusive_transaction():
        execute_write(
            """UPDATE npc_profiles SET player_hunter=?,boss_killer=?,world_boss_hunter=?,hoarder=?,thief=?,aggression=?,
               self_preservation=?,repair_tendency=?,actions_per_day=?,enabled=? WHERE player_id=?""",
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


def admin_npc_replenish_ap(pid: int):
    """Restore one active NPC to its normal AP maximum for controlled testing."""
    from database import get_player
    profile = execute_one("SELECT * FROM npc_profiles WHERE player_id=?", (pid,))
    player = get_player(pid)
    if not profile or not player:
        return redirect(url_for("admin_npcs", error="NPC not found."))
    if profile["retired"] or player["is_banned"]:
        return redirect(url_for("admin_npcs", error="A retired NPC cannot be replenished."))
    before = player["current_ap"]
    restored = player["max_ap"]
    with exclusive_transaction():
        execute_write("UPDATE players SET current_ap=? WHERE id=?", (restored, pid))
        _audit("REPLENISH_NPC_AP", "PLAYER", pid, "Admin testing refill",
               {"before": before, "after": restored})
    return redirect(url_for(
        "admin_npcs",
        feedback=f"{player['character_name']} AP replenished from {before} to {restored}."
    ))


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
            """INSERT INTO npc_profiles(player_id,player_hunter,boss_killer,world_boss_hunter,hoarder,thief,
               aggression,self_preservation,repair_tendency) VALUES(?,?,?,?,?,?,?,?,?)""",
            (pid, *scores)
        )
    from routes.auth import _award_starter_gear
    from npc import _equip_best_items
    _award_starter_gear(pid)
    profile = execute_one("SELECT * FROM npc_profiles WHERE player_id=?", (pid,))
    _equip_best_items(pid, profile)
    from contracts import ensure_daily_contract
    ensure_daily_contract(pid)
    return pid


def _npc_scores_from_form(form):
    # Presets populate the visible form in the browser. Always save the visible
    # values so an administrator can select a preset and then customize it.
    """Provide the internal npc scores from form operation used by this module."""
    return tuple(max(0, min(100, form.get(key, type=int, default=default)))
                 for key, default in (
                     ("player_hunter", 100), ("boss_killer", 0), ("world_boss_hunter", 0),
                     ("hoarder", 0), ("thief", 0), ("aggression", 85),
                     ("self_preservation", 35), ("repair_tendency", 55)))


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def admin_config():
    """Render or process the config administrative workflow."""
    feedback = error = None

    if request.method == "POST":
        if request.form.get("action") == "reset_enemy_balance":
            reset_values = {
                "MINION_HP_SCALE": cfg.MINION_HP_SCALE,
                "BOSS_HP_SCALE": cfg.BOSS_HP_SCALE,
                "ENEMY_DAMAGE_SCALE": cfg.ENEMY_DAMAGE_SCALE,
            }
            with exclusive_transaction():
                for name, reset_value in reset_values.items():
                    execute_write(
                        """INSERT INTO settings (constant_name,value,imported_at)
                           VALUES (?,?,?)
                           ON CONFLICT(constant_name) DO UPDATE SET
                               value=excluded.value, imported_at=excluded.imported_at""",
                        (name, str(reset_value), datetime.utcnow().isoformat())
                    )
                _audit("RESET_ENEMY_BALANCE", "SETTING", details=reset_values)
            feedback = "Enemy balance controls restored to their recommended testing values."
            constant = value = ""
        else:
            constant = request.form.get("constant_name", "").strip()
            value    = request.form.get("value", "").strip()
        if constant in {"MINION_HP_SCALE", "BOSS_HP_SCALE", "ENEMY_DAMAGE_SCALE"}:
            try:
                numeric_value = float(value)
                if not 0.10 <= numeric_value <= 2.00:
                    raise ValueError
                value = str(round(numeric_value, 2))
            except ValueError:
                error = "Enemy balance values must be between 0.10 (10%) and 2.00 (200%)."
                constant = ""
        if constant and value:
            with exclusive_transaction():
                execute_write(
                    """INSERT INTO settings (constant_name, value, imported_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(constant_name) DO UPDATE SET
                           value=excluded.value, imported_at=excluded.imported_at""",
                    (constant, value, datetime.utcnow().isoformat())
                )
                _audit("EDIT_CONFIG", "SETTING", reason=constant, details={"value": value})
            feedback = f"Setting '{constant}' updated to '{value}'."
        elif request.form.get("action") != "reset_enemy_balance" and not error:
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

    import sqlite3, os, shutil

    # Validate the staged workbook before deleting anything. A malformed file
    # must never leave the game empty without the revised content available.
    if os.path.exists(cfg.PENDING_IMPORT_PATH):
        from importer import parse_workbook, validate
        try:
            staged_errors = validate(parse_workbook(cfg.PENDING_IMPORT_PATH))
        except Exception as exc:
            staged_errors = [f"Could not read staged workbook: {exc}"]
        if staged_errors:
            logger.error("Full reset cancelled; staged import is invalid: %s", staged_errors)
            return redirect(
                url_for("admin_index")
                + "?error=Full+reset+cancelled:+the+staged+workbook+failed+validation."
            )

    logger.warning("Admin: initiating FULL GAME RESET")

    # Keep a recoverable snapshot beside the database before the destructive step.
    backup_dir = os.path.join(os.path.dirname(cfg.DB_PATH), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(
        backup_dir, f"game_pre_reset_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
    )
    shutil.copy2(cfg.DB_PATH, backup_path)
    logger.warning("Pre-reset database backup created at %s", backup_path)

    # Drop all operational tables (content tables survive)
    operational = [
        "world_boss_event_log", "world_boss_rewards", "world_boss_contributions",
        "world_boss_events",
        "scene_effects", "scene_attempts",
        "pending_interrupted_actions", "auction_listings",
        "npc_action_log", "npc_profiles", "player_activity_log",
        "combat_buffs", "combat_logs", "combat_sessions",
        "boss_instances", "minion_instances", "boss_intel",
        "inventory_items", "item_history", "special_item_registry",
        "shop_listings", "daily_feed", "action_queue",
        "player_stats", "player_perks", "level_up_history", "status_effects", "players",
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

    # Re-import if staged file exists
    if os.path.exists(cfg.PENDING_IMPORT_PATH):
        from importer import run_import
        # Content tables survive a player reset; update them in place instead
        # of attempting duplicate inserts for existing named content.
        result = run_import(cfg.PENDING_IMPORT_PATH, full_reset=False)
        logger.info("Post-reset import: %s", result)
        if not result.get("success"):
            logger.error("Post-reset import failed; backup available at %s", backup_path)
            return redirect(
                url_for("admin_index")
                + "?error=Players+were+reset+but+content+import+failed.+Restore+the+automatic+backup."
            )

    # Build the unique-special pool only after the revised catalog is active.
    with exclusive_transaction():
        execute_write("DELETE FROM special_item_registry")
        specials = execute(
            "SELECT id FROM special_items WHERE is_active=1 AND association_type<>'WorldBoss'"
        )
        for s in specials:
            execute_write(
                "INSERT INTO special_item_registry (special_item_id, status) VALUES (?, 'IN_POOL')",
                (s["id"],)
            )

    logger.warning("Admin: FULL GAME RESET complete")
    return redirect(
        url_for("admin_index")
        + "?feedback=Full+game+reset+complete.+A+pre-reset+database+backup+was+saved."
    )


# ─────────────────────────────────────────────────────────────────────────────
# LOGS
# ─────────────────────────────────────────────────────────────────────────────

def admin_logs():
    """Render or process the logs administrative workflow."""
    import os
    show_reviewed = request.args.get("show") == "all"

    def read_tail(path: str, n: int = 100) -> list[str]:
        """Handle the read tail workflow."""
        if not os.path.exists(path):
            return []
        with open(path, "r") as f:
            return f.readlines()[-n:]

    import_errors = read_tail(cfg.IMPORT_ERROR_LOG)
    orphan_log    = read_tail(cfg.ORPHAN_LOG)
    failed_queue = execute(
        """SELECT q.*, p.character_name, l.message AS error_message,
                  l.details_json, cs.combat_type, cs.status AS combat_status,
                  cs.result AS combat_result, cs.current_round,
                  EXISTS(
                    SELECT 1 FROM action_queue later
                    WHERE later.player_id=q.player_id
                      AND later.action_type=q.action_type
                      AND later.status='DONE' AND later.created_at>q.created_at
                      AND COALESCE(json_extract(later.payload,'$.session_id'),-1)
                          = COALESCE(json_extract(q.payload,'$.session_id'),-1)
                  ) AS later_succeeded
           FROM action_queue q
           LEFT JOIN players p ON p.id=q.player_id
           LEFT JOIN player_activity_log l ON l.queue_id=q.id AND l.status='FAILED'
           LEFT JOIN combat_sessions cs
             ON cs.id=json_extract(q.payload,'$.session_id')
           WHERE q.status='FAILED' AND (? OR q.admin_acknowledged_at IS NULL)
           ORDER BY q.created_at DESC LIMIT 50""", (int(show_reviewed),)
    )
    failure_counts = execute_one(
        """SELECT SUM(CASE WHEN admin_acknowledged_at IS NULL THEN 1 ELSE 0 END) unreviewed,
                  SUM(CASE WHEN admin_acknowledged_at IS NOT NULL THEN 1 ELSE 0 END) reviewed
           FROM action_queue WHERE status='FAILED'"""
    )
    for row in failed_queue:
        try:
            row["payload_data"] = json.loads(row.get("payload") or "{}")
        except (TypeError, json.JSONDecodeError):
            row["payload_data"] = {"raw": row.get("payload")}
        try:
            row["details_data"] = json.loads(row.get("details_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            row["details_data"] = {"raw": row.get("details_json")}

    return render_template("admin/logs.html",
                           import_errors=import_errors,
                           orphan_log=orphan_log,
                           failed_queue=failed_queue,
                           failure_counts=failure_counts,
                           show_reviewed=show_reviewed)


################################################################################
