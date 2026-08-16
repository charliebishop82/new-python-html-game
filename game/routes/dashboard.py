"""Main player dashboard and context-sensitive action availability."""
# Dashboard feed assembly, action availability, and polling timestamps.
import logging
import re
from datetime import datetime, timedelta
from flask import Blueprint, render_template, g, session
from database import (execute, execute_write, exclusive_transaction, get_all_settings,
                      encumbered_ap_cost, tavern_quote)
import config_defaults as cfg

bp = Blueprint('dashboard', __name__)
logger = logging.getLogger(__name__)


@bp.route('/')
def index():
    """Handle the index workflow."""
    # Returning to the dashboard ends paid Shop and Blacksmith visits. Clicking
    # either service again starts a new visit and charges admission AP.
    session.pop("shop_access_granted", None)
    session.pop("blacksmith_access_granted", None)
    session.pop("blacksmith_visit_ap_spent", None)
    player   = g.player
    settings = get_all_settings()

    # daily_feed is archived and cleared at midnight. Load the whole active
    # day's history so leaving combat or visiting the character sheet never
    # makes earlier events appear to vanish.
    terminal_history = execute(
        '''SELECT id,feed_scope,player_id,flavor_text,event_category,occurred_at,combat_session_id
           FROM daily_feed
           WHERE player_id = ? OR feed_scope = 'GLOBAL'
           ORDER BY datetime(occurred_at) ASC,id ASC''',
        (player['id'],)
    )

    # Tutorial lines used to be permanent feed rows, which caused them to
    # reappear on every dashboard load. Hide those historical copies and add a
    # transient copy only on the first successful login of each UTC day.
    from routes.auth import get_tutorial_messages
    tutorial_messages = get_tutorial_messages()
    tutorial_text = {text for _, text in tutorial_messages}
    terminal_history = [
        entry for entry in terminal_history
        if not (entry['feed_scope'] == 'PERSONAL' and entry['flavor_text'] in tutorial_text)
    ]
    if session.pop("show_daily_tutorial", False):
        base_time = datetime.utcnow()
        terminal_history.extend({
            "id": None,
            "feed_scope": "PERSONAL",
            "player_id": player["id"],
            "flavor_text": text,
            "event_category": category,
            "occurred_at": (base_time + timedelta(seconds=index)).isoformat(),
            "combat_session_id": None,
        } for index, (category, text) in enumerate(tutorial_messages))

    # A completed fight writes a private result and an identical public world
    # announcement. Show the private copy in the terminal and leave the public
    # copy to the world ticker, avoiding apparent duplicate rewards/results.
    private_combat = {
        (entry.get('combat_session_id'), entry['flavor_text'])
        for entry in terminal_history
        if entry['feed_scope'] == 'PERSONAL' and entry.get('combat_session_id')
    }
    terminal_history = [
        entry for entry in terminal_history
        if not (entry['feed_scope'] == 'GLOBAL'
                and (entry.get('combat_session_id'), entry['flavor_text']) in private_combat)
    ]

    # Historical random-event rows predate effect summaries. Reconstruct them
    # from content so old feed lines become as useful as newly generated ones.
    random_events = execute("SELECT * FROM random_events WHERE is_active=1")
    from combat.flavour import random_event_flavor
    from routes.actions import _describe_random_event_effect
    for entry in terminal_history:
        # Interruption entries created before dedicated feed categories existed
        # are relabelled for today's dashboard without rewriting audit history.
        if (entry['event_category'] == 'RANDOM_EVENT'
                and entry['flavor_text'].startswith('INTERRUPTION:')):
            entry['event_category'] = 'INTERRUPTION_HOSTILE'
        elif (entry['event_category'] == 'RANDOM_EVENT'
              and 'looks you over and hands you the ' in entry['flavor_text']):
            entry['event_category'] = 'INTERRUPTION_FRIENDLY'
        if entry['event_category'] != 'RANDOM_EVENT' or 'Effect:' in entry['flavor_text']:
            continue
        for event in random_events:
            if random_event_flavor(event, player['character_name']) == entry['flavor_text']:
                entry['flavor_text'] += f"  Effect: {_describe_random_event_effect(event)}."
                break

    # Condense every turn belonging to a combat session into one expandable
    # record, even when live world announcements arrived between its rounds.
    # A short narrative preserves damage and outcomes; bracketed roll math is
    # retained only inside the full transcript.
    grouped_history = []
    combat_groups = {}
    for entry in terminal_history:
        if entry['event_category'] == 'COMBAT_TURN' and entry.get('combat_session_id'):
            session_id = entry['combat_session_id']
            concise = re.sub(r'\s*\[[^\]]*\]', '', entry['flavor_text'])
            concise = re.sub(r'^Round\s+([^—]+)—\s+Initiative:.*?\.\s+',
                             r'Round \1— ', concise)
            concise = concise.replace(player['character_name'], 'You')
            concise = re.sub(r'\s+', ' ', concise).strip()
            if session_id in combat_groups:
                group = combat_groups[session_id]
                group['details'].append(entry['flavor_text'])
                group['summaries'].append(concise)
                group['flavor_text'] = f"Combat #{session_id} · {len(group['details'])} rounds recorded"
                continue
            group = {**entry, 'event_category': 'COMBAT_ROUNDS',
                     'details': [entry['flavor_text']], 'summaries': [concise],
                     'flavor_text': f"Combat #{session_id} · 1 round recorded"}
            combat_groups[session_id] = group
            grouped_history.append(group)
        else:
            grouped_history.append(entry)
    terminal_history = grouped_history

    important_categories = {
        'PVP_DEFENSE', 'COMBAT', 'LEVEL_UP', 'REWARD', 'CONTRACT', 'AUCTION',
        'WORLD_BOSS_REWARD', 'INTERRUPTION_FRIENDLY', 'INTERRUPTION_HOSTILE',
    }
    previous_feed_visit = session.get('dashboard_feed_seen_at')
    try:
        previous_feed_dt = datetime.fromisoformat(previous_feed_visit) if previous_feed_visit else None
        if previous_feed_dt and previous_feed_dt.tzinfo:
            previous_feed_dt = previous_feed_dt.replace(tzinfo=None)
    except (TypeError, ValueError):
        previous_feed_dt = None
    for entry in terminal_history:
        entry['important'] = entry['event_category'] in important_categories
        try:
            occurred_dt = datetime.fromisoformat(str(entry['occurred_at']).replace('Z', '+00:00'))
            # SQLite timestamps and session timestamps are both UTC but may use
            # different separators. Compare naive UTC values consistently.
            if occurred_dt.tzinfo:
                occurred_dt = occurred_dt.replace(tzinfo=None)
            entry['is_new'] = bool(previous_feed_dt and occurred_dt > previous_feed_dt)
        except (TypeError, ValueError):
            entry['is_new'] = False

    button_states = _get_button_states(player, settings)

    # Inject current UTC timestamp for JS feed polling start point
    now_iso = datetime.utcnow().isoformat()
    session['dashboard_feed_seen_at'] = now_iso

    active_effects = execute(
        "SELECT effect_type, value FROM status_effects WHERE player_id = ?", (player["id"],)
    )
    label_map = {
        "STAT_BOOST_STR": "+STR", "STAT_BOOST_END": "+END", "STAT_BOOST_AGI": "+AGI",
        "STAT_BOOST_LCK": "+LCK", "STAT_BOOST_PER": "+PER", "STAT_BOOST_INITIATIVE": "+INIT",
        "STAT_PENALTY_STR": "-STR", "STAT_PENALTY_END": "-END", "STAT_PENALTY_AGI": "-AGI",
        "STAT_PENALTY_LCK": "-LCK", "STAT_PENALTY_PER": "-PER", "STAT_PENALTY_INITIATIVE": "-INIT",
        "CURSED": "CURSED",
    }
    effect_labels = [
        f"{label_map.get(e['effect_type'], e['effect_type'])} {int(abs(e['value']))}"
        for e in active_effects
    ]
    active_combat = _load_active_combat(player)
    from routes.actions import get_pending_interrupted_action, _minion_per_check
    pending_minion_data = session.get("pending_minion_prompt")
    pending_minion_prompt = None
    if pending_minion_data and not active_combat:
        minions = execute(
            "SELECT * FROM minions WHERE id=? AND is_active=1",
            (pending_minion_data.get("minion_id"),)
        )
        if minions:
            minion = minions[0]
            pending_minion_prompt = {
                "minion": minion,
                "per_result": _minion_per_check(player, minion),
                "interruption": {"check": pending_minion_data.get("check", {})},
                "level_diff": minion["level"] - player["level"],
            }
    pending_action = (None if active_combat else
                      get_pending_interrupted_action(player["id"]))

    # Hostile actions can happen while a player is offline and may cross the
    # midnight feed reset. Persistent unseen defense events are therefore shown
    # prominently once, while the permanent activity record remains for admin.
    unread_defense_events = execute(
        """SELECT id,message,status,occurred_at
           FROM player_activity_log
           WHERE player_id=? AND source='PVP_DEFENSE' AND seen_at IS NULL
           ORDER BY datetime(occurred_at) ASC,id ASC""",
        (player["id"],)
    )
    if unread_defense_events:
        placeholders = ",".join("?" for _ in unread_defense_events)
        with exclusive_transaction():
            execute_write(
                f"UPDATE player_activity_log SET seen_at=? WHERE id IN ({placeholders})",
                (datetime.utcnow().isoformat(), *[event["id"] for event in unread_defense_events])
            )

    return render_template(
        'dashboard.html',
        terminal_history=terminal_history,
        button_states=button_states,
        blackout=g.get('blackout', False),
        now_iso=now_iso,
        effect_labels=effect_labels,
        active_combat=active_combat,
        pending_action=pending_action,
        pending_minion_prompt=pending_minion_prompt,
        unread_defense_events=unread_defense_events,
    )


def _load_active_combat(player: dict) -> dict | None:
    """Restore a player-controlled active fight after navigation or reconnecting."""
    if not player.get("in_combat"):
        return None
    rows = execute(
        """SELECT * FROM combat_sessions
           WHERE attacker_player_id=? AND status='ACTIVE' ORDER BY id DESC LIMIT 1""",
        (player["id"],),
    )
    if not rows:
        return None
    combat_session = rows[0]
    session["combat_session_id"] = combat_session["id"]
    from combat.actions import get_combat_state
    from combat.flavour import hp_status
    from combat.engine import calc_max_hp
    state = get_combat_state(combat_session["id"])
    encounter_type = combat_session["combat_type"]
    opponent = state["defender"] if encounter_type == "PVP" else state["boss"] or state["minion"]
    opponent_max_hp = calc_max_hp(opponent) if encounter_type == "PVP" else opponent["max_hp"]
    inventory = execute(
        """SELECT ii.id inv_id,ii.item_type,
                  CASE ii.item_type WHEN 'WEAPON' THEN w.name WHEN 'ARMOR' THEN a.name ELSE s.name END name
           FROM inventory_items ii
           LEFT JOIN weapons w ON ii.item_type='WEAPON' AND w.id=ii.item_id
           LEFT JOIN armor a ON ii.item_type='ARMOR' AND a.id=ii.item_id
           LEFT JOIN special_items s ON ii.item_type='SPECIAL' AND s.id=ii.item_id
           WHERE ii.player_id=? ORDER BY ii.item_type,name""", (player["id"],))
    return {
        "opponent": opponent, "encounter_type": encounter_type,
        "session_id": combat_session["id"], "intel": None, "intel_detail": None,
        "opponent_health": hp_status(opponent["current_hp"], opponent_max_hp),
        "boss_flavor": opponent.get("flavor_text", ""),
        "opponent_description": opponent.get("description", ""),
        "boss_phase": opponent.get("current_phase", 1), "inventory": inventory,
    }


def _get_button_states(player: dict, settings: dict) -> dict:
    """Load button states from current database state."""
    in_combat  = player['in_combat']
    current_ap = player['current_ap']
    credits    = player['credits']
    current_hp = player['current_hp']
    max_hp     = player['max_hp']
    blackout   = g.get('blackout', False)

    ap_boss       = settings.get('AP_COST_BOSS',       cfg.AP_COST_BOSS)
    ap_pvp        = settings.get('AP_COST_PVP',        cfg.AP_COST_PVP)
    ap_world      = settings.get('AP_COST_WORLD_BOSS', cfg.AP_COST_WORLD_BOSS)
    ap_tavern     = settings.get('AP_COST_TAVERN',     cfg.AP_COST_TAVERN)
    ap_blacksmith = settings.get('AP_COST_BLACKSMITH', cfg.AP_COST_BLACKSMITH)
    ap_shop       = settings.get('AP_COST_SHOP',       cfg.AP_COST_SHOP)
    ap_auction    = settings.get('AP_COST_AUCTION',    cfg.AP_COST_AUCTION)
    ap_boss       = encumbered_ap_cost(player, ap_boss, settings)
    ap_pvp        = encumbered_ap_cost(player, ap_pvp, settings)
    ap_world      = encumbered_ap_cost(player, ap_world, settings)
    ap_tavern     = encumbered_ap_cost(player, ap_tavern, settings)
    ap_blacksmith = encumbered_ap_cost(player, ap_blacksmith, settings)
    ap_shop       = encumbered_ap_cost(player, ap_shop, settings)
    ap_auction    = encumbered_ap_cost(player, ap_auction, settings)
    tavern_quote_now = tavern_quote(player, settings)
    tavern_cost = tavern_quote_now['credit_cost']

    from world_boss import get_active_event
    world_event = get_active_event()

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

    if not world_event:
        world_ok, world_reason = False, 'No active weekly boss'
    elif in_combat:
        world_ok, world_reason = False, 'In combat'
    elif blackout:
        world_ok, world_reason = False, 'Approaching midnight reset'
    elif current_ap < ap_world:
        world_ok, world_reason = False, f'Need {ap_world} AP'
    else:
        world_ok, world_reason = True, None

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

    if in_combat:
        auction_ok, auction_reason = False, 'In combat'
    elif current_ap < ap_auction:
        auction_ok, auction_reason = False, f'Need {ap_auction} AP'
    else:
        auction_ok, auction_reason = True, None

    return {
        'boss':       {'enabled': boss_ok,   'reason': boss_reason,   'ap_cost': ap_boss},
        'pvp':        {'enabled': pvp_ok,    'reason': pvp_reason,    'ap_cost': ap_pvp},
        'world_boss': {'enabled': world_ok,  'reason': world_reason,  'ap_cost': ap_world},
        'tavern':     {'enabled': tavern_ok, 'reason': tavern_reason, 'ap_cost': ap_tavern,
                       'credit_cost': tavern_cost, 'heal_amount': tavern_quote_now['heal_amount']},
        'blacksmith': {'enabled': bs_ok,     'reason': bs_reason,     'ap_cost': ap_blacksmith},
        'shop':       {'enabled': shop_ok,   'reason': shop_reason,   'ap_cost': ap_shop},
        'auction':    {'enabled': auction_ok,'reason': auction_reason,'ap_cost': ap_auction},
    }
