"""Process auditable player actions synchronously through registered handlers."""
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


def _combat_context(player_id: int, session_id: int | None) -> dict:
    """Return stable names and summary state for an action tied to combat."""
    if not session_id:
        return {}
    row = execute_one(
        """SELECT cs.id,cs.combat_type,cs.status,cs.result,cs.current_round,
                  cs.attacker_player_id,cs.defender_player_id,
                  attacker.character_name AS attacker_name,
                  defender.character_name AS defender_name,
                  b.name AS boss_name,m.name AS minion_name,wb.name AS world_boss_name
           FROM combat_sessions cs
           LEFT JOIN players attacker ON attacker.id=cs.attacker_player_id
           LEFT JOIN players defender ON defender.id=cs.defender_player_id
           LEFT JOIN boss_instances bi ON bi.id=cs.boss_instance_id
           LEFT JOIN bosses b ON b.id=bi.boss_id
           LEFT JOIN minion_instances mi ON mi.id=cs.minion_instance_id
           LEFT JOIN minions m ON m.id=mi.minion_id
           LEFT JOIN world_boss_events wbe ON wbe.id=cs.world_boss_event_id
           LEFT JOIN world_bosses wb ON wb.id=wbe.world_boss_id
           WHERE cs.id=?""", (session_id,)
    )
    if not row:
        return {"combat_session_id": session_id}
    opponent = (row["defender_name"] if player_id == row["attacker_player_id"]
                else row["attacker_name"])
    if row["combat_type"] == "BOSS":
        opponent = row["boss_name"]
    elif row["combat_type"] == "MINION":
        opponent = row["minion_name"]
    elif row["combat_type"] == "WORLD_BOSS":
        opponent = row["world_boss_name"]
    return {
        "combat_session_id": row["id"], "combat_type": row["combat_type"],
        "opponent": opponent, "player_role": ("ATTACKER" if player_id == row["attacker_player_id"] else "DEFENDER"),
        "round": row["current_round"], "combat_status": row["status"],
        "combat_result": row["result"],
    }


def _activity_details(player_id: int, action_type: str, payload: dict,
                      result: dict | None = None, error: Exception | None = None) -> dict:
    """Build structured diagnostic details for the permanent activity log."""
    result = result or {}
    session_id = result.get("session_id") or payload.get("session_id")
    details = {
        "input": payload,
        "result": result,
        "context": _combat_context(player_id, session_id),
    }
    if error:
        details["error"] = {"type": type(error).__name__, "message": str(error)}
    player = execute_one(
        "SELECT level,current_hp,current_ap,credits,in_combat FROM players WHERE id=?",
        (player_id,)
    )
    if player:
        details["player_state_after"] = dict(player)
    return details


def _activity_message(action_type: str, details: dict) -> str:
    """Create a concise human-readable summary while JSON retains full detail."""
    context = details.get("context", {})
    opponent = context.get("opponent")
    labels = {
        "start_pvp_fight": "Started PvP combat", "start_boss_fight": "Started boss combat",
        "start_world_boss_fight": "Started world-boss combat",
        "combat_action": "Completed a combat round", "combat_steal": "Attempted a combat steal",
        "combat_resolve": "Resolved combat by score", "combat_extend": "Extended combat",
        "shop_buy": "Purchased an item", "shop_sell": "Sold an item",
        "blacksmith_repair": "Repaired equipment", "tavern_heal": "Healed at the Tavern",
        "assign_levelup": "Assigned a level-up point",
    }
    message = labels.get(action_type, action_type.replace("_", " ").capitalize())
    if opponent:
        message += f" against {opponent}"
    if context.get("combat_session_id"):
        message += f" (combat #{context['combat_session_id']})"
    return message


def register_handler(action_type: str):
    """Decorator to register an action handler function.

    Usage:
        @register_handler('tavern_heal')
        def handle_tavern_heal(player_id, payload):
            ...
    """
    def decorator(fn):
        """Handle the decorator workflow."""
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
            details = _activity_details(player_id, action_type, payload, result=result)
            execute_write(
                "UPDATE action_queue SET status = 'DONE', processed_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), queue_id)
            )
            execute_write(
                """INSERT INTO player_activity_log
                   (player_id,category,action,status,message,details_json,queue_id,source)
                   VALUES(?, 'ACTION', ?, 'SUCCESS', ?, ?, ?, 'GAME')""",
                (player_id, action_type, _activity_message(action_type, details),
                 json.dumps(details, default=str)[:8000], queue_id)
            )
        return result

    except Exception as exc:
        try:
            with exclusive_transaction():
                details = _activity_details(player_id, action_type, payload, error=exc)
                execute_write(
                    "UPDATE action_queue SET status = 'FAILED', processed_at = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), queue_id)
                )
                execute_write(
                    """INSERT INTO player_activity_log
                       (player_id,category,action,status,message,details_json,queue_id,source)
                       VALUES(?, 'ERROR', ?, 'FAILED', ?, ?, ?, 'GAME')""",
                    (player_id, action_type, str(exc)[:1000],
                     json.dumps(details, default=str)[:8000], queue_id)
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
    """Provide the internal ap cost for action operation used by this module."""
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
