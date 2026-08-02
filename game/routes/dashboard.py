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
