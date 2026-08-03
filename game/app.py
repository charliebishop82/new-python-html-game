"""Main Flask application factory, request guards, and background-job setup."""
# app.py
# Main Flask application factory.

import logging
from datetime import datetime, timezone

from flask import Flask, session, redirect, url_for, g, request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config_defaults as cfg
from database import get_db, close_db, init_db, get_player, get_all_settings
from queue_handler import startup_cleanup

logger = logging.getLogger(__name__)

_AUTH_EXEMPT = {
    "auth.login", "auth.login_post",
    "auth.register", "auth.register_post",
    "static",
}
_LEVELUP_EXEMPT = {"auth.levelup", "auth.levelup_post", "auth.logout", "static"}


def create_app() -> Flask:
    """Handle the create app workflow."""
    app = Flask(__name__)
    app.secret_key = cfg.SECRET_KEY

    init_db()
    startup_cleanup()

    app.teardown_appcontext(close_db)
    _register_blueprints(app)
    app.context_processor(_context_processor)
    app.before_request(_check_auth)
    app.before_request(_load_player)
    app.before_request(_check_levelup)
    app.before_request(_set_blackout_flag)
    _start_scheduler(app)

    return app


def _register_blueprints(app: Flask):
    """Provide the internal register blueprints operation used by this module."""
    from routes.auth        import bp as auth_bp
    from routes.dashboard   import bp as dashboard_bp
    from routes.actions     import bp as actions_bp
    from routes.combat      import bp as combat_bp
    from routes.shop        import bp as shop_bp
    from routes.blacksmith  import bp as blacksmith_bp
    from routes.character   import bp as character_bp
    from routes.scoreboards import bp as scoreboards_bp
    from routes.feeds       import bp as feeds_bp

    for bp in [auth_bp, dashboard_bp, actions_bp, combat_bp, shop_bp,
               blacksmith_bp, character_bp, scoreboards_bp, feeds_bp]:
        app.register_blueprint(bp)


def _context_processor() -> dict:
    """Provide the internal context processor operation used by this module."""
    settings = get_all_settings()
    player = g.get("player")
    if not player:
        return {"settings": settings}
    return {"player": player, "settings": settings}


def _check_auth():
    """Provide the internal check auth operation used by this module."""
    if request.endpoint in _AUTH_EXEMPT:
        return None
    if not session.get("player_id"):
        return redirect(url_for("auth.login"))
    return None


def _load_player():
    """Load the authenticated player before route handlers access ``g.player``."""
    player_id = session.get("player_id")
    if not player_id:
        return None
    player = get_player(player_id)
    if player is None:
        session.clear()
        return redirect(url_for("auth.login"))
    g.player = player
    return None


def _check_levelup():
    """Provide the internal check levelup operation used by this module."""
    if request.endpoint in _LEVELUP_EXEMPT:
        return None
    player = g.get("player")
    if player and player.get("pending_levelup") and not player.get("in_combat"):
        return redirect(url_for("auth.levelup"))
    return None


def _set_blackout_flag():
    """Provide the internal set blackout flag operation used by this module."""
    settings = get_all_settings()
    blackout_mins = settings.get("MIDNIGHT_BLACKOUT_MINUTES", cfg.MIDNIGHT_BLACKOUT_MINUTES)
    now = datetime.now(timezone.utc)
    minutes_to_midnight = (24 * 60) - (now.hour * 60 + now.minute)
    g.blackout = (minutes_to_midnight <= blackout_mins)


def _start_scheduler(app: Flask):
    """Provide the internal start scheduler operation used by this module."""
    from scheduler import midnight_reset, ap_trickle
    from npc import run_due_npc_turns

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        func=lambda: _run_with_context(app, midnight_reset),
        trigger=CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="midnight_reset", name="Midnight Reset",
        replace_existing=True, misfire_grace_time=300,
    )
    scheduler.add_job(
        func=lambda: _run_with_context(app, ap_trickle),
        trigger=CronTrigger(hour="3,9,15,21", minute=0, timezone="UTC"),
        id="ap_trickle", name="AP Trickle",
        replace_existing=True, misfire_grace_time=300,
    )
    scheduler.add_job(
        func=lambda: _run_with_context(app, run_due_npc_turns),
        trigger=CronTrigger(minute="*/5", timezone="UTC"),
        id="npc_turns", name="NPC Turns",
        replace_existing=True, misfire_grace_time=240,
    )
    scheduler.start()
    logger.info("APScheduler started")


def _run_with_context(app: Flask, fn):
    """Provide the internal run with context operation used by this module."""
    with app.app_context():
        from database import execute_write, exclusive_transaction
        started = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        with exclusive_transaction():
            run_id = execute_write(
                "INSERT INTO scheduler_run_log(job_name,status,started_at) VALUES(?, 'RUNNING', ?)",
                (fn.__name__, started)
            )
        try:
            result = fn()
            with exclusive_transaction():
                execute_write(
                    "UPDATE scheduler_run_log SET status='SUCCESS',result_summary=?,finished_at=? WHERE id=?",
                    (str(result)[:2000], datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), run_id)
                )
        except Exception as exc:
            with exclusive_transaction():
                execute_write(
                    "UPDATE scheduler_run_log SET status='FAILED',result_summary=?,finished_at=? WHERE id=?",
                    (str(exc)[:2000], datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), run_id)
                )
            logger.exception("Scheduled job '%s' raised an exception", fn.__name__)


################################################################################
