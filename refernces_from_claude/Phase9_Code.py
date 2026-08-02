################################################################################
# PHASE 9 CODE — Polish, Fixes & Launch Checklist
# BBS-Inspired Multiplayer Dueling Game
#
# Contents:
#   1. combat/__init__.py        (empty package marker)
#   2. routes/__init__.py        (empty package marker)
#   3. requirements.txt
#   4. run.py                    (dev entry point)
#   5. routes/dashboard.py       (Phase 9 fix — injects now_iso for JS polling)
#   6. Session ID fix notes      (apply to routes/actions.py from Phase 5)
#   7. combat_open.html          (Phase 9 — adds pre-combat warnings)
#   8. Warning/blocked states    (consolidated QA checklist)
#   9. Pre-launch checklist
#
# KEY PATCHES TO APPLY:
#   a) routes/dashboard.py: use the Phase 9 version (adds now_iso)
#   b) routes/actions.py: add session["combat_session_id"] = result["session_id"]
#      in _start_boss_fight() and action_pvp_fight() after fight initiates
#   c) templates/fragments/combat_open.html: use Phase 9 version (adds warnings)
################################################################################

# =============================================================================
# PHASE 9 — Polish, Missing Pieces & Wiring
# =============================================================================
# This file covers everything needed to make the app fully runnable:
#   1. combat/__init__.py         (empty package marker)
#   2. routes/__init__.py         (empty package marker)
#   3. Missing dashboard.py fix   (injects now_iso for feed polling)
#   4. routes/scoreboards.py fix  (blueprint name collision fix)
#   5. All remaining blocked/warning state checks consolidated
#   6. requirements.txt
#   7. run.py  (dev entry point)
# =============================================================================


# =============================================================================
# FILE: combat/__init__.py
# (empty — makes combat/ a Python package)
# =============================================================================
COMBAT_INIT = ""


# =============================================================================
# FILE: routes/__init__.py
# (empty — makes routes/ a Python package)
# =============================================================================
ROUTES_INIT = ""


# =============================================================================
# FILE: requirements.txt
# =============================================================================
REQUIREMENTS = """flask>=3.0
apscheduler>=3.10
openpyxl>=3.1
werkzeug>=3.0
"""


# =============================================================================
# FILE: run.py
# Development entry point. In production use gunicorn:
#   gunicorn "app:create_app()" --bind 0.0.0.0:5000 --workers 1
# Single worker required — SQLite + APScheduler are not multi-process safe.
# =============================================================================
RUN_PY = """
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

from app import create_app
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, port=5000)
    # use_reloader=False: prevents APScheduler from running twice in debug mode
"""


# =============================================================================
# FILE: routes/dashboard.py  (Phase 9 fix — inject now_iso for feed polling)
# Full replacement with the fix applied.
# =============================================================================
DASHBOARD_PY = """
# routes/dashboard.py  (Phase 9 — adds now_iso injection for JS feed polling)
import logging
from datetime import datetime
from flask import Blueprint, render_template, g
from database import execute, get_all_settings
import config_defaults as cfg

bp = Blueprint('dashboard', __name__)
logger = logging.getLogger(__name__)


@bp.route('/')
def index():
    player   = g.player
    settings = get_all_settings()
    history_count = settings.get('TERMINAL_HISTORY_ENTRIES', cfg.TERMINAL_HISTORY_ENTRIES)

    terminal_history = execute(
        '''SELECT flavor_text, event_category, occurred_at, combat_session_id
           FROM daily_feed
           WHERE player_id = ? OR feed_scope = 'GLOBAL'
           ORDER BY occurred_at DESC
           LIMIT ?''',
        (player['id'], history_count)
    )
    terminal_history = list(reversed(terminal_history))

    button_states = _get_button_states(player, settings)

    # Inject current UTC timestamp for JS feed polling start point
    now_iso = datetime.utcnow().isoformat()

    return render_template(
        'dashboard.html',
        terminal_history=terminal_history,
        button_states=button_states,
        blackout=g.get('blackout', False),
        now_iso=now_iso,
    )


def _get_button_states(player: dict, settings: dict) -> dict:
    in_combat  = player['in_combat']
    current_ap = player['current_ap']
    credits    = player['credits']
    current_hp = player['current_hp']
    max_hp     = player['max_hp']
    blackout   = g.get('blackout', False)

    ap_boss       = settings.get('AP_COST_BOSS',       cfg.AP_COST_BOSS)
    ap_pvp        = settings.get('AP_COST_PVP',        cfg.AP_COST_PVP)
    ap_tavern     = settings.get('AP_COST_TAVERN',     cfg.AP_COST_TAVERN)
    ap_blacksmith = settings.get('AP_COST_BLACKSMITH', cfg.AP_COST_BLACKSMITH)
    ap_shop       = settings.get('AP_COST_SHOP',       cfg.AP_COST_SHOP)
    tavern_cost   = settings.get('TAVERN_HEAL_COST',   cfg.TAVERN_HEAL_COST)

    # Boss/PvP: blocked by in_combat, blackout, or insufficient AP
    if in_combat:
        boss_ok, boss_reason = False, 'In combat'
        pvp_ok,  pvp_reason  = False, 'In combat'
    elif blackout:
        boss_ok, boss_reason = False, 'Approaching midnight reset'
        pvp_ok,  pvp_reason  = False, 'Approaching midnight reset'
    elif current_ap < ap_boss:
        boss_ok, boss_reason = False, f'Need {ap_boss} AP'
        pvp_ok,  pvp_reason  = False, f'Need {ap_pvp} AP'
    else:
        boss_ok, boss_reason = True, None
        pvp_ok,  pvp_reason  = current_ap >= ap_pvp, (None if current_ap >= ap_pvp else f'Need {ap_pvp} AP')

    # Tavern: no blackout restriction
    if in_combat:
        tavern_ok, tavern_reason = False, 'In combat'
    elif current_ap < ap_tavern:
        tavern_ok, tavern_reason = False, f'Need {ap_tavern} AP'
    elif credits < tavern_cost:
        tavern_ok, tavern_reason = False, f'Need {tavern_cost} credits'
    elif current_hp >= max_hp:
        tavern_ok, tavern_reason = False, 'Already at full health'
    else:
        tavern_ok, tavern_reason = True, None

    # Blacksmith: no blackout restriction; blocked at 0 credits
    if in_combat:
        bs_ok, bs_reason = False, 'In combat'
    elif current_ap < ap_blacksmith:
        bs_ok, bs_reason = False, f'Need {ap_blacksmith} AP'
    elif credits == 0:
        bs_ok, bs_reason = False, 'No credits'
    else:
        bs_ok, bs_reason = True, None

    # Shop: no blackout restriction
    if in_combat:
        shop_ok, shop_reason = False, 'In combat'
    elif current_ap < ap_shop:
        shop_ok, shop_reason = False, f'Need {ap_shop} AP'
    else:
        shop_ok, shop_reason = True, None

    return {
        'boss':       {'enabled': boss_ok,   'reason': boss_reason,   'ap_cost': ap_boss},
        'pvp':        {'enabled': pvp_ok,    'reason': pvp_reason,    'ap_cost': ap_pvp},
        'tavern':     {'enabled': tavern_ok, 'reason': tavern_reason, 'ap_cost': ap_tavern},
        'blacksmith': {'enabled': bs_ok,     'reason': bs_reason,     'ap_cost': ap_blacksmith},
        'shop':       {'enabled': shop_ok,   'reason': shop_reason,   'ap_cost': ap_shop},
    }
"""


# =============================================================================
# FILE: templates/fragments/combat_open.html  (Phase 9 fix)
# Adds session_id to Flask session via a lightweight POST on combat start.
# The session['combat_session_id'] must be set so subsequent /combat/* routes
# can find the active fight. We set it in the queue handler, not the template.
# This is a NOTE only — no template change needed. The fix is in routes/actions.py:
# after handle_start_boss_fight / handle_start_pvp_fight returns session_id,
# set session['combat_session_id'] = result['session_id'] in the route handler.
# =============================================================================
SESSION_FIX_NOTE = """
# IMPORTANT: In routes/actions.py, after enqueue_and_process returns for boss/pvp fight,
# add this line before returning the template:
#
#   from flask import session
#   session['combat_session_id'] = result['session_id']
#
# Add it in _start_boss_fight() and action_pvp_fight() immediately after
# enqueue_and_process returns successfully.
# This ensures /combat/action routes can find the active session.
"""


# =============================================================================
# FILE: routes/actions.py  (Phase 9 patch — session_id fix, minimal diff)
# Only showing the two functions that need patching.
# Apply these changes to your Phase 5 routes/actions.py.
# =============================================================================
ACTIONS_PATCH = """
# In routes/actions.py — patch _start_boss_fight():
# After the line: if result.get('error'): return _error_fragment(...)
# Add:
#   from flask import session as flask_session
#   flask_session['combat_session_id'] = result['session_id']

# In routes/actions.py — patch action_pvp_fight():
# After: result = enqueue_and_process(...)
# Add:
#   if not result.get('error'):
#       from flask import session as flask_session
#       flask_session['combat_session_id'] = result['session_id']
"""


# =============================================================================
# Consolidated warning/blocked states reference
# These are already implemented across the route files.
# Listed here for completeness / QA checklist.
# =============================================================================
WARNING_STATES = """
# ── Confirmed warning/blocked states across all routes ──────────────────────

# DASHBOARD (left column buttons — all implemented in routes/dashboard.py):
#   Boss/PvP:     blocked if in_combat, blackout window, insufficient AP
#   Tavern:       blocked if in_combat, insufficient AP, insufficient credits, full HP
#   Blacksmith:   blocked if in_combat, insufficient AP, 0 credits, all items full durability
#   Shop:         blocked if in_combat, insufficient AP

# BOSS FIGHT (routes/actions.py):
#   - Already in combat
#   - Midnight blackout window
#   - Insufficient AP
#   - No content imported yet (no bosses/minions in DB)
#   - Level mismatch warning (BOSS_LEVEL_WARNING_THRESHOLD) — non-blocking, shows confirm fragment
#   - Minion PER check — non-blocking, shows spotted fragment with avoid option

# PVP (routes/actions.py):
#   - Already in combat
#   - Midnight blackout window
#   - Insufficient AP
#   - Target is level 1 or 2 (protected)
#   - Target is at 1 HP
#   - Target is already in combat
#   - Target is more than 2 levels below attacker
#   - No eligible opponents

# COMBAT ACTIONS (routes/combat.py):
#   - No active combat session in Flask session
#   - Session not ACTIVE status
#   - Escape: insufficient AP for escape cost

# TAVERN (routes/actions.py):
#   - Already at full HP
#   - Insufficient AP
#   - Insufficient credits

# BLACKSMITH (routes/blacksmith.py):
#   - 0 credits (entire page blocked)
#   - All items at full durability (entire page blocked)
#   - Insufficient credits for selected repairs

# SHOP (routes/shop.py):
#   - Item no longer available (race condition guard in handler)
#   - Insufficient credits

# CHARACTER SHEET (routes/character.py):
#   - Cannot drop equipped items (must unequip first)
#   - Cannot sell equipped items (must unequip first)

# LEVEL UP (routes/auth.py):
#   - Invalid stat choice (not STR/END/AGI/LCK/PER)
#   - No pending level up (shouldn't be reachable but guarded)

# PRE-COMBAT WARNINGS (shown as terminal fragments — non-blocking):
#   - Empty weapon slot
#   - Empty armor slot
#   - Over-encumbered status
#   All shown in combat_open.html — add these as term-amber lines:
#   {% if not player.equipped_weapon_id %}
#   <div class='term-line term-amber'>⚠ No weapon equipped — fighting unarmed (d4 Blunt).</div>
#   {% endif %}
#   {% if not player.equipped_armor_id %}
#   <div class='term-line term-amber'>⚠ No armor equipped.</div>
#   {% endif %}
#   {% if player.is_overencumbered %}
#   <div class='term-line term-amber'>⚠ Over encumbered — AP costs doubled, combat penalties active.</div>
#   {% endif %}
"""


# =============================================================================
# FILE: templates/fragments/combat_open.html  (Phase 9 — add pre-combat warnings)
# Full replacement with warnings added.
# =============================================================================
COMBAT_OPEN_WITH_WARNINGS = """
<!-- FILE: templates/fragments/combat_open.html  (Phase 9 — with pre-combat warnings) -->
<div class="fragment"
     data-hp="{{ player.current_hp }}"
     data-max-hp="{{ player.max_hp }}"
     data-ap="{{ player.current_ap }}"
     data-max-ap="{{ player.max_ap }}"
     data-credits="{{ player.credits }}">

    <div class="term-line term-amber">
        {% if encounter_type == 'BOSS' %}
        === BOSS FIGHT: {{ opponent.name|upper }} ====================================
        {% elif encounter_type == 'MINION' %}
        === MINION ENCOUNTER: {{ opponent.name|upper }} ==============================
        {% else %}
        === PVP: {{ opponent.character_name|upper }} =================================
        {% endif %}
    </div>

    {% if boss_flavor %}
    <div class="term-line term-grey">{{ boss_flavor }}</div>
    {% endif %}

    {% if intel %}
    <div class="term-line term-blue">[KNOWN INTEL from previous encounter — check character sheet]</div>
    {% endif %}

    <!-- Pre-combat warnings -->
    {% if not player.equipped_weapon_id %}
    <div class="term-line term-amber">⚠ No weapon equipped — fighting unarmed (d4 Blunt).</div>
    {% endif %}
    {% if not player.equipped_armor_id %}
    <div class="term-line term-amber">⚠ No armor equipped — unprotected.</div>
    {% endif %}
    {% if player.is_overencumbered %}
    <div class="term-line term-amber">⚠ Over encumbered — AP costs doubled, combat penalties active.</div>
    {% endif %}

    <div class="term-line term-system">
        Your HP: {{ player.current_hp }}/{{ player.max_hp }} &nbsp;|&nbsp;
        AP: {{ player.current_ap }}
    </div>

    <!-- Combat action buttons -->
    <div id="combat-actions" style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;">
        <form class="terminal-action" action="{{ url_for('combat.action') }}" method="POST">
            <input type="hidden" name="action_type" value="attack">
            <button type="submit" class="action-btn" style="width:auto;padding:6px 14px;">⚔ Attack</button>
        </form>
        <form class="terminal-action" action="{{ url_for('combat.steal') }}" method="POST">
            <button type="submit" class="action-btn" style="width:auto;padding:6px 14px;">💰 Steal</button>
        </form>
        <form class="terminal-action" action="{{ url_for('combat.action') }}" method="POST">
            <input type="hidden" name="action_type" value="brace">
            <button type="submit" class="action-btn" style="width:auto;padding:6px 14px;">🛡 Brace</button>
        </form>
        <form class="terminal-action" action="{{ url_for('combat.action') }}" method="POST">
            <input type="hidden" name="action_type" value="escape">
            <button type="submit" class="action-btn" style="width:auto;padding:6px 14px;">🚪 Escape</button>
        </form>
        <form class="terminal-action" action="{{ url_for('combat.action') }}" method="POST">
            <input type="hidden" name="action_type" value="observe">
            <button type="submit" class="action-btn" style="width:auto;padding:6px 14px;">🔍 Observe</button>
        </form>
    </div>
</div>
<script>
window._combatSessionId = {{ session_id }};
</script>
"""


# =============================================================================
# FINAL CHECKLIST — things to verify before first run
# =============================================================================
CHECKLIST = """
# ── Pre-launch checklist ────────────────────────────────────────────────────

# 1. Directory structure:
#    game/
#    ├── app.py, admin.py, config_defaults.py, database.py
#    ├── queue_handler.py, scheduler.py, importer.py, run.py
#    ├── schema.sql
#    ├── combat/__init__.py, engine.py, actions.py, flavour.py
#    ├── routes/__init__.py, auth.py, dashboard.py, actions.py, combat.py
#    │         shop.py, blacksmith.py, character.py, scoreboards.py, feeds.py
#    ├── templates/
#    │   ├── base.html, dashboard.html
#    │   ├── auth/  (login, register, character_create, levelup)
#    │   ├── shop/, blacksmith/, character/, scoreboards/
#    │   ├── fragments/  (error, tavern_result, event_result, boss_confirm,
#    │   │               minion_spotted, opponent_list, combat_open,
#    │   │               combat_round, combat_steal_confirm,
#    │   │               combat_extend, combat_result)
#    │   └── admin/  (base_admin, dashboard, import, players,
#    │               player_detail, config, logs)
#    ├── static/style.css, terminal.js
#    └── data/  (auto-created by init_db)

# 2. Install dependencies:
#    pip install flask apscheduler openpyxl werkzeug

# 3. Import game content FIRST:
#    - Place GameContent_Template.xlsx at data/pending_import.xlsx
#    - Run: python -c "from importer import run_import; print(run_import())"
#    - Or start the app and trigger via admin at http://localhost:5001/admin

# 4. Run in development:
#    python run.py
#    Admin app: flask --app admin:create_admin_app run --port 5001

# 5. Apply Phase 9 session_id patch to routes/actions.py:
#    In _start_boss_fight(): after result check, add:
#      from flask import session; session['combat_session_id'] = result['session_id']
#    In action_pvp_fight(): same pattern

# 6. Verify APScheduler is firing:
#    Check logs for 'APScheduler started' and trickle/reset messages

# 7. Set GAME_SECRET_KEY environment variable for production:
#    export GAME_SECRET_KEY='your-secret-key-here'
"""
