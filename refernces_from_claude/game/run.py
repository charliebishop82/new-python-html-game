#!/usr/bin/env python3
"""
run.py — Development entry point.

Production:
  gunicorn "app:create_app()" --bind 0.0.0.0:5000 --workers 1
  Single worker only — SQLite + APScheduler are not multi-process safe.

Environment variables:
  GAME_SECRET_KEY  — Flask secret key (required in production)
  ADMIN_PASSWORD   — Admin panel HTTP Basic Auth password (optional)
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
app = create_app()

if __name__ == "__main__":
    app.run(
        debug=True,
        use_reloader=False,  # Prevents APScheduler from running twice in debug mode
        port=5000,
        host="127.0.0.1"
    )
