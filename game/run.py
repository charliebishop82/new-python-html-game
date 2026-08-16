#!/usr/bin/env python3
"""
run.py — Development entry point.

Production:
  gunicorn "app:create_app()" --bind 0.0.0.0:5000 --workers 1
  Single worker only — SQLite + APScheduler are not multi-process safe.

Environment variables:
  GAME_SECRET_KEY  — Flask secret key (required in production)
  ADMIN_PASSWORD   — Admin panel HTTP Basic Auth password (optional)
  GAME_HOST        — Bind address (defaults to 0.0.0.0 for LAN play)
  GAME_PORT        — Player-server port (defaults to 5000)
"""
import logging, os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

if not os.environ.get("GAME_SECRET_KEY"):
    logging.warning(
        "GAME_SECRET_KEY not set — using insecure default. "
        "Set this before exposing to a network."
    )

from app import create_app
# Directly running this script grants the configured AP trickle once, then the
# scheduler begins its configured interval from this server start.
app = create_app(award_startup_trickle=__name__ == "__main__")

if __name__ == "__main__":
    # Bind the player application to every local network interface so another
    # device on the same trusted Wi-Fi can use this computer's private IP.
    # The interactive Flask debugger must never be exposed over that binding.
    host = os.environ.get("GAME_HOST", "0.0.0.0")
    port = int(os.environ.get("GAME_PORT", "5000"))
    app.run(
        debug=False,
        use_reloader=False,  # Prevents APScheduler from running twice in debug mode
        port=port,
        host=host,
    )
