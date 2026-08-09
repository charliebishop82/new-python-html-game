"""Account registration, login, character creation, and level-up routes."""
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
    """Handle the login workflow."""
    if session.get("player_id"):
        return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html")


@bp.route("/login", methods=["POST"])
def login_post():
    """Handle the login post workflow."""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        return render_template("auth/login.html", error="Username and password required.")

    player = execute_one(
        """SELECT id, password_hash, is_banned, retired_at, last_login_at
           FROM players WHERE username = ?""",
        (username,)
    )

    if player is None or not check_password_hash(player["password_hash"], password):
        return render_template("auth/login.html", error="Invalid username or password.")

    if player.get("retired_at"):
        return render_template("auth/login.html", error="This character has been retired.")
    if player["is_banned"]:
        return render_template("auth/login.html", error="This account has been banned.")

    previous_login = player.get("last_login_at")
    first_login_today = not previous_login or previous_login[:10] != datetime.utcnow().date().isoformat()

    # Update last_login_at
    with exclusive_transaction():
        execute_write(
            "UPDATE players SET last_login_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), player["id"])
        )

    session.clear()
    session["player_id"] = player["id"]
    session["show_daily_tutorial"] = first_login_today
    return redirect(url_for("dashboard.index"))


# ─────────────────────────────────────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/logout", methods=["POST"])
def logout():
    """Handle the logout workflow."""
    session.clear()
    return redirect(url_for("auth.login"))


# ─────────────────────────────────────────────────────────────────────────────
# REGISTER
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/register", methods=["GET"])
def register():
    """Handle the register workflow."""
    if session.get("player_id"):
        return redirect(url_for("dashboard.index"))
    return render_template("auth/register.html")


@bp.route("/register", methods=["POST"])
def register_post():
    """Handle the register post workflow."""
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
    """Handle the character create workflow."""
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
    """Handle the character create post workflow."""
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
    # Show onboarding once on this first character-session dashboard. It is
    # transient rather than permanent feed history, so reloads do not repeat it.
    session["show_daily_tutorial"] = True

    return redirect(url_for("dashboard.index"))


def _award_starter_gear(player_id: int):
    """Give and immediately equip one level-1 weapon and armor."""
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
            equipped_column = ("equipped_weapon_id" if item_type == "WEAPON"
                               else "equipped_armor_id")
            execute_write(
                f"UPDATE players SET {equipped_column}=? WHERE id=?",
                (inv_id, player_id)
            )


# ─────────────────────────────────────────────────────────────────────────────
# LEVEL UP
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/levelup", methods=["GET"])
def levelup():
    """Show stat point assignment page.
    Enforced by before_request — only reachable when pending_levelup = True."""
    player = g.player
    perks = _eligible_perks(player) if player.get("pending_perk") else []
    return render_template("auth/levelup.html", player=player, perks=perks)


@bp.route("/levelup", methods=["POST"])
def levelup_post():
    """Handle the levelup post workflow."""
    stat = request.form.get("stat", "").strip().upper()
    if stat not in ("STR", "END", "AGI", "LCK", "PER"):
        return render_template("auth/levelup.html", player=g.player,
                               perks=_eligible_perks(g.player) if g.player.get("pending_perk") else [],
                               error="Please choose a valid stat.")

    perk_id = request.form.get("perk_id", type=int)
    if g.player.get("pending_perk") and not perk_id:
        return render_template("auth/levelup.html", player=g.player,
                               perks=_eligible_perks(g.player),
                               error="This level also grants a perk. Please choose one.")

    result = enqueue_and_process(
        session["player_id"], "assign_levelup", {"stat": stat, "perk_id": perk_id}
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

    perk = None
    if player.get("pending_perk"):
        perk_id = payload.get("perk_id")
        perk = execute_one(
            """SELECT p.* FROM perks p WHERE p.id=? AND p.is_active=1
               AND p.level <= ? AND NOT EXISTS(
                   SELECT 1 FROM player_perks pp WHERE pp.player_id=? AND pp.perk_id=p.id)""",
            (perk_id or -1, player["level"] + 2, player_id)
        )
        if not perk:
            raise ValueError("Choose an eligible perk you do not already own.")

    new_stat_val = player[col] + 1
    new_level    = player["level"]

    pending_before = max(1, int(player.get("pending_levelup", 1)))
    perk_pending_before = max(0, int(player.get("pending_perk", 0)))
    next_threshold = cfg.XP_CURVE.get(new_level + 1)
    has_another_level = next_threshold is not None and player["xp"] >= next_threshold
    target_level = new_level + 1 if has_another_level else new_level
    remaining_levelups = pending_before - 1 + (1 if has_another_level else 0)
    remaining_perks = perk_pending_before - (1 if perk else 0)
    if has_another_level and target_level % 3 == 0:
        remaining_perks += 1

    # Recalculate max HP with the assigned stat and any immediately queued level.
    new_end = new_stat_val if stat == "end" else player["end_stat"]
    new_max_hp = 10 + new_end + (5 * target_level)

    with exclusive_transaction():
        execute_write(f"UPDATE players SET {col} = ? WHERE id = ?", (new_stat_val, player_id))
        # Always fully restore HP on level up
        execute_write(
            """UPDATE players SET current_hp=?,pending_levelup=?,pending_perk=?,level=?
               WHERE id=?""",
            (new_max_hp, remaining_levelups,
             remaining_perks,
             target_level, player_id)
        )
        if perk:
            execute_write(
                "INSERT INTO player_perks(player_id,perk_id,level_chosen) VALUES(?,?,?)",
                (player_id, perk["id"], new_level)
            )
        execute_write(
            """INSERT INTO level_up_history (player_id, level_reached, stat_increased)
               VALUES (?, ?, ?)""",
            (player_id, new_level, stat.upper())
        )
        stat_names = {"str": "Strength", "end": "Endurance", "agi": "Agility",
                      "lck": "Luck", "per": "Perception"}
        execute_write(
            """INSERT INTO daily_feed
               (feed_scope, player_id, flavor_text, event_category)
               VALUES ('PERSONAL', ?, ?, 'LEVEL_UP')""",
            (player_id,
             f"{player['character_name']} reached Level {new_level} and increased "
             f"{stat_names[stat]} to {new_stat_val}.")
        )
        execute_write(
            """INSERT INTO daily_feed
               (feed_scope, player_id, flavor_text, event_category)
               VALUES ('GLOBAL', NULL, ?, 'LEVEL_UP')""",
            (f"{player['character_name']} reached Level {new_level}!",)
        )
        if perk:
            perk_text = f"{player['character_name']} selected the perk {perk['name']}."
            execute_write(
                """INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category)
                   VALUES('PERSONAL',?,?,'PERK')""", (player_id, perk_text)
            )

    logger.info("Player %d assigned level-up stat point to %s (now %d)",
                player_id, stat.upper(), new_stat_val)
    return {"stat": stat.upper(), "new_value": new_stat_val,
            "level": new_level, "perk": perk["name"] if perk else None,
            "another_level_pending": has_another_level}


def _eligible_perks(player: dict) -> list[dict]:
    """List unowned active perks at or below character level plus two."""
    return execute(
        """SELECT p.* FROM perks p WHERE p.is_active=1 AND p.level <= ?
           AND NOT EXISTS(SELECT 1 FROM player_perks pp
                          WHERE pp.player_id=? AND pp.perk_id=p.id)
           ORDER BY p.level,p.name""", (player["level"] + 2, player["id"])
    )


################################################################################


def get_tutorial_messages() -> list[tuple[str, str]]:
    """Return the transient tutorial shown on a player's first login each day."""
    return [
        ("SYSTEM",       "Welcome. The world is dangerous. Here is what you need to know."),
        ("SYSTEM",       "AP (Action Points) fuel everything. You earn a daily allotment at midnight plus trickle bonuses every 6 hours. Spend them wisely."),
        ("SYSTEM",       "BOSS — Challenge a movie villain. Defeat them for XP, credits, and gear. Watch for phase transitions as their HP drops."),
        ("SYSTEM",       "PVP — Fight another player. Win to steal credits and items. Lose and you drop to 1 HP. Choose your targets carefully."),
        ("SYSTEM",       "TAVERN — Spend credits to restore HP. No AP cost once inside."),
        ("SYSTEM",       "BLACKSMITH — Repair damaged gear. Durability matters — broken weapons deal less damage."),
        ("SYSTEM",       "SHOP — Buy and sell weapons, armor, and special items. Special items are unique. Only one copy exists in the world at a time."),
        ("SYSTEM",       "OBSERVE in combat to learn an enemy's resistances and weaknesses. That intel is stored permanently for future fights."),
        ("SYSTEM",       "Level up by earning XP. Each level grants one permanent stat point. Choose carefully — there is no going back."),
        ("SYSTEM",       "You have been given starter gear. Visit your Character Sheet to equip it before your first fight."),
        ("RANDOM_EVENT", "Good luck out there. You will need it."),
    ]
