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
            execute_write(
                """INSERT INTO player_activity_log
                   (player_id,category,action,status,message,details_json,queue_id,source)
                   VALUES(?, 'ACTION', ?, 'SUCCESS', ?, ?, ?, 'GAME')""",
                (player_id, action_type, f"{action_type} completed",
                 json.dumps(result, default=str)[:8000], queue_id)
            )
        return result

    except Exception as exc:
        try:
            with exclusive_transaction():
                execute_write(
                    "UPDATE action_queue SET status = 'FAILED', processed_at = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), queue_id)
                )
                execute_write(
                    """INSERT INTO player_activity_log
                       (player_id,category,action,status,message,details_json,queue_id,source)
                       VALUES(?, 'ERROR', ?, 'FAILED', ?, ?, ?, 'GAME')""",
                    (player_id, action_type, str(exc)[:1000],
                     json.dumps({"exception_type": type(exc).__name__}), queue_id)
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
