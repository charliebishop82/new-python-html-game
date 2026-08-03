################################################################################
# PHASE 2 CODE — Auth, Dashboard, Feeds, CSS, JS
# BBS-Inspired Multiplayer Dueling Game
#
# Files included:
#   1. routes/auth.py
#   2. routes/dashboard.py
#   3. routes/feeds.py
#   4. templates/base.html
#   5. templates/dashboard.html
#   6. templates/auth/ (login, register, character_create, levelup — combined)
#   7. static/style.css
#   8. static/terminal.js
#
# Place each file at the path shown in its delimiter below.
# Requires Phase 1 files to already be in place.
################################################################################

################################################################################
# FILE: routes/auth.py
################################################################################

# routes/auth.py
# Handles: login, logout, register, character creation, level-up prompt.
# All write operations go through enqueue_and_process except auth itself
# (login/register are not game actions, no AP involved).

import math
import logging
from datetime import datetime

from flask import (Blueprint, render_template, request, session,
                   redirect, url_for, flash, g)
from werkzeug.security import generate_password_hash, check_password_hash

from database import (execute, execute_one, execute_write,
                      exclusive_transaction, get_player, get_all_settings)
from queue_handler import enqueue_and_process, register_handler
import config_defaults as cfg

bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET"])
def login():
    if session.get("player_id"):
        return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html")


@bp.route("/login", methods=["POST"])
def login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        return render_template("auth/login.html", error="Username and password required.")

    player = execute_one(
        "SELECT id, password_hash, is_banned FROM players WHERE username = ?",
        (username,)
    )

    if player is None or not check_password_hash(player["password_hash"], password):
        return render_template("auth/login.html", error="Invalid username or password.")

    if player["is_banned"]:
        return render_template("auth/login.html", error="This account has been banned.")

    # Update last_login_at
    with exclusive_transaction():
        execute_write(
            "UPDATE players SET last_login_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), player["id"])
        )

    session.clear()
    session["player_id"] = player["id"]
    return redirect(url_for("dashboard.index"))


# ─────────────────────────────────────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


# ─────────────────────────────────────────────────────────────────────────────
# REGISTER
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/register", methods=["GET"])
def register():
    if session.get("player_id"):
        return redirect(url_for("dashboard.index"))
    return render_template("auth/register.html")


@bp.route("/register", methods=["POST"])
def register_post():
    username   = request.form.get("username", "").strip()
    password   = request.form.get("password", "")
    email      = request.form.get("email", "").strip().lower()

    # Validation
    errors = []
    if not username:
        errors.append("Username is required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if not email or "@" not in email:
        errors.append("A valid email address is required.")

    if not errors:
        if execute_one("SELECT id FROM players WHERE username = ?", (username,)):
            errors.append("That username is already taken.")
        if execute_one("SELECT id FROM players WHERE email = ?", (email,)):
            errors.append("That email address is already registered.")

    if errors:
        return render_template("auth/register.html", errors=errors,
                               username=username, email=email)

    # Create account with placeholder stats — character creation completes them
    password_hash = generate_password_hash(password)
    with exclusive_transaction():
        # Players row needs class_id — set to 0 as sentinel until character creation
        # current_hp and current_ap set to 0; character creation sets real values
        player_id = execute_write(
            """INSERT INTO players
               (username, password_hash, email, character_name, sex, class_id,
                str_stat, end_stat, agi_stat, lck_stat, per_stat,
                level, xp, current_hp, current_ap, credits, last_login_at)
               VALUES (?, ?, ?, '', '', NULL, 1, 1, 1, 1, 1, 1, 0, 0, 0, ?, ?)""",
            (username, password_hash, email,
             cfg.STARTING_CREDITS, datetime.utcnow().isoformat())
        )
        # Create player_stats row
        execute_write(
            "INSERT INTO player_stats (player_id) VALUES (?)", (player_id,)
        )

    session.clear()
    session["player_id"] = player_id
    return redirect(url_for("auth.character_create"))


# ─────────────────────────────────────────────────────────────────────────────
# CHARACTER CREATION
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/character-create", methods=["GET"])
def character_create():
    classes = execute("SELECT * FROM classes WHERE is_active = 1 ORDER BY name")
    if not classes:
        return render_template("auth/character_create.html",
                               classes=[],
                               error="No classes available yet. Ask the admin to import content first.")
    settings = get_all_settings()
    stat_points = settings.get("STARTING_STAT_POINTS", cfg.STARTING_STAT_POINTS)
    return render_template("auth/character_create.html",
                           classes=classes,
                           stat_points=stat_points)


@bp.route("/character-create", methods=["POST"])
def character_create_post():
    player_id      = session["player_id"]
    character_name = request.form.get("character_name", "").strip()
    sex            = request.form.get("sex", "").strip()
    class_id       = request.form.get("class_id", type=int)

    # Stat allocations from form
    try:
        alloc = {
            "str": int(request.form.get("str_alloc", 0)),
            "end": int(request.form.get("end_alloc", 0)),
            "agi": int(request.form.get("agi_alloc", 0)),
            "lck": int(request.form.get("lck_alloc", 0)),
            "per": int(request.form.get("per_alloc", 0)),
        }
    except (ValueError, TypeError):
        alloc = {"str": 0, "end": 0, "agi": 0, "lck": 0, "per": 0}

    settings    = get_all_settings()
    stat_points = settings.get("STARTING_STAT_POINTS", cfg.STARTING_STAT_POINTS)
    classes     = execute("SELECT * FROM classes WHERE is_active = 1 ORDER BY name")

    # Validate
    errors = []
    if not character_name:
        errors.append("Character name is required.")
    if not sex:
        errors.append("Please select a sex.")
    if not class_id:
        errors.append("Please select a class.")

    selected_class = execute_one("SELECT * FROM classes WHERE id = ? AND is_active = 1", (class_id,))
    if not selected_class and not errors:
        errors.append("Invalid class selected.")

    total_alloc = sum(alloc.values())
    if total_alloc != stat_points:
        errors.append(f"You must allocate exactly {stat_points} stat points (you allocated {total_alloc}).")
    if any(v < 0 for v in alloc.values()):
        errors.append("Stat allocations cannot be negative.")

    if errors:
        return render_template("auth/character_create.html",
                               classes=classes, errors=errors,
                               stat_points=stat_points,
                               character_name=character_name, sex=sex,
                               class_id=class_id, alloc=alloc)

    # Apply class bonuses on top of base 1 per stat + player allocation
    final_stats = {
        "str": 1 + selected_class["str_bonus"] + alloc["str"],
        "end": 1 + selected_class["end_bonus"] + alloc["end"],
        "agi": 1 + selected_class["agi_bonus"] + alloc["agi"],
        "lck": 1 + selected_class["lck_bonus"] + alloc["lck"],
        "per": 1 + selected_class["per_bonus"] + alloc["per"],
    }

    # Derive starting HP and AP
    base_daily_ap = settings.get("BASE_DAILY_AP", cfg.BASE_DAILY_AP)
    starting_hp   = 10 + final_stats["end"] + 5   # level 1
    starting_ap   = base_daily_ap + math.floor(final_stats["end"] / 2)

    with exclusive_transaction():
        execute_write(
            """UPDATE players SET
               character_name = ?, sex = ?, class_id = ?,
               str_stat = ?, end_stat = ?, agi_stat = ?, lck_stat = ?, per_stat = ?,
               current_hp = ?, current_ap = ?
               WHERE id = ?""",
            (character_name, sex, class_id,
             final_stats["str"], final_stats["end"], final_stats["agi"],
             final_stats["lck"], final_stats["per"],
             starting_hp, starting_ap, player_id)
        )

    # Award starter gear (random level 1 weapon + armor)
    _award_starter_gear(player_id)

    return redirect(url_for("dashboard.index"))


def _award_starter_gear(player_id: int):
    """Select a random level-1 weapon and armor, add to inventory."""
    for item_type, table in [("WEAPON", "weapons"), ("ARMOR", "armor")]:
        item = execute_one(
            f"SELECT * FROM {table} WHERE level = 1 AND is_active = 1 ORDER BY RANDOM() LIMIT 1"
        )
        if item is None:
            # Fallback: any active item
            item = execute_one(
                f"SELECT * FROM {table} WHERE is_active = 1 ORDER BY level ASC, RANDOM() LIMIT 1"
            )
        if item is None:
            continue  # No items imported yet — admin will need to import content

        with exclusive_transaction():
            inv_id = execute_write(
                """INSERT INTO inventory_items
                   (player_id, item_type, item_id, current_durability, acquired_method)
                   VALUES (?, ?, ?, ?, 'STARTER')""",
                (player_id, item_type, item["id"], item["starting_durability"])
            )
            execute_write(
                """INSERT INTO item_history
                   (player_id, item_type, item_id, item_name, event_type)
                   VALUES (?, ?, ?, ?, 'RECEIVED_STARTER')""",
                (player_id, item_type, item["id"], item["name"])
            )


# ─────────────────────────────────────────────────────────────────────────────
# LEVEL UP
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/levelup", methods=["GET"])
def levelup():
    """Show stat point assignment page.
    Enforced by before_request — only reachable when pending_levelup = True."""
    player = g.player
    return render_template("auth/levelup.html", player=player)


@bp.route("/levelup", methods=["POST"])
def levelup_post():
    stat = request.form.get("stat", "").strip().upper()
    if stat not in ("STR", "END", "AGI", "LCK", "PER"):
        return render_template("auth/levelup.html", player=g.player,
                               error="Please choose a valid stat.")

    result = enqueue_and_process(
        session["player_id"], "assign_levelup", {"stat": stat}
    )
    return redirect(url_for("dashboard.index"))


@register_handler("assign_levelup")
def handle_assign_levelup(player_id: int, payload: dict) -> dict:
    """Assign one stat point, recalculate and fully restore HP, clear pending flag."""
    stat = payload["stat"].lower()  # str / end / agi / lck / per
    col  = f"{stat}_stat"

    player = execute_one("SELECT * FROM players WHERE id = ?", (player_id,))
    if not player or not player["pending_levelup"]:
        raise ValueError("No pending level-up for this player.")

    new_stat_val = player[col] + 1
    new_level    = player["level"]

    # Recalculate max HP with new stat (end may have just increased)
    new_end = new_stat_val if stat == "end" else player["end_stat"]
    new_max_hp = 10 + new_end + (5 * new_level)

    with exclusive_transaction():
        execute_write(f"UPDATE players SET {col} = ? WHERE id = ?", (new_stat_val, player_id))
        # Always fully restore HP on level up
        execute_write(
            "UPDATE players SET current_hp = ?, pending_levelup = 0 WHERE id = ?",
            (new_max_hp, player_id)
        )
        execute_write(
            """INSERT INTO level_up_history (player_id, level_reached, stat_increased)
               VALUES (?, ?, ?)""",
            (player_id, new_level, stat.upper())
        )

    logger.info("Player %d assigned level-up stat point to %s (now %d)",
                player_id, stat.upper(), new_stat_val)
    return {"redirect": url_for("dashboard.index")}


################################################################################
# FILE: routes/dashboard.py
################################################################################

# routes/dashboard.py
# Serves the main dashboard shell — the only full-page render in normal gameplay.
# Loads the last N personal feed entries into the terminal on every load.

import logging
from flask import Blueprint, render_template, g
from database import execute, get_all_settings
import config_defaults as cfg

bp = Blueprint("dashboard", __name__)
logger = logging.getLogger(__name__)


@bp.route("/")
def index():
    player = g.player
    settings = get_all_settings()
    history_count = settings.get("TERMINAL_HISTORY_ENTRIES", cfg.TERMINAL_HISTORY_ENTRIES)

    # Load last N personal feed entries for terminal pre-population
    terminal_history = execute(
        """SELECT flavor_text, event_category, occurred_at, combat_session_id
           FROM daily_feed
           WHERE player_id = ? OR feed_scope = 'GLOBAL'
           ORDER BY occurred_at DESC
           LIMIT ?""",
        (player["id"], history_count)
    )
    terminal_history = list(reversed(terminal_history))  # oldest first

    # Determine enabled/disabled state of each AP action button
    button_states = _get_button_states(player, settings)

    return render_template(
        "dashboard.html",
        terminal_history=terminal_history,
        button_states=button_states,
        blackout=g.get("blackout", False),
    )


def _get_button_states(player: dict, settings: dict) -> dict:
    """Return enabled/disabled state and reason for each left-column action button."""
    in_combat  = player["in_combat"]
    current_ap = player["current_ap"]
    credits    = player["credits"]
    current_hp = player["current_hp"]
    max_hp     = player["max_hp"]
    blackout   = g.get("blackout", False)

    ap_boss      = settings.get("AP_COST_BOSS",       cfg.AP_COST_BOSS)
    ap_pvp       = settings.get("AP_COST_PVP",        cfg.AP_COST_PVP)
    ap_tavern    = settings.get("AP_COST_TAVERN",      cfg.AP_COST_TAVERN)
    ap_blacksmith= settings.get("AP_COST_BLACKSMITH",  cfg.AP_COST_BLACKSMITH)
    ap_shop      = settings.get("AP_COST_SHOP",        cfg.AP_COST_SHOP)
    tavern_cost  = settings.get("TAVERN_HEAL_COST",    cfg.TAVERN_HEAL_COST)

    def check(ap_cost, extra_checks=None):
        if in_combat:
            return False, "In combat"
        if blackout and extra_checks != "no_blackout":
            return False, "Approaching midnight reset"
        if current_ap < ap_cost:
            return False, f"Need {ap_cost} AP"
        if extra_checks:
            return extra_checks
        return True, None

    boss_ok, boss_reason = check(ap_boss)
    pvp_ok, pvp_reason   = check(ap_pvp)

    # Tavern: no blackout restriction; blocked at full HP or insufficient credits
    if in_combat:
        tavern_ok, tavern_reason = False, "In combat"
    elif current_ap < ap_tavern:
        tavern_ok, tavern_reason = False, f"Need {ap_tavern} AP"
    elif credits < tavern_cost:
        tavern_ok, tavern_reason = False, f"Need {tavern_cost} credits"
    elif current_hp >= max_hp:
        tavern_ok, tavern_reason = False, "Already at full health"
    else:
        tavern_ok, tavern_reason = True, None

    # Blacksmith: no blackout restriction; blocked at 0 credits
    if in_combat:
        bs_ok, bs_reason = False, "In combat"
    elif current_ap < ap_blacksmith:
        bs_ok, bs_reason = False, f"Need {ap_blacksmith} AP"
    elif credits == 0:
        bs_ok, bs_reason = False, "No credits"
    else:
        bs_ok, bs_reason = True, None

    # Shop: no blackout restriction
    if in_combat:
        shop_ok, shop_reason = False, "In combat"
    elif current_ap < ap_shop:
        shop_ok, shop_reason = False, f"Need {ap_shop} AP"
    else:
        shop_ok, shop_reason = True, None

    return {
        "boss":       {"enabled": boss_ok,   "reason": boss_reason,   "ap_cost": ap_boss},
        "pvp":        {"enabled": pvp_ok,    "reason": pvp_reason,    "ap_cost": ap_pvp},
        "tavern":     {"enabled": tavern_ok, "reason": tavern_reason, "ap_cost": ap_tavern},
        "blacksmith": {"enabled": bs_ok,     "reason": bs_reason,     "ap_cost": ap_blacksmith},
        "shop":       {"enabled": shop_ok,   "reason": shop_reason,   "ap_cost": ap_shop},
    }


################################################################################
# FILE: routes/feeds.py
################################################################################

# routes/feeds.py
# Lightweight JSON polling endpoints for the live terminal feed.
# Called every 5 seconds by terminal.js.
# These are the only two JSON-returning routes in the main app.

from flask import Blueprint, jsonify, request, session
from database import execute

bp = Blueprint("feeds", __name__)


@bp.route("/feed/personal/latest")
def personal_latest():
    """Return new personal feed entries since a given timestamp.
    Query param: since=<ISO datetime string>"""
    player_id = session.get("player_id")
    since = request.args.get("since", "1970-01-01T00:00:00")

    rows = execute(
        """SELECT flavor_text, event_category, occurred_at, combat_session_id
           FROM daily_feed
           WHERE player_id = ? AND occurred_at > ?
           ORDER BY occurred_at ASC""",
        (player_id, since)
    )
    return jsonify(rows)


@bp.route("/feed/global/latest")
def global_latest():
    """Return new global feed entries since a given timestamp.
    Query param: since=<ISO datetime string>"""
    since = request.args.get("since", "1970-01-01T00:00:00")

    rows = execute(
        """SELECT flavor_text, event_category, occurred_at
           FROM daily_feed
           WHERE feed_scope = 'GLOBAL' AND occurred_at > ?
           ORDER BY occurred_at ASC""",
        (since,)
    )
    return jsonify(rows)


################################################################################
# FILE: templates/base.html
################################################################################

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Movie Multiverse{% endblock %}</title>
    <script>
        try {
            document.documentElement.dataset.theme = localStorage.getItem('movie-multiverse-theme') || 'dark';
        } catch (error) {
            document.documentElement.dataset.theme = 'dark';
        }
    </script>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body class="{{ 'authenticated' if player else 'auth-page' }} {% block body_class %}{% endblock %}">

<button id="theme-toggle" type="button" aria-label="Switch color theme" aria-pressed="false">
    LIGHT MODE
</button>

{% if player %}
<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- LEFT COLUMN — status block + action buttons + nav             -->
<!-- ═══════════════════════════════════════════════════════════════ -->
<div id="left-col">

    <div id="status-block">
        <div class="status-name">{{ player.character_name }}</div>
        <div class="status-line">
            <span class="label">LVL</span>
            <span id="status-level">{{ player.level }}</span>
        </div>
        <div class="status-line">
            <span class="label">HP</span>
            <span id="status-hp">{{ player.current_hp }}</span>/<span id="status-maxhp">{{ player.max_hp }}</span>
        </div>
        <div class="status-line">
            <span class="label">AP</span>
            <span id="status-ap">{{ player.current_ap }}</span>/<span id="status-maxap">{{ player.max_ap }}</span>
        </div>
        <div class="status-line">
            <span class="label">CR</span>
            <span id="status-credits">{{ player.credits }}</span>
        </div>
        {% if player.is_overencumbered %}
        <div class="status-warning">⚠ OVER ENCUMBERED</div>
        {% endif %}
        {% if player.is_cursed %}
        <div class="status-warning">☠ CURSED</div>
        {% endif %}
        {% if player.in_combat %}
        <div class="status-combat">⚔ IN COMBAT</div>
        {% endif %}
    </div>

    <div id="action-buttons">
        {% if button_states is defined %}
            {% set action_endpoints = {
                'boss': 'actions.action_boss',
                'pvp': 'actions.action_pvp',
                'tavern': 'actions.action_tavern',
                'blacksmith': 'blacksmith.index',
                'shop': 'shop.index'
            } %}
            {% for action, state in button_states.items() %}
                {% if state.enabled %}
                    {% if action in ('blacksmith', 'shop') %}
                    <a class="action-btn action-link" href="{{ url_for(action_endpoints[action]) }}">
                        {{ action|upper }} <span class="ap-cost">({{ state.ap_cost }} AP)</span>
                    </a>
                    {% else %}
                    <form class="terminal-action" action="{{ url_for(action_endpoints[action]) }}" method="POST">
                    <button type="submit" class="action-btn">
                        {{ action|upper }} <span class="ap-cost">({{ state.ap_cost }} AP)</span>
                    </button>
                    </form>
                    {% endif %}
                {% else %}
                <button class="action-btn disabled" title="{{ state.reason }}" disabled>
                    {{ action|upper }} <span class="ap-cost">({{ state.ap_cost }} AP)</span>
                    <span class="btn-reason">{{ state.reason }}</span>
                </button>
                {% endif %}
            {% endfor %}
        {% endif %}
    </div>

    <nav id="left-nav">
        <a href="{{ url_for('character.index') }}">Character</a>
        <a href="{{ url_for('scoreboards.index') }}">Scoreboards</a>
        <form action="{{ url_for('auth.logout') }}" method="POST" style="margin:0">
            <button type="submit" class="nav-link-btn">Logout</button>
        </form>
    </nav>

</div><!-- /left-col -->
{% endif %}

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- MAIN CONTENT AREA                                             -->
<!-- ═══════════════════════════════════════════════════════════════ -->
<div id="main">
    {% block content %}{% endblock %}
</div>

{% if player %}
<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- BOTTOM TICKER — global feed                                   -->
<!-- ═══════════════════════════════════════════════════════════════ -->
<div id="ticker-wrap">
    <div id="ticker">
        <span id="ticker-content">Loading global feed...</span>
    </div>
</div>
{% endif %}

{% block scripts %}{% endblock %}
<script src="{{ url_for('static', filename='terminal.js') }}"></script>

</body>
</html>


################################################################################
# FILE: templates/dashboard.html
################################################################################

{% extends "base.html" %}

{% block title %}Dashboard{% endblock %}

{% block content %}
<div id="terminal" role="log" aria-live="polite">
    {# Pre-populate with last N personal feed entries on every load #}
    {% for entry in terminal_history %}
        <div class="term-line term-{{ entry.event_category|lower }}">
            <span class="term-ts">[{{ entry.occurred_at[11:16] }}]</span>
            {{ entry.flavor_text }}
        </div>
    {% endfor %}

    {% if blackout %}
    <div class="term-line term-system">
        ⚠ Midnight reset approaching — combat unavailable for a few minutes.
    </div>
    {% endif %}
</div>
{% endblock %}

{% block scripts %}
<script>
    // Inject the current timestamp so feed polling knows where to start
    const initialTimestamp = "{{ now_iso }}";
    const personalFeedUrl  = "{{ url_for('feeds.personal_latest') }}";
    const globalFeedUrl    = "{{ url_for('feeds.global_latest') }}";
</script>
{% endblock %}


################################################################################
# FILE: templates/auth/login.html + register.html + character_create.html + levelup.html
################################################################################

<!-- ============================================================ -->
<!-- FILE: templates/auth/login.html                            -->
<!-- ============================================================ -->
{% extends "base.html" %}
{% block title %}Login | Movie Multiverse{% endblock %}
{% block body_class %}poster-page poster-login{% endblock %}
{% block content %}
<div class="poster-stage poster-stage-login">
<img class="poster-art" src="{{ url_for('static', filename='images/movie-multiverse-login-boss-fight-v2.png') }}"
     alt="Movie Multiverse: Boss Fight movie poster">
<div id="auth-box" class="poster-auth-card">
    <h1 class="sr-only">Movie Multiverse: Boss Fight!</h1>
    {% if error %}
    <div class="term-error">{{ error }}</div>
    {% endif %}

    <form method="POST" action="{{ url_for('auth.login_post') }}">
        <div class="form-row">
            <label>USERNAME:</label>
            <input type="text" name="username" autocomplete="username" autofocus required>
        </div>
        <div class="form-row">
            <label>PASSWORD:</label>
            <input type="password" name="password" autocomplete="current-password" required>
        </div>
        <button type="submit" class="auth-btn">ENTER</button>
    </form>

    <p class="auth-link">New player? <a href="{{ url_for('auth.register') }}">Register here</a></p>
</div>
</div>
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/auth/register.html                         -->
<!-- ============================================================ -->
{% extends "base.html" %}
{% block title %}Create Account | Movie Multiverse{% endblock %}
{% block body_class %}poster-page poster-register{% endblock %}
{% block content %}
<div class="poster-stage poster-stage-register">
<img class="poster-art" src="{{ url_for('static', filename='images/movie-multiverse-signup-concept.png') }}"
     alt="Movie Multiverse cinema lobby poster">
<div id="auth-box" class="poster-auth-card">
    <h2 class="auth-heading">Create Account</h2>

    {% if errors %}
    <div class="term-errors">
        {% for e in errors %}<div class="term-error">{{ e }}</div>{% endfor %}
    </div>
    {% endif %}

    <form method="POST" action="{{ url_for('auth.register_post') }}">
        <div class="form-row">
            <label>USERNAME:</label>
            <input type="text" name="username" value="{{ username or '' }}"
                   autocomplete="username" autofocus required>
        </div>
        <div class="form-row">
            <label>EMAIL:</label>
            <input type="email" name="email" value="{{ email or '' }}"
                   autocomplete="email" required>
        </div>
        <div class="form-row">
            <label>PASSWORD:</label>
            <input type="password" name="password"
                   autocomplete="new-password" minlength="8" required>
            <span class="field-hint">Minimum 8 characters</span>
        </div>
        <button type="submit" class="auth-btn">CREATE ACCOUNT</button>
    </form>

    <p class="auth-link">Already registered? <a href="{{ url_for('auth.login') }}">Login here</a></p>
</div>
</div>
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/auth/character_create.html                 -->
<!-- ============================================================ -->
{% extends "base.html" %}
{% block title %}Create Character{% endblock %}
{% block content %}
<div id="auth-box" id="char-create">
    <h2 class="auth-heading">Character Creation</h2>
    <p class="auth-subtitle">This is permanent. Choose carefully.</p>

    {% if errors %}
    <div class="term-errors">
        {% for e in errors %}<div class="term-error">{{ e }}</div>{% endfor %}
    </div>
    {% endif %}

    {% if not classes %}
    <div class="term-error">{{ error }}</div>
    {% else %}

    <form method="POST" action="{{ url_for('auth.character_create_post') }}">

        <div class="form-section">
            <div class="form-row">
                <label>CHARACTER NAME:</label>
                <input type="text" name="character_name"
                       value="{{ character_name or '' }}" required autofocus>
                <span class="field-hint">Permanent — cannot be changed</span>
            </div>
            <div class="form-row">
                <label>SEX:</label>
                <select name="sex" required>
                    <option value="">-- Select --</option>
                    <option value="Male"   {% if sex == 'Male'   %}selected{% endif %}>Male</option>
                    <option value="Female" {% if sex == 'Female' %}selected{% endif %}>Female</option>
                    <option value="Other"  {% if sex == 'Other'  %}selected{% endif %}>Other</option>
                </select>
            </div>
        </div>

        <div class="form-section">
            <h3>Choose Class <span class="field-hint">(Permanent)</span></h3>
            <div id="class-list">
                {% for cls in classes %}
                <label class="class-option {% if class_id == cls.id %}selected{% endif %}">
                    <input type="radio" name="class_id" value="{{ cls.id }}"
                           {% if class_id == cls.id %}checked{% endif %} required>
                    <span class="class-name">{{ cls.name }}</span>
                    <span class="class-bonuses">
                        {% if cls.str_bonus %}+{{ cls.str_bonus }} STR {% endif %}
                        {% if cls.end_bonus %}+{{ cls.end_bonus }} END {% endif %}
                        {% if cls.agi_bonus %}+{{ cls.agi_bonus }} AGI {% endif %}
                        {% if cls.lck_bonus %}+{{ cls.lck_bonus }} LCK {% endif %}
                        {% if cls.per_bonus %}+{{ cls.per_bonus }} PER {% endif %}
                    </span>
                    {% if cls.description %}
                    <span class="class-desc">{{ cls.description }}</span>
                    {% endif %}
                </label>
                {% endfor %}
            </div>
        </div>

        <div class="form-section">
            <h3>Distribute {{ stat_points }} Stat Points</h3>
            <p class="field-hint">Base stats start at 1 each (plus class bonus). No per-stat cap.</p>
            <div id="stat-alloc">
                {% for stat, label in [('str','STR — Melee damage, inventory size'),
                                       ('end','END — HP pool, AP bonus, HP regen'),
                                       ('agi','AGI — Ranged damage, AC, dodge, initiative'),
                                       ('lck','LCK — Crits, dodge, shop odds, repair'),
                                       ('per','PER — Observe, shop discount, minion detection')] %}
                <div class="stat-row">
                    <label>{{ label }}</label>
                    <input type="number" name="{{ stat }}_alloc"
                           value="{{ (alloc or {}).get(stat, 0) }}"
                           min="0" max="{{ stat_points }}" required>
                </div>
                {% endfor %}
            </div>
            <div id="points-remaining">
                Points remaining: <span id="pts-left">{{ stat_points }}</span>
            </div>
        </div>

        <button type="submit" class="auth-btn">BEGIN</button>
    </form>
    {% endif %}
</div>

{% block scripts %}
<script>
// Live stat point counter
const total = {{ stat_points }};
const inputs = document.querySelectorAll('#stat-alloc input[type=number]');
const counter = document.getElementById('pts-left');

function updateCounter() {
    let used = 0;
    inputs.forEach(i => used += parseInt(i.value) || 0);
    const remaining = total - used;
    counter.textContent = remaining;
    counter.style.color = remaining === 0 ? 'var(--green)' :
                          remaining < 0  ? 'var(--red)'   : 'var(--amber)';
}
inputs.forEach(i => i.addEventListener('input', updateCounter));
updateCounter();
</script>
{% endblock %}
{% endblock %}


<!-- ============================================================ -->
<!-- FILE: templates/auth/levelup.html                          -->
<!-- ============================================================ -->
{% extends "base.html" %}
{% block title %}Level Up!{% endblock %}
{% block content %}
<div id="auth-box">
    <h2 class="auth-heading term-amber">⬆ LEVEL UP!</h2>
    <p>You have reached <strong>Level {{ player.level }}</strong>.</p>
    <p>Choose one stat to permanently increase by 1:</p>

    <form method="POST" action="{{ url_for('auth.levelup_post') }}">
        <div id="levelup-stats">
            {% for stat, label, detail in [
                ('STR', 'STR — Strength',    'Melee attack & damage / Inventory size'),
                ('END', 'END — Endurance',   'Max HP / Bonus AP / Passive HP regen'),
                ('AGI', 'AGI — Agility',     'Ranged attack & damage / AC / Dodge / Initiative'),
                ('LCK', 'LCK — Luck',        'Crit range / Dodge / Steal / Events / Repair'),
                ('PER', 'PER — Perception',  'Observe / Shop discount / Minion detection')
            ] %}
            <label class="stat-choice">
                <input type="radio" name="stat" value="{{ stat }}" required>
                <span class="stat-name">{{ label }}</span>
                <span class="stat-current">Currently: {{ player[stat.lower() + '_stat'] }} → {{ player[stat.lower() + '_stat'] + 1 }}</span>
                <span class="stat-detail">{{ detail }}</span>
            </label>
            {% endfor %}
        </div>

        {% if error %}
        <div class="term-error">{{ error }}</div>
        {% endif %}

        <button type="submit" class="auth-btn">CONFIRM</button>
    </form>
</div>
{% endblock %}


################################################################################
# FILE: static/style.css
################################################################################

/* style.css
   Dark terminal theme for the BBS-inspired dueling game.
   Monospace throughout, color-coded terminal output. */

/* ── CSS Variables ─────────────────────────────────────────── */
:root {
    --bg:         #0a0a0a;
    --bg-panel:   #111111;
    --bg-input:   #1a1a1a;
    --border:     #2a2a2a;
    --green:      #00cc66;
    --red:        #cc2222;
    --amber:      #ffaa00;
    --blue:       #4499ff;
    --grey:       #666666;
    --white:      #dddddd;
    --dim:        #444444;
    --font:       'Courier New', Courier, monospace;
    --left-width: 220px;
    --ticker-h:   32px;
}

:root[data-theme="light"] {
    --bg:       #f4f0e7;
    --bg-panel: #ffffff;
    --bg-input: #faf7f0;
    --border:   #c9bea9;
    --green:    #176b42;
    --red:      #a12b2b;
    --amber:    #8a5400;
    --blue:     #185f9d;
    --grey:     #655f55;
    --white:    #201d18;
    --dim:      #8a8174;
    color-scheme: light;
}

/* ── Reset & Base ──────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
    height: 100%;
    background: var(--bg);
    color: var(--white);
    font-family: var(--font);
    font-size: 14px;
    overflow: hidden;
}

a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }

#theme-toggle {
    position: fixed;
    top: 12px;
    right: 14px;
    z-index: 1000;
    min-width: 112px;
    padding: 7px 10px;
    border: 1px solid var(--amber);
    background: var(--bg-panel);
    color: var(--amber);
    font: bold 11px/1 var(--font);
    letter-spacing: 0.08em;
    cursor: pointer;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.18);
}

#theme-toggle:hover,
#theme-toggle:focus-visible {
    background: var(--amber);
    color: var(--bg);
    outline: none;
}

:root[data-theme="light"] .action-btn:hover:not(:disabled),
:root[data-theme="light"] .auth-btn { background: #e5f2e9; }
:root[data-theme="light"] .action-btn.disabled,
:root[data-theme="light"] .action-btn:disabled { border-color: var(--border); }
:root[data-theme="light"] #auth-box {
    border-color: #9b7a3f;
    box-shadow: 0 8px 30px rgba(54, 43, 25, 0.12);
}
:root[data-theme="light"] .auth-title {
    color: #176b42;
    text-shadow: none;
}
:root[data-theme="light"] .auth-btn:hover { background: #d5e9dc; }
:root[data-theme="light"] tr:nth-child(even) td { background: #eee8dc; }
:root[data-theme="light"] .effect-good { background: #e5f2e9; }
:root[data-theme="light"] .effect-bad { background: #f7e6e3; }

/* ── Layout ────────────────────────────────────────────────── */
#left-col {
    position: fixed;
    top: 0; left: 0;
    width: var(--left-width);
    height: calc(100vh - var(--ticker-h));
    background: var(--bg-panel);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 12px 10px;
    overflow-y: auto;
    z-index: 10;
}

#main {
    margin-left: var(--left-width);
    height: calc(100vh - var(--ticker-h));
    overflow-y: auto;
    overflow-x: hidden;
    scrollbar-gutter: stable;
    display: flex;
    flex-direction: column;
}

body.auth-page #main {
    margin-left: 0;
    height: 100vh;
}

.sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
}

body.poster-page #main {
    min-height: 100vh;
    height: auto;
    background-color: #05070c;
    align-items: center;
    justify-content: flex-start;
}

.poster-stage {
    position: relative;
    flex: 0 0 auto;
    width: min(100vw, 150vh);
    aspect-ratio: 3 / 2;
    margin: 0 auto;
    background: #05070c;
}

.poster-art {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: contain;
}

body.poster-page #auth-box.poster-auth-card {
    position: absolute;
    margin: 0;
    border-color: rgba(190, 142, 54, 0.72);
    background: rgba(5, 8, 13, 0.92);
    box-shadow: 0 12px 36px rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(3px);
}

body.poster-login #auth-box.poster-auth-card {
    left: 25.5%;
    top: 62.5%;
    width: 49%;
    max-width: none;
    padding: clamp(12px, 1.5vw, 24px) clamp(18px, 2.5vw, 42px);
}

body.poster-register #auth-box.poster-auth-card {
    left: 36%;
    top: 53.5%;
    width: 28%;
    max-width: none;
    padding: clamp(10px, 1.2vw, 20px) clamp(14px, 2vw, 32px);
}

:root[data-theme="light"] body.poster-page #auth-box.poster-auth-card {
    background: rgba(255, 252, 245, 0.96);
    border-color: #9b7a3f;
}

@media (max-width: 760px), (max-height: 620px) {
    body.poster-page #main {
        min-height: 100vh;
        padding-bottom: 28px;
        background: var(--bg);
    }

    .poster-stage {
        width: 100%;
        aspect-ratio: auto;
    }

    .poster-art {
        height: auto;
    }

    body.poster-login #auth-box.poster-auth-card,
    body.poster-register #auth-box.poster-auth-card {
        position: relative;
        inset: auto;
        width: min(100%, 520px);
        max-width: 520px;
        margin: 18px auto 0;
        padding: 24px;
    }
}

/* ── Status Block ──────────────────────────────────────────── */
#status-block {
    border: 1px solid var(--border);
    padding: 8px;
    margin-bottom: 14px;
}

.status-name {
    color: var(--amber);
    font-size: 13px;
    font-weight: bold;
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.status-line {
    display: flex;
    justify-content: space-between;
    margin: 2px 0;
    font-size: 13px;
}

.status-line .label { color: var(--grey); }

.status-warning { color: var(--amber); font-size: 12px; margin-top: 4px; }
.status-combat  { color: var(--red);   font-size: 12px; margin-top: 4px; }

/* ── Action Buttons ────────────────────────────────────────── */
#action-buttons {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 14px;
}

#action-buttons form { margin: 0; }

.action-btn {
    width: 100%;
    background: var(--bg-input);
    color: var(--green);
    border: 1px solid var(--border);
    padding: 7px 8px;
    text-align: left;
    cursor: pointer;
    font-family: var(--font);
    font-size: 13px;
    letter-spacing: 0.5px;
    transition: background 0.1s, border-color 0.1s;
}

.action-link {
    display: block;
    text-decoration: none;
}

.action-link:hover { text-decoration: none; }

.action-btn:hover:not(:disabled) {
    background: #1a2a1a;
    border-color: var(--green);
}

.action-btn.disabled, .action-btn:disabled {
    color: var(--dim);
    cursor: not-allowed;
    border-color: #1a1a1a;
}

.ap-cost   { font-size: 11px; color: var(--grey); float: right; }
.btn-reason{ display: block; font-size: 10px; color: var(--dim); margin-top: 2px; }

/* ── Left Nav ──────────────────────────────────────────────── */
#left-nav {
    margin-top: auto;
    display: flex;
    flex-direction: column;
    gap: 4px;
    border-top: 1px solid var(--border);
    padding-top: 10px;
}

#left-nav a, .nav-link-btn {
    color: var(--grey);
    font-size: 12px;
    font-family: var(--font);
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
    padding: 0;
}
#left-nav a:hover, .nav-link-btn:hover { color: var(--white); }

/* ── Terminal Area ─────────────────────────────────────────── */
#terminal {
    flex: 1;
    overflow-y: auto;
    padding: 12px 16px;
    scroll-behavior: smooth;
}

/* Terminal color coding */
.term-line         { margin: 2px 0; line-height: 1.5; word-wrap: break-word; }
.term-combat       { color: var(--white); }
.term-item         { color: var(--blue); }
.term-level_up     { color: var(--amber); font-weight: bold; }
.term-random_event { color: var(--green); }
.term-system       { color: var(--amber); }
.term-error        { color: var(--red); }
.term-good         { color: var(--green); }
.term-bad          { color: var(--red); }
.term-opponent     { color: var(--grey); }

.term-ts { color: var(--dim); font-size: 12px; margin-right: 6px; }

/* Terminal output panel on full pages (shop, blacksmith, etc.) */
#terminal-output {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    padding: 8px 12px;
    min-height: 40px;
    font-size: 13px;
    margin-bottom: 16px;
}

/* ── Bottom Ticker ─────────────────────────────────────────── */
#ticker-wrap {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    height: var(--ticker-h);
    background: var(--bg-panel);
    border-top: 1px solid var(--border);
    overflow: hidden;
    z-index: 20;
    display: flex;
    align-items: center;
}

#ticker {
    white-space: nowrap;
    color: var(--dim);
    font-size: 12px;
    padding-left: 100%;
    animation: ticker-scroll 60s linear infinite;
}

#ticker:hover { animation-play-state: paused; }

@keyframes ticker-scroll {
    0%   { transform: translateX(0); }
    100% { transform: translateX(-100%); }
}

/* ── Auth Pages ────────────────────────────────────────────── */
#auth-box {
    max-width: 520px;
    margin: 60px auto;
    padding: 32px;
    background: var(--bg-panel);
    border: 1px solid #1d6b42;
    box-shadow: 0 0 24px rgba(0, 204, 102, 0.08), inset 0 0 24px rgba(0, 204, 102, 0.025);
}

.auth-banner {
    overflow: hidden;
    margin-bottom: 24px;
    text-align: center;
}

.auth-banner-rule {
    color: var(--dim);
    font-size: 12px;
    line-height: 1;
    white-space: nowrap;
}

.auth-title {
    margin: 12px 0 8px;
    color: #40ee86;
    font-size: clamp(32px, 10vw, 56px);
    font-weight: 700;
    line-height: 1;
    letter-spacing: 0.14em;
    text-indent: 0.14em;
    text-shadow: 0 0 9px rgba(0, 204, 102, 0.45);
}

.auth-subtitle  { color: var(--amber); margin-bottom: 12px; font-size: 12px; letter-spacing: 0.08em; }
.auth-heading   { color: var(--amber); margin-bottom: 16px; font-size: 16px; }
.auth-link      { color: var(--grey); font-size: 12px; margin-top: 16px; }

.form-row {
    display: flex;
    flex-direction: column;
    margin-bottom: 14px;
}

.form-row label { color: var(--grey); font-size: 12px; margin-bottom: 4px; }

.form-row input,
.form-row select {
    background: var(--bg-input);
    border: 1px solid var(--border);
    color: var(--white);
    padding: 7px 10px;
    font-family: var(--font);
    font-size: 13px;
    outline: none;
}

.form-row input:focus,
.form-row select:focus { border-color: var(--green); }

.field-hint { color: var(--dim); font-size: 11px; margin-top: 3px; }

.auth-btn {
    background: #0a2a0a;
    color: var(--green);
    border: 1px solid var(--green);
    padding: 9px 24px;
    font-family: var(--font);
    font-size: 14px;
    letter-spacing: 1px;
    cursor: pointer;
    margin-top: 8px;
    width: 100%;
}
.auth-btn:hover { background: #0f3a0f; }

.term-errors { margin-bottom: 12px; }
.term-error  { color: var(--red); font-size: 13px; margin: 3px 0; }

/* ── Character Creation ────────────────────────────────────── */
.form-section { margin-bottom: 24px; }
.form-section h3 { color: var(--amber); margin-bottom: 10px; font-size: 14px; }

.class-option {
    display: block;
    background: var(--bg-input);
    border: 1px solid var(--border);
    padding: 8px 10px;
    margin-bottom: 6px;
    cursor: pointer;
}
.class-option:hover { border-color: var(--green); }
.class-option.selected {
    border-color: var(--green);
    background: #10281b;
    box-shadow: inset 4px 0 0 var(--green), 0 0 10px rgba(0, 204, 102, 0.18);
}
.class-option input[type=radio] {
    position: absolute;
    opacity: 0;
    pointer-events: none;
}
.class-option:focus-within { outline: 2px solid var(--blue); outline-offset: 2px; }
.class-option.selected .class-name::after {
    content: " [SELECTED]";
    color: var(--green);
    font-size: 11px;
    letter-spacing: 0.06em;
}
:root[data-theme="light"] .class-option.selected { background: #e5f2e9; }
.class-name    { color: var(--amber); font-size: 13px; display: block; }
.class-bonuses { color: var(--green); font-size: 12px; display: block; }
.class-desc    { color: var(--grey);  font-size: 11px; display: block; margin-top: 3px; }

.stat-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
}
.stat-row label { color: var(--grey); font-size: 12px; flex: 1; }
.stat-row input {
    width: 60px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    color: var(--white);
    padding: 4px 8px;
    font-family: var(--font);
    text-align: center;
}

#points-remaining {
    color: var(--amber);
    font-size: 13px;
    margin-top: 8px;
    text-align: right;
}

/* ── Level Up ──────────────────────────────────────────────── */
.stat-choice {
    display: block;
    background: var(--bg-input);
    border: 1px solid var(--border);
    padding: 8px 10px;
    margin-bottom: 6px;
    cursor: pointer;
}
.stat-choice:hover { border-color: var(--green); }
.stat-choice input[type=radio] { display: none; }
.stat-name    { color: var(--amber); display: block; font-size: 13px; }
.stat-current { color: var(--green); display: block; font-size: 12px; }
.stat-detail  { color: var(--grey);  display: block; font-size: 11px; margin-top: 2px; }

/* ── Fragments ─────────────────────────────────────────────── */
.fragment { padding: 6px 0; border-top: 1px solid var(--border); margin-top: 8px; }
.fragment-header { color: var(--amber); margin-bottom: 6px; }

/* ── Full Pages (shop, blacksmith, character, scoreboards) ─── */
#page-content {
    padding: 20px 24px;
    overflow-y: auto;
    height: 100%;
}

.page-title {
    color: var(--amber);
    font-size: 16px;
    margin-bottom: 16px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 8px;
}

.back-link {
    color: var(--grey);
    font-size: 12px;
    display: inline-block;
    margin-bottom: 16px;
}

table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    margin-bottom: 16px;
}
th {
    background: var(--bg-input);
    color: var(--amber);
    padding: 6px 10px;
    text-align: left;
    border: 1px solid var(--border);
}
td {
    padding: 5px 10px;
    border: 1px solid var(--border);
    color: var(--white);
    vertical-align: middle;
}
tr:nth-child(even) td { background: #0d0d0d; }

.btn-small {
    background: var(--bg-input);
    color: var(--green);
    border: 1px solid var(--border);
    padding: 3px 10px;
    font-family: var(--font);
    font-size: 12px;
    cursor: pointer;
}
.btn-small:hover { border-color: var(--green); }
.btn-small.danger { color: var(--red); }
.btn-small.danger:hover { border-color: var(--red); }

/* Durability bar */
.dur-bar {
    display: inline-block;
    height: 6px;
    background: var(--green);
    transition: width 0.2s;
}
.dur-bar.medium { background: var(--amber); }
.dur-bar.low    { background: var(--red); }

/* ── Scrollbar ─────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--dim); }


################################################################################
# FILE: static/terminal.js
################################################################################

// terminal.js
// Four responsibilities:
//   1. Terminal action form interception (POST → append fragment)
//   2. Feed polling every 5 seconds
//   3. Left column status block updates
//   4. Round-4 PvP extension countdown timer

'use strict';

// Persistent light/dark color theme.
document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;

    const updateToggle = () => {
        const isLight = document.documentElement.dataset.theme === 'light';
        toggle.textContent = isLight ? 'DARK MODE' : 'LIGHT MODE';
        toggle.setAttribute('aria-pressed', String(isLight));
    };

    updateToggle();
    toggle.addEventListener('click', () => {
        const nextTheme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
        document.documentElement.dataset.theme = nextTheme;
        try {
            localStorage.setItem('movie-multiverse-theme', nextTheme);
        } catch (error) {
            // The theme still changes for this page if storage is unavailable.
        }
        updateToggle();
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// 1. TERMINAL ACTION FORM INTERCEPTION
// All forms with class="terminal-action" are intercepted.
// Result HTML fragment is appended to #terminal instead of navigating away.
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    bindTerminalForms();
    bindClassSelection();
});

function bindClassSelection() {
    const options = document.querySelectorAll('.class-option');
    if (!options.length) return;

    const updateSelection = () => {
        options.forEach(option => {
            const radio = option.querySelector('input[type="radio"]');
            const selected = Boolean(radio && radio.checked);
            option.classList.toggle('selected', selected);
            option.setAttribute('aria-selected', String(selected));
        });
    };

    options.forEach(option => {
        const radio = option.querySelector('input[type="radio"]');
        if (radio) radio.addEventListener('change', updateSelection);
    });
    updateSelection();
}

function bindTerminalForms() {
    document.querySelectorAll('.terminal-action').forEach(form => {
        if (form.dataset.terminalBound === 'true') return;
        form.dataset.terminalBound = 'true';

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const actionUrl = form.getAttribute('action');
            if (!actionUrl) {
                appendToTerminal('<div class="term-line term-error">This action is unavailable because its destination is missing.</div>');
                return;
            }

            const response = await fetch(actionUrl, {
                method: 'POST',
                body: new FormData(form),
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const html = await response.text();
            if (!response.ok) {
                appendToTerminal(`<div class="term-line term-error">Action failed (${response.status}). Please try again or check the server log.</div>`);
                return;
            }
            appendToTerminal(html);
            // Rebind any new terminal-action forms inside the fragment
            bindTerminalForms();
        });
    });
}

function appendToTerminal(html) {
    const terminal = document.getElementById('terminal');
    if (!terminal) return;
    const div = document.createElement('div');
    div.innerHTML = html;
    terminal.appendChild(div);
    terminal.scrollTop = terminal.scrollHeight;
    // Extract and apply any status updates embedded in the fragment
    updateStatusFromFragment(div);
}


// ─────────────────────────────────────────────────────────────────────────────
// 2. FEED POLLING
// Polls personal and global feed endpoints every 5 seconds.
// Appends new personal entries to #terminal; updates ticker with global entries.
// Timestamps injected by dashboard.html into initialTimestamp.
// ─────────────────────────────────────────────────────────────────────────────

let lastPersonalTs = (typeof initialTimestamp !== 'undefined') ? initialTimestamp : new Date(0).toISOString();
let lastGlobalTs   = lastPersonalTs;
const POLL_INTERVAL = 5000;

function pollFeeds() {
    // Personal feed → terminal
    if (typeof personalFeedUrl !== 'undefined') {
        fetch(`${personalFeedUrl}?since=${encodeURIComponent(lastPersonalTs)}`)
            .then(r => r.json())
            .then(entries => {
                entries.forEach(entry => {
                    appendFeedEntry(entry);
                    lastPersonalTs = entry.occurred_at;
                });
            })
            .catch(() => {});  // silent fail — server may be momentarily busy
    }

    // Global feed → ticker
    if (typeof globalFeedUrl !== 'undefined') {
        fetch(`${globalFeedUrl}?since=${encodeURIComponent(lastGlobalTs)}`)
            .then(r => r.json())
            .then(entries => {
                entries.forEach(entry => {
                    appendToTicker(entry.flavor_text);
                    lastGlobalTs = entry.occurred_at;
                });
            })
            .catch(() => {});
    }
}

function appendFeedEntry(entry) {
    const terminal = document.getElementById('terminal');
    if (!terminal) return;
    const div = document.createElement('div');
    const category = (entry.event_category || 'system').toLowerCase();
    div.className = `term-line term-${category}`;
    const ts = entry.occurred_at ? entry.occurred_at.substring(11, 16) : '';
    div.innerHTML = `<span class="term-ts">[${ts}]</span> ${entry.flavor_text}`;
    terminal.appendChild(div);
    terminal.scrollTop = terminal.scrollHeight;
}

function appendToTicker(text) {
    const ticker = document.getElementById('ticker-content');
    if (!ticker) return;
    if (ticker.textContent === 'Loading global feed...') {
        ticker.textContent = '';
    }
    ticker.textContent += '  ·  ' + text;
}

// Start polling if on dashboard
if (document.getElementById('terminal')) {
    setInterval(pollFeeds, POLL_INTERVAL);
}


// ─────────────────────────────────────────────────────────────────────────────
// 3. LEFT COLUMN STATUS UPDATES
// Terminal fragments include data-hp, data-ap, data-credits attributes
// on a wrapper element. Read and push to the status block after every action.
// ─────────────────────────────────────────────────────────────────────────────

function updateStatusFromFragment(container) {
    const el = container.querySelector('[data-hp]');
    if (!el) return;

    const hp    = el.dataset.hp;
    const maxHp = el.dataset.maxHp;
    const ap    = el.dataset.ap;
    const maxAp = el.dataset.maxAp;
    const cr    = el.dataset.credits;

    if (hp    !== undefined) setEl('status-hp',      hp);
    if (maxHp !== undefined) setEl('status-maxhp',   maxHp);
    if (ap    !== undefined) setEl('status-ap',       ap);
    if (maxAp !== undefined) setEl('status-maxap',    maxAp);
    if (cr    !== undefined) setEl('status-credits',  cr);
}

function setEl(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}


// ─────────────────────────────────────────────────────────────────────────────
// 4. ROUND-4 PVP EXTENSION COUNTDOWN TIMER
// Called by combat_extend.html fragment when it's injected into the terminal.
// Counts down COMBAT_EXTENSION_TIMEOUT seconds. On expiry, auto-POSTs to
// /combat/resolve so the score formula runs even if the player doesn't respond.
// ─────────────────────────────────────────────────────────────────────────────

let _extensionTimer = null;

function startExtensionTimer(seconds, resolveUrl) {
    // Clear any existing timer (safety)
    if (_extensionTimer) clearInterval(_extensionTimer);

    let remaining = seconds;
    const timerEl = document.getElementById('extend-timer');

    _extensionTimer = setInterval(() => {
        remaining--;
        if (timerEl) timerEl.textContent = remaining;

        if (remaining <= 0) {
            clearInterval(_extensionTimer);
            _extensionTimer = null;
            // Auto-resolve: POST to /combat/resolve
            fetch(resolveUrl, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => r.text())
            .then(html => appendToTerminal(html))
            .catch(() => {});
        }
    }, 1000);
}

// Expose so combat fragments can call it after injection
window.startExtensionTimer = startExtensionTimer;
