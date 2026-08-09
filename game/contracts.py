"""Daily contract assignment, progress, rewards, and midnight turnover."""

from datetime import datetime, timezone

from database import execute, execute_one, execute_write, exclusive_transaction, get_all_settings
from combat import engine
import config_defaults as cfg


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def ensure_daily_contract(player_id: int) -> dict | None:
    """Return today's assignment, creating one eligible objective when needed."""
    today = _today()
    row = _assignment(player_id, today)
    if row:
        return row
    player = execute_one("SELECT level FROM players WHERE id=? AND is_banned=0", (player_id,))
    if not player:
        return None
    contract = execute_one(
        """SELECT * FROM contracts
           WHERE is_active=1 AND min_level<=?
           ORDER BY RANDOM() LIMIT 1""", (player["level"],)
    )
    if not contract:
        return None
    with exclusive_transaction():
        execute_write(
            """INSERT OR IGNORE INTO player_daily_contracts
               (player_id,contract_id,contract_date) VALUES(?,?,?)""",
            (player_id, contract["id"], today),
        )
    return _assignment(player_id, today)


def _assignment(player_id: int, date: str) -> dict | None:
    return execute_one(
        """SELECT pdc.*,c.name,c.description,c.metric,c.target,
                  c.reward_xp,c.reward_credits,c.reward_ap
           FROM player_daily_contracts pdc JOIN contracts c ON c.id=pdc.contract_id
           WHERE pdc.player_id=? AND pdc.contract_date=?""", (player_id, date)
    )


def record_progress(player_id: int, metric: str, amount: int = 1) -> dict | None:
    """Increment the matching daily objective and atomically award completion prizes."""
    assignment = ensure_daily_contract(player_id)
    if not assignment or assignment["status"] != "ACTIVE" or assignment["metric"] != metric:
        return assignment
    new_progress = min(assignment["target"], assignment["progress"] + max(0, int(amount)))
    completed = new_progress >= assignment["target"]
    now = datetime.utcnow().isoformat()
    with exclusive_transaction():
        execute_write(
            """UPDATE player_daily_contracts SET progress=?,status=?,completed_at=?
               WHERE id=? AND status='ACTIVE'""",
            (new_progress, "COMPLETED" if completed else "ACTIVE", now if completed else None,
             assignment["id"]),
        )
        if completed:
            from crews import contribute_earnings
            net_xp, net_credits = contribute_earnings(
                player_id, assignment["reward_xp"], assignment["reward_credits"], "DAILY_CONTRACT"
            )
            cap = int(get_all_settings().get("AP_CARRYOVER_CAP", cfg.AP_CARRYOVER_CAP))
            execute_write(
                """UPDATE players SET xp=xp+?,credits=credits+?,
                   current_ap=MIN(?,current_ap+?) WHERE id=?""",
                (net_xp, net_credits, cap,
                 assignment["reward_ap"], player_id),
            )
            message = (f"Daily contract complete: {assignment['name']}. "
                       f"+{assignment['reward_xp']} XP, +{assignment['reward_credits']} credits, "
                       f"+{assignment['reward_ap']} AP.")
            execute_write(
                """INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category)
                   VALUES('PERSONAL',?,?,'CONTRACT')""", (player_id, message)
            )
    if completed:
        from crews import record_crew_score
        record_crew_score(player_id, "CONTRACT_COMPLETE", 4)
        p = execute_one("SELECT xp,level FROM players WHERE id=?", (player_id,))
        engine.check_level_up(player_id, p["xp"], p["level"])
    return _assignment(player_id, _today())


def midnight_contract_turnover() -> None:
    """Expire unfinished prior objectives and assign a fresh one to every active character."""
    today = _today()
    with exclusive_transaction():
        execute_write(
            """UPDATE player_daily_contracts SET status='EXPIRED'
               WHERE status='ACTIVE' AND contract_date<>?""", (today,)
        )
    for player in execute("SELECT id FROM players WHERE is_banned=0 AND retired_at IS NULL"):
        ensure_daily_contract(player["id"])
