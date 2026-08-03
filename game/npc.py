"""Automated player-character decisions using the normal queued action handlers."""

import logging
import math
import random
import hashlib
import json
from datetime import datetime, timedelta

import config_defaults as cfg
from database import (execute, execute_one, execute_write, exclusive_transaction,
                      get_all_settings, get_player)
from queue_handler import enqueue_and_process

logger = logging.getLogger(__name__)


def _ensure_handlers_loaded():
    # Importing these modules registers their queue handlers.
    """Provide the internal ensure handlers loaded operation used by this module."""
    import routes.actions  # noqa: F401
    import routes.auth  # noqa: F401
    import routes.blacksmith  # noqa: F401
    import routes.combat  # noqa: F401
    import routes.shop  # noqa: F401


def run_due_npc_turns(now: datetime | None = None) -> dict:
    """Run staggered AP-driven NPC decisions.

    There is one deterministic, daily-random wake time in each three-hour
    window. During 23:00-23:55 UTC, NPCs receive repeated opportunities to use
    remaining AP. AP is never erased; only real player actions spend it.
    """
    now = now or datetime.utcnow()
    profiles = execute(
        """SELECT np.* FROM npc_profiles np JOIN players p ON p.id=np.player_id
           WHERE np.enabled=1 AND np.retired=0 AND p.is_banned=0
           ORDER BY COALESCE(np.last_action_at, '') ASC"""
    )
    results = []
    for profile in profiles:
        if not _npc_is_due(profile, now):
            continue
        try:
            attempts = 12 if now.hour == 23 else 1
            no_ap_progress = 0
            for _ in range(attempts):
                player = get_player(profile["player_id"])
                if not player or player["current_ap"] <= 0:
                    break
                ap_before = player["current_ap"]
                result = run_npc_turn(profile["player_id"])
                results.append(result)
                if now.hour != 23 or result["decision"] in ("WAIT", "SKIP"):
                    break
                player_after = get_player(profile["player_id"])
                if player_after and player_after["current_ap"] >= ap_before:
                    no_ap_progress += 1
                    if no_ap_progress >= 2:
                        break
                else:
                    no_ap_progress = 0
        except Exception as exc:
            logger.exception("NPC turn failed for player %d", profile["player_id"])
            _log(profile["player_id"], "ERROR", "Turn raised an exception", str(exc))
    return {"processed": len(results), "results": results}


def _npc_is_due(profile: dict, now: datetime) -> bool:
    """Provide the internal npc is due operation used by this module."""
    last = None
    if profile.get("last_action_at"):
        try:
            last = datetime.fromisoformat(profile["last_action_at"])
        except ValueError:
            pass
    if now.hour == 23:
        # One catch-up attempt per five-minute scheduler slot.
        slot = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
        return last is None or last < slot
    window_start = now.replace(hour=(now.hour // 3) * 3, minute=0, second=0, microsecond=0)
    identity = f"{now.date().isoformat()}:{profile['player_id']}:{now.hour // 3}".encode()
    offset = int.from_bytes(hashlib.sha256(identity).digest()[:4], "big") % 165
    scheduled = window_start + timedelta(minutes=offset)
    return now >= scheduled and (last is None or last < scheduled)


def run_npc_turn(player_id: int) -> dict:
    """Handle the run npc turn workflow."""
    _ensure_handlers_loaded()
    profile = execute_one("SELECT * FROM npc_profiles WHERE player_id=?", (player_id,))
    player = get_player(player_id)
    if not profile or not player or not profile["enabled"] or profile["retired"]:
        return {"player_id": player_id, "decision": "SKIP", "result": "NPC inactive"}

    _assign_pending_levelup(player_id, profile)
    player = get_player(player_id)

    if player["in_combat"]:
        active = execute_one(
            "SELECT combat_type FROM combat_sessions WHERE attacker_player_id=? AND status='ACTIVE' ORDER BY id DESC LIMIT 1",
            (player_id,)
        )
        result = (_finish_thief_combat(player_id) if profile["thief"] > 0 and active
                  and active["combat_type"] == "PVP" else _finish_active_combat(player_id, profile=profile))
        return _finish_turn(profile, "COMBAT", "An active fight must be resolved first", result)

    equipment_changes = _equip_best_items(player_id, profile)
    if equipment_changes:
        _log(player_id, "EQUIP", "Re-evaluated owned equipment", ", ".join(equipment_changes))
    player = get_player(player_id)
    settings = get_all_settings()

    # NPCs live under the same rules as human players, including random
    # events. An event modifies the turn but does not replace the chosen action.
    from routes.actions import check_random_event
    check_random_event(player, settings)
    player = get_player(player_id)

    repair_result = _maybe_repair(player, profile)
    if repair_result:
        return _finish_turn(profile, "REPAIR", repair_result[0], repair_result[1])

    heal_result = _maybe_heal(player, profile, settings)
    if heal_result:
        return _finish_turn(profile, "HEAL", heal_result[0], heal_result[1])

    shop_result = _maybe_manage_inventory(player, profile, settings)
    if shop_result:
        return _finish_turn(profile, "SHOP", shop_result[0], shop_result[1])

    # Do not enqueue actions that are already known to be unaffordable. A small
    # AP remainder is legitimate when no useful legal action fits that balance.
    pvp_cost = settings.get("AP_COST_PVP", cfg.AP_COST_PVP)
    boss_cost = settings.get("AP_COST_BOSS", cfg.AP_COST_BOSS)
    can_pvp = player["current_ap"] >= pvp_cost
    can_boss = player["current_ap"] >= boss_cost
    pvp_targets = _eligible_pvp_targets(player) if can_pvp else []
    if not can_pvp and not can_boss:
        return _finish_turn(
            profile, "WAIT", "Remaining AP cannot fund another useful action",
            f"{player['current_ap']} AP remains; cheapest available combat costs {min(pvp_cost, boss_cost)} AP"
        )
    if profile["thief"] >= max(profile["player_hunter"], profile["boss_killer"],
                                profile["hoarder"]):
        last_mode = execute_one(
            """SELECT decision FROM npc_action_log WHERE player_id=?
               AND decision IN ('PVP_STEAL','BOSS','MINION') ORDER BY id DESC LIMIT 1""",
            (player_id,)
        )
        steal_turn = not last_mode or last_mode["decision"] in ("BOSS", "MINION")
        if steal_turn and pvp_targets and can_pvp:
            interrupted = _roll_minion_interruption(player, settings)
            if interrupted:
                result = enqueue_and_process(
                    player_id, "start_boss_fight",
                    {"opponent_id": interrupted["id"], "encounter_type": "MINION",
                     "cost_ap": boss_cost}
                )
                if result.get("error"):
                    return _finish_turn(profile, "MINION", "Minion interrupted PvP theft", result["error"])
                combat = _finish_active_combat(player_id, result["session_id"], profile)
                return _finish_turn(profile, "MINION",
                                    f"{interrupted['name']} interrupted PvP theft", combat)
            target = random.choice(pvp_targets)
            result = enqueue_and_process(
                player_id, "start_pvp_fight",
                {"target_id": target["id"], "cost_ap": settings.get("AP_COST_PVP", cfg.AP_COST_PVP)}
            )
            if result.get("error"):
                return _finish_turn(profile, "PVP_STEAL", "Random eligible target selected", result["error"])
            combat = _finish_thief_combat(player_id, result["session_id"])
            return _finish_turn(profile, "PVP_STEAL", f"Attempted theft from {target['character_name']}", combat)
        # Alternate with the same boss/minion encounter roll a human receives
        # from the Boss action. If PvP is unavailable, this is also the normal
        # combat fallback under the existing eligibility rules.
        encounter_type, opponent = _choose_combat_encounter(player, settings)
        if opponent and can_boss:
            result = enqueue_and_process(
                player_id, "start_boss_fight",
                {"opponent_id": opponent["id"], "encounter_type": encounter_type,
                 "cost_ap": settings.get("AP_COST_BOSS", cfg.AP_COST_BOSS)}
            )
            if not result.get("error"):
                combat = _finish_active_combat(player_id, result["session_id"], profile)
                return _finish_turn(profile, encounter_type,
                                    f"Alternated to {encounter_type.lower()} {opponent['name']} for XP",
                                    combat)
            return _finish_turn(profile, encounter_type, "Thief's XP-building turn", result["error"])

    pvp_score = profile["player_hunter"] + random.randint(-10, 10)
    boss_score = profile["boss_killer"] + random.randint(-10, 10)
    if not pvp_targets:
        boss_score += profile["player_hunter"]  # hunter fallback
    if profile["hoarder"] >= max(profile["player_hunter"], profile["boss_killer"],
                                  profile["thief"]):
        # When no worthwhile shop transaction is available, hoarders pursue
        # loot-bearing bosses instead of drifting into arbitrary PvP.
        boss_score += profile["hoarder"]

    if can_pvp and pvp_targets and pvp_score >= boss_score:
        interrupted = _roll_minion_interruption(player, settings)
        if interrupted:
            result = enqueue_and_process(
                player_id, "start_boss_fight",
                {"opponent_id": interrupted["id"], "encounter_type": "MINION",
                 "cost_ap": boss_cost}
            )
            if result.get("error"):
                return _finish_turn(profile, "MINION", "Minion interrupted PvP hunt", result["error"])
            combat = _finish_active_combat(player_id, result["session_id"], profile)
            return _finish_turn(profile, "MINION",
                                f"{interrupted['name']} interrupted PvP hunt", combat)
        target = _choose_pvp_target(player, pvp_targets, profile["aggression"])
        result = enqueue_and_process(
            player_id, "start_pvp_fight",
            {"target_id": target["id"], "cost_ap": settings.get("AP_COST_PVP", cfg.AP_COST_PVP)}
        )
        if result.get("error"):
            return _finish_turn(profile, "PVP", "Highest motivation was player hunting", result["error"])
        combat = _finish_active_combat(player_id, result["session_id"], profile)
        return _finish_turn(profile, "PVP", f"Targeted {target['character_name']}", combat)

    encounter_type, opponent = _choose_combat_encounter(player, settings)
    if opponent and can_boss:
        result = enqueue_and_process(
            player_id, "start_boss_fight",
            {"opponent_id": opponent["id"], "encounter_type": encounter_type,
             "cost_ap": settings.get("AP_COST_BOSS", cfg.AP_COST_BOSS)}
        )
        if not result.get("error"):
            combat = _finish_active_combat(player_id, result["session_id"], profile)
            return _finish_turn(profile, encounter_type,
                                f"Hunted {encounter_type.lower()} {opponent['name']}", combat)
        return _finish_turn(profile, encounter_type, "Boss/minion hunt selected", result["error"])

    return _finish_turn(profile, "WAIT", "No legal useful action was available", "No action")


def spend_npc_ap_now(player_id: int, max_decisions: int = 24) -> dict:
    """Run normal NPC decisions immediately until AP or useful progress stops."""
    starting = get_player(player_id)
    if not starting:
        raise ValueError("NPC player not found.")
    if not execute_one("SELECT 1 FROM npc_profiles WHERE player_id=? AND enabled=1 AND retired=0",
                       (player_id,)):
        raise ValueError("NPC is paused or retired.")
    results = []
    no_ap_progress = 0
    for _ in range(max(1, min(50, max_decisions))):
        before = get_player(player_id)
        if before["current_ap"] <= 0:
            break
        result = run_npc_turn(player_id)
        results.append(result)
        after = get_player(player_id)
        if result["decision"] in ("WAIT", "SKIP"):
            break
        if after["current_ap"] >= before["current_ap"]:
            no_ap_progress += 1
            if no_ap_progress >= 2:
                break
        else:
            no_ap_progress = 0
    ending = get_player(player_id)
    return {
        "player_id": player_id, "decisions": len(results),
        "ap_spent": max(0, starting["current_ap"] - ending["current_ap"]),
        "ap_remaining": ending["current_ap"], "results": results,
    }


def retire_npc(player_id: int):
    """Safely retire an NPC and return its unique specials to the pool."""
    now = datetime.utcnow().isoformat()
    with exclusive_transaction():
        active_sessions = execute(
            """SELECT id,attacker_player_id,defender_player_id FROM combat_sessions
               WHERE status='ACTIVE' AND (attacker_player_id=? OR defender_player_id=?)""",
            (player_id, player_id)
        )
        for session in active_sessions:
            execute_write(
                "UPDATE combat_sessions SET status='ABANDONED',result='NPC_RETIRED',resolved_at=? WHERE id=?",
                (now, session["id"])
            )
            other_id = (session["defender_player_id"] if session["attacker_player_id"] == player_id
                        else session["attacker_player_id"])
            if other_id:
                execute_write("UPDATE players SET in_combat=0 WHERE id=?", (other_id,))
        specials = execute(
            "SELECT id,item_id FROM inventory_items WHERE player_id=? AND item_type='SPECIAL'",
            (player_id,)
        )
        for item in specials:
            execute_write(
                """UPDATE special_item_registry SET status='IN_POOL',current_owner_player_id=NULL,
                   inventory_item_id=NULL,last_released_method='NPC_RETIRED',updated_at=?
                   WHERE special_item_id=?""", (now, item["item_id"])
            )
        execute_write("DELETE FROM inventory_items WHERE player_id=? AND item_type='SPECIAL'", (player_id,))
        execute_write("UPDATE npc_profiles SET enabled=0,retired=1 WHERE player_id=?", (player_id,))
        execute_write("UPDATE players SET in_combat=0,is_banned=1 WHERE id=?", (player_id,))


def _finish_active_combat(player_id: int, session_id: int | None = None,
                          profile: dict | None = None) -> str:
    """Provide the internal finish active combat operation used by this module."""
    if session_id is None:
        row = execute_one(
            "SELECT id FROM combat_sessions WHERE attacker_player_id=? AND status='ACTIVE' ORDER BY id DESC LIMIT 1",
            (player_id,)
        )
        if not row:
            return "No active attacker combat found"
        session_id = row["id"]
    final = None
    for _ in range(20):
        action = _choose_combat_action(player_id, session_id, profile)
        final = enqueue_and_process(
            player_id, "combat_action", {"session_id": session_id, "action_type": action}
        )
        if any(entry.get("escaped") for entry in final.get("round_log", [])):
            return f"Combat {session_id} ended by escape"
        if final.get("combat_ended"):
            return f"Combat {session_id} completed ({final.get('winner_side')})"
        if final.get("at_round_limit"):
            enqueue_and_process(player_id, "combat_resolve", {"session_id": session_id})
            return f"Combat {session_id} resolved at round limit"
    # An automated character cannot leave an unbounded fight active forever.
    # After the normal batch, attempt the same AP-backed Escape action available
    # to a human player. A failed roll leaves combat active for a later turn.
    session_row = execute_one("SELECT status,current_round FROM combat_sessions WHERE id=?", (session_id,))
    player = get_player(player_id)
    settings = get_all_settings()
    escape_cost = settings.get("AP_COST_ESCAPE", cfg.AP_COST_ESCAPE)
    if session_row and session_row["status"] == "ACTIVE" and player and player["current_ap"] >= escape_cost:
        escaped = enqueue_and_process(
            player_id, "combat_action", {"session_id": session_id, "action_type": "escape"}
        )
        escape_event = next((event for event in escaped.get("round_log", [])
                             if event.get("action") == "ESCAPE"), {})
        if escape_event.get("escaped"):
            return f"Combat {session_id} exceeded the safety window; NPC escaped"
        return f"Combat {session_id} exceeded the safety window; escape attempt failed"
    return f"Combat {session_id} remains active after safety limit; insufficient AP to escape"


def _choose_combat_action(player_id: int, session_id: int, profile: dict | None) -> str:
    """Choose among the same Attack, Brace, Observe, and Escape actions as a player.

    Player ID supplies a stable temperament offset while the per-round roll
    prevents two otherwise identical NPCs from following the same script.
    """
    if not profile:
        return "attack"
    player = get_player(player_id)
    session_row = execute_one("SELECT * FROM combat_sessions WHERE id=?", (session_id,))
    if not player or not session_row:
        return "attack"

    temperament = random.Random(player_id * 104729)
    boldness = temperament.randint(-12, 12)
    curiosity = temperament.randint(-10, 10)
    caution = temperament.randint(-12, 12)
    hp_ratio = player["current_hp"] / max(1, player["max_hp"])
    aggression = max(0, min(100, profile["aggression"] + boldness))
    safety = max(0, min(100, profile["self_preservation"] + caution))

    weights = {"attack": 60.0, "brace": 5.0, "observe": 0.0, "escape": 0.0}
    if profile["player_hunter"] >= max(profile["boss_killer"], profile["hoarder"]):
        weights["attack"] += 20 + aggression * 0.2
        weights["brace"] += safety * 0.05
    if profile["boss_killer"] >= max(profile["player_hunter"], profile["hoarder"]):
        weights["observe"] += max(0, 35 + curiosity)
        weights["brace"] += 10 + safety * 0.08
    if profile["hoarder"] >= max(profile["player_hunter"], profile["boss_killer"]):
        weights["brace"] += 20 + safety * 0.15
        weights["escape"] += 10 + safety * 0.12

    # Observation is useful once per encounter; afterward its weight becomes 0.
    if session_row["attacker_observed"]:
        weights["observe"] = 0
    elif weights["observe"] == 0 and random.random() < 0.08:
        weights["observe"] = 8 + curiosity

    # Survival decisions intensify as HP falls, but aggression can keep a bold
    # character fighting longer. Escape remains subject to its normal AP cost.
    if hp_ratio < 0.55:
        weights["brace"] += (1 - hp_ratio) * safety
    if hp_ratio < 0.30:
        weights["escape"] += (0.30 - hp_ratio) * safety * 5
        weights["attack"] = max(5, weights["attack"] - safety * 0.35)
    settings = get_all_settings()
    if player["current_ap"] < settings.get("AP_COST_ESCAPE", cfg.AP_COST_ESCAPE):
        weights["escape"] = 0

    choices = [(action, max(0, weight + random.uniform(-8, 8)))
               for action, weight in weights.items()]
    total = sum(weight for _, weight in choices)
    if total <= 0:
        return "attack"
    pick = random.uniform(0, total)
    for action, weight in choices:
        pick -= weight
        if pick <= 0:
            return action
    return "attack"


def _finish_thief_combat(player_id: int, session_id: int | None = None) -> str:
    """Use only the normal Steal and Escape actions available to players."""
    if session_id is None:
        row = execute_one(
            "SELECT id FROM combat_sessions WHERE attacker_player_id=? AND status='ACTIVE' ORDER BY id DESC LIMIT 1",
            (player_id,)
        )
        if not row:
            return "No active thief combat found"
        session_id = row["id"]

    stole = False
    for _ in range(20):
        session_row = execute_one("SELECT status FROM combat_sessions WHERE id=?", (session_id,))
        if not session_row or session_row["status"] != "ACTIVE":
            return f"Combat {session_id} ended after {'a successful steal' if stole else 'the steal attempt'}"
        if not stole:
            result = enqueue_and_process(player_id, "combat_steal", {"session_id": session_id})
            steal_action = next((a for a in result.get("round_log", []) if a.get("action") == "STEAL"), {})
            stole = bool(steal_action.get("success"))
            if result.get("combat_ended"):
                return f"Combat {session_id} ended before escape"
        else:
            result = enqueue_and_process(
                player_id, "combat_action", {"session_id": session_id, "action_type": "escape"}
            )
            escape_action = next((a for a in result.get("round_log", []) if a.get("action") == "ESCAPE"), {})
            if escape_action.get("escaped"):
                return f"Stole successfully and escaped combat {session_id}"
            if result.get("combat_ended"):
                return f"Stole successfully but combat {session_id} ended before escape"
    return f"Combat {session_id} remains active after thief safety limit"


def _assign_pending_levelup(player_id: int, profile: dict):
    """Provide the internal assign pending levelup operation used by this module."""
    player = get_player(player_id)
    if not player or not player["pending_levelup"]:
        return
    if profile["thief"] >= max(profile["player_hunter"], profile["boss_killer"], profile["hoarder"]):
        priorities = ("agi", "lck", "per")
    elif profile["boss_killer"] >= max(profile["player_hunter"], profile["hoarder"]):
        priorities = ("str", "end", "agi")
    elif profile["hoarder"] >= profile["player_hunter"]:
        priorities = ("lck", "per", "end")
    else:
        priorities = ("agi", "per", "str")
    # Choose the currently lowest preferred stat, randomizing exact ties.
    lowest = min(player[f"{stat}_stat"] for stat in priorities)
    choices = [stat for stat in priorities if player[f"{stat}_stat"] == lowest]
    enqueue_and_process(player_id, "assign_levelup", {"stat": random.choice(choices)})


def _maybe_repair(player: dict, profile: dict):
    """Repair equipped gear only when the NPC can afford the complete action."""
    if random.randint(1, 100) > profile["repair_tendency"]:
        return None
    settings = get_all_settings()
    if (player["current_ap"] < settings.get("AP_COST_BLACKSMITH", cfg.AP_COST_BLACKSMITH)
            or player["credits"] <= 0):
        return None
    threshold = 40 + profile["repair_tendency"] // 2
    equipped = [
        player.get("equipped_weapon_id"),
        player.get("equipped_armor_id"),
        player.get("equipped_special_id"),
    ]
    damaged = execute(
        """SELECT id,item_type,item_id,current_durability
           FROM inventory_items WHERE player_id=? AND id IN (?,?,?)
           AND current_durability < 100""",
        (player["id"], *(inv_id or -1 for inv_id in equipped))
    )
    if not any(item["current_durability"] < threshold for item in damaged):
        return None

    # The blacksmith repairs every damaged equipped item in this mode.  Check
    # that complete price before entering the queue so an unaffordable repair
    # is not logged as a failed action and retried without spending AP.
    item_tables = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}
    cost_pct = settings.get("REPAIR_COST_PERCENT", cfg.REPAIR_COST_PERCENT)
    total_cost = 0
    for item in damaged:
        table = item_tables.get(item["item_type"])
        detail = execute_one(f"SELECT credit_cost FROM {table} WHERE id=?", (item["item_id"],)) if table else None
        if detail:
            missing = 100 - item["current_durability"]
            total_cost += max(0, int(detail["credit_cost"] * cost_pct * (missing / 100)))
    if player["credits"] < total_cost:
        return None
    try:
        result = enqueue_and_process(player["id"], "blacksmith_repair", {"mode": "equipped", "inv_ids": []})
        return (f"Equipped gear fell below {threshold}% durability", str(result))
    except RuntimeError as exc:
        return ("Repair was desirable but unaffordable", str(exc))


def _maybe_heal(player: dict, profile: dict, settings: dict):
    """Provide the internal maybe heal operation used by this module."""
    hp_ratio = player["current_hp"] / max(1, player["max_hp"])
    threshold = 0.25 + (profile["self_preservation"] / 200)
    if hp_ratio >= threshold:
        return None
    cost_ap = settings.get("AP_COST_TAVERN", cfg.AP_COST_TAVERN)
    cost_cr = settings.get("TAVERN_HEAL_COST", cfg.TAVERN_HEAL_COST)
    if player["current_ap"] < cost_ap or player["credits"] < cost_cr:
        return None
    try:
        result = enqueue_and_process(player["id"], "tavern_heal", {
            "cost_ap": cost_ap, "cost_cr": cost_cr,
        })
        return (f"HP was below {int(threshold * 100)}% safety threshold", str(result))
    except RuntimeError as exc:
        return ("Healing was desirable but unavailable", str(exc))


def _maybe_manage_inventory(player: dict, profile: dict, settings: dict):
    """Occasionally sell obsolete gear or buy a meaningful, affordable upgrade.

    The NPC sees only its own inventory and the same public shop listings as a
    human player. One sale or purchase consumes the normal configured Shop AP.
    """
    ap_cost = settings.get("AP_COST_SHOP", cfg.AP_COST_SHOP)
    if player["current_ap"] < ap_cost:
        return None

    owned = _load_scored_inventory(player, profile)
    inv_count = len(owned)
    # Make space when full. Hoarders protect specials; other personalities sell
    # the least useful unequipped item regardless of category.
    if inv_count >= player["inventory_limit"]:
        equipped = {player.get("equipped_weapon_id"), player.get("equipped_armor_id"),
                    player.get("equipped_special_id")} - {None}
        candidates = [item for item in owned if item["inv_id"] not in equipped]
        if profile["hoarder"] >= 50:
            non_specials = [item for item in candidates if item["item_type"] != "SPECIAL"]
            if non_specials:
                candidates = non_specials
            elif candidates:
                victim = min(candidates, key=lambda item: item["credit_cost"])
                result = enqueue_and_process(player["id"], "shop_sell", {"inv_id": victim["inv_id"]})
                return (f"Inventory was full; sold cheapest special {victim['name']}", str(result))
        if candidates:
            victim = min(candidates, key=lambda item: (item["score"], item["credit_cost"]))
            result = enqueue_and_process(player["id"], "shop_sell", {"inv_id": victim["inv_id"]})
            return (f"Inventory was full; sold obsolete {victim['name']}", str(result))
        return None

    # Near capacity, occasionally clear a duplicate weapon or armor that is
    # materially worse than the equipped one. This is deliberately infrequent
    # so the NPC does not burn all of its AP merely reorganizing inventory.
    if inv_count >= max(3, player["inventory_limit"] - 2) and random.random() < 0.20:
        equipped = {player.get("equipped_weapon_id"), player.get("equipped_armor_id"),
                    player.get("equipped_special_id")} - {None}
        obsolete = []
        for kind in ("WEAPON", "ARMOR"):
            category = [item for item in owned if item["item_type"] == kind]
            best_score = max((item["score"] for item in category), default=0)
            obsolete.extend(item for item in category
                            if item["inv_id"] not in equipped and item["score"] < best_score * 0.75)
        if obsolete:
            victim = min(obsolete, key=lambda item: (item["score"], item["credit_cost"]))
            result = enqueue_and_process(player["id"], "shop_sell", {"inv_id": victim["inv_id"]})
            return (f"Sold obsolete {victim['name']} to keep inventory useful", str(result))

    # Temperament creates stable differences between otherwise identical NPCs,
    # while the per-turn roll prevents a completely predictable schedule.
    temperament = random.Random(player["id"] * 65537).randint(-10, 10)
    shop_interest = max(profile["hoarder"], profile["boss_killer"] // 2,
                        profile["player_hunter"] // 2, profile["thief"] // 2)
    if random.randint(1, 100) > max(10, min(85, 15 + shop_interest // 2 + temperament)):
        return None

    # Preserve enough money for one heal and a modest repair reserve. More
    # self-preserving NPCs keep a larger cushion; hoarders accept more risk.
    heal_reserve = settings.get("TAVERN_HEAL_COST", cfg.TAVERN_HEAL_COST)
    reserve_pct = max(0.10, 0.35 + profile["self_preservation"] / 400
                      - profile["hoarder"] / 500)
    credit_reserve = max(heal_reserve, int(player["credits"] * reserve_pct))
    spendable = max(0, player["credits"] - credit_reserve)
    if spendable <= 0:
        return None

    current_scores = {kind: 0.0 for kind in ("WEAPON", "ARMOR", "SPECIAL")}
    equipped_ids = {"WEAPON": player.get("equipped_weapon_id"),
                    "ARMOR": player.get("equipped_armor_id"),
                    "SPECIAL": player.get("equipped_special_id")}
    for item in owned:
        if item["inv_id"] == equipped_ids[item["item_type"]]:
            current_scores[item["item_type"]] = item["score"]

    listings = execute("SELECT * FROM shop_listings ORDER BY id")
    upgrades = []
    owned_special_ids = {item["id"] for item in owned if item["item_type"] == "SPECIAL"}
    for listing in listings:
        detail = _load_item_detail(listing["item_type"], listing["item_id"])
        if not detail:
            continue
        price = _discounted_shop_price(player, listing["price"])
        if price > spendable:
            continue
        score = _score_item(listing["item_type"], detail, player, profile,
                            listing.get("durability_at_listing") or detail.get("starting_durability", 100))
        baseline = current_scores[listing["item_type"]]
        # Empty slots are always useful; otherwise require a real 10% upgrade.
        collectible = (listing["item_type"] == "SPECIAL" and profile["hoarder"] >= 50
                       and listing["item_id"] not in owned_special_ids)
        if baseline <= 0 or score >= baseline * 1.10 or collectible:
            value = (score - baseline) / max(1, price)
            if collectible:
                value += profile["hoarder"] / 25
            upgrades.append((value, score - baseline, -price, listing, detail))
    if not upgrades:
        return None
    _, improvement, _, listing, detail = max(upgrades, key=lambda row: row[:3])
    result = enqueue_and_process(player["id"], "shop_buy", {"listing_id": listing["id"]})
    _equip_best_items(player["id"], profile)
    return (f"Bought {detail['name']} as a meaningful {listing['item_type'].lower()} upgrade",
            f"estimated improvement {improvement:.1f}; {result}")


def _eligible_pvp_targets(player: dict) -> list[dict]:
    """Provide the internal eligible pvp targets operation used by this module."""
    return execute(
        """SELECT p.* FROM players p WHERE p.id != ? AND p.is_banned=0 AND p.in_combat=0
           AND p.level>=3 AND p.current_hp>1 AND (? - p.level)<=2""",
        (player["id"], player["level"])
    )


def _choose_pvp_target(player: dict, targets: list[dict], aggression: int) -> dict:
    """Choose using only eligibility and visible level information.

    NPCs must not exploit private credits, inventory, or exact HP values that a
    human challenger could not use when selecting an opponent.
    """
    if aggression >= 70:
        highest = max(p["level"] for p in targets)
        return random.choice([p for p in targets if p["level"] == highest])
    if aggression <= 30:
        lowest = min(p["level"] for p in targets)
        return random.choice([p for p in targets if p["level"] == lowest])
    nearest = min(abs(p["level"] - player["level"]) for p in targets)
    return random.choice([p for p in targets if abs(p["level"] - player["level"]) == nearest])


def _choose_boss(player: dict):
    """Provide the internal choose boss operation used by this module."""
    return execute_one(
        """SELECT b.* FROM bosses b LEFT JOIN boss_instances bi
           ON bi.boss_id=b.id AND bi.player_id=? WHERE b.is_active=1
           ORDER BY CASE WHEN COALESCE(bi.kill_count,0)=0 THEN 0 ELSE 1 END,
                    ABS(b.level-?) ASC, RANDOM() LIMIT 1""", (player["id"], player["level"])
    )


def _choose_combat_encounter(player: dict, settings: dict) -> tuple[str, dict | None]:
    """Roll and select a boss or minion using the human encounter rules."""
    minion_chance = max(0.0, min(1.0, settings.get(
        "MINION_ENCOUNTER_CHANCE", cfg.MINION_ENCOUNTER_CHANCE
    )))
    encounter_type = "MINION" if random.random() < minion_chance else "BOSS"
    singular = "minion" if encounter_type == "MINION" else "boss"
    table = "minions" if encounter_type == "MINION" else "bosses"
    instances = f"{singular}_instances"
    id_column = f"{singular}_id"

    discovered = execute(
        f"SELECT {id_column} FROM {instances} WHERE player_id=?",
        (player["id"],)
    )
    discovered_ids = [row[id_column] for row in discovered]
    if discovered_ids:
        placeholders = ",".join("?" for _ in discovered_ids)
        opponent = execute_one(
            f"SELECT * FROM {table} WHERE is_active=1 "
            f"AND id NOT IN ({placeholders}) ORDER BY RANDOM() LIMIT 1",
            tuple(discovered_ids)
        )
        if opponent:
            return encounter_type, opponent
    return encounter_type, execute_one(
        f"SELECT * FROM {table} WHERE is_active=1 ORDER BY RANDOM() LIMIT 1"
    )


def _roll_minion_interruption(player: dict, settings: dict) -> dict | None:
    """Return a minion when an NPC's attempted PvP action is interrupted."""
    chance = max(0.0, min(1.0, settings.get(
        "MINION_ENCOUNTER_CHANCE", cfg.MINION_ENCOUNTER_CHANCE
    )))
    if random.random() >= chance:
        return None
    discovered = execute(
        "SELECT minion_id FROM minion_instances WHERE player_id=?", (player["id"],)
    )
    ids = [row["minion_id"] for row in discovered]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        minion = execute_one(
            f"SELECT * FROM minions WHERE is_active=1 AND id NOT IN ({placeholders}) "
            "ORDER BY RANDOM() LIMIT 1", tuple(ids)
        )
        if minion:
            return minion
    return execute_one("SELECT * FROM minions WHERE is_active=1 ORDER BY RANDOM() LIMIT 1")


def _equip_best_items(player_id: int, profile: dict) -> list[str]:
    """Equip the best owned weapon, armor, and special for this NPC's build."""
    player = get_player(player_id)
    if not player:
        return []
    items = _load_scored_inventory(player, profile)
    fields = {"WEAPON": "equipped_weapon_id", "ARMOR": "equipped_armor_id",
              "SPECIAL": "equipped_special_id"}
    updates, changes = {}, []
    for item_type, field in fields.items():
        choices = [item for item in items if item["item_type"] == item_type]
        if not choices:
            continue
        best = max(choices, key=lambda item: (item["score"], item["current_durability"],
                                               item["credit_cost"]))
        if player.get(field) != best["inv_id"]:
            updates[field] = best["inv_id"]
            changes.append(f"{item_type.lower()}: {best['name']}")
    if updates:
        with exclusive_transaction():
            for field, inv_id in updates.items():
                execute_write(f"UPDATE players SET {field}=? WHERE id=?", (inv_id, player_id))
    return changes


def _load_scored_inventory(player: dict, profile: dict) -> list[dict]:
    """Return the NPC's inventory with public item data and build-aware scores."""
    result = []
    for inv in execute("SELECT * FROM inventory_items WHERE player_id=?", (player["id"],)):
        detail = _load_item_detail(inv["item_type"], inv["item_id"])
        if detail:
            result.append({**detail, "inv_id": inv["id"], "item_type": inv["item_type"],
                           "current_durability": inv["current_durability"],
                           "score": _score_item(inv["item_type"], detail, player, profile,
                                                inv["current_durability"])})
    return result


def _load_item_detail(item_type: str, item_id: int) -> dict | None:
    """Load one item definition using the same content tables as player screens."""
    table = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}.get(item_type)
    return execute_one(f"SELECT * FROM {table} WHERE id=?", (item_id,)) if table else None


def _stat_bonus_score(item: dict, weights: dict[str, float]) -> float:
    return sum(item.get(f"{stat}_bonus", 0) * weight for stat, weight in weights.items())


def _score_item(item_type: str, item: dict, player: dict, profile: dict,
                durability: int = 100) -> float:
    """Estimate practical value without hidden opponent information."""
    thief_led = profile["thief"] >= max(profile["player_hunter"], profile["boss_killer"],
                                         profile["hoarder"])
    weights = {"str": 1.2, "end": 1.2, "agi": 1.2, "lck": 1.0, "per": 1.0}
    if thief_led:
        weights.update({"agi": 2.0, "lck": 1.7, "per": 1.5})
    elif profile["boss_killer"] >= max(profile["player_hunter"], profile["hoarder"]):
        weights.update({"str": 1.8, "end": 1.7, "agi": 1.4})
    elif profile["player_hunter"] >= profile["hoarder"]:
        weights.update({"agi": 1.8, "per": 1.6, "str": 1.4})
    elif profile["hoarder"] > 0:
        weights.update({"lck": 1.7, "per": 1.6, "end": 1.4})
    stats = _stat_bonus_score(item, weights)
    condition = 0.55 + 0.45 * max(0, min(100, durability)) / 100
    resistances = sum(bool(item.get(f"res_{kind}")) for kind in
                      ("blade", "blunt", "ballistic", "energy", "arcane", "explosive", "venom"))
    if item_type == "WEAPON":
        die = str(item.get("damage_die", "d4")).lower().split("d")[-1]
        average = (int(die) + 1) / 2 if die.isdigit() else 2.5
        combat_stat = player["str_stat"] if item.get("weapon_type") == "Melee" else player["agi_stat"]
        return (average * 4 + math.floor(combat_stat / 2) * 2 + stats
                + item.get("level", 0) * 0.5) * condition
    if item_type == "ARMOR":
        return (item.get("ac_bonus", 0) * 5 + resistances * 3 + stats
                + item.get("level", 0) * 0.4) * condition
    economy = (item.get("shop_discount", 0) + item.get("sell_bonus", 0)
               + item.get("credit_multiplier", 0)) * (14 if profile["hoarder"] else 8)
    thief_value = item.get("steal_bonus", 0) * (18 if thief_led else 6)
    combat = (item.get("bonus_damage_amount", 0) * 3 + item.get("extra_attack", 0) * 10
              + item.get("ac_bonus", 0) * 5 + resistances * 3
              + item.get("initiative_bonus", 0) * 2
              + item.get("crit_chance_bonus", 0) * 20
              + item.get("crit_dmg_multiplier", 0) * 8)
    utility = (item.get("bonus_ap", 0) * 4 + item.get("hp_regen_bonus", 0) * 2
               + item.get("durability_reduction", 0) * 10
               + item.get("encounter_bonus", 0) * 8 + item.get("xp_multiplier", 0) * 10)
    return (combat + utility + economy + thief_value + stats + 1) * condition


def _discounted_shop_price(player: dict, listed_price: int) -> int:
    """Mirror the Shop's PER and equipped-special discount calculation."""
    settings = get_all_settings()
    discount = math.floor(player["per_stat"] / 2) / 100
    if player.get("equipped_special_id"):
        row = execute_one(
            """SELECT si.shop_discount FROM inventory_items ii JOIN special_items si ON si.id=ii.item_id
               WHERE ii.id=? AND ii.player_id=?""",
            (player["equipped_special_id"], player["id"])
        )
        discount += row["shop_discount"] if row else 0
    discount = min(discount, settings.get("SHOP_DISCOUNT_MAX", cfg.SHOP_DISCOUNT_MAX))
    return max(0, int(listed_price * (1 - discount)))


def _finish_turn(profile: dict, decision: str, reason: str, result) -> dict:
    """Provide the internal finish turn operation used by this module."""
    _assign_pending_levelup(profile["player_id"], profile)
    now = datetime.utcnow().isoformat()
    with exclusive_transaction():
        execute_write("UPDATE npc_profiles SET last_action_at=? WHERE player_id=?",
                      (now, profile["player_id"]))
    _log(profile["player_id"], decision, reason, str(result))
    return {"player_id": profile["player_id"], "decision": decision, "result": str(result)}


def _log(player_id: int, decision: str, reason: str, result: str):
    """Record NPC rationale in both specialist and per-character audit logs."""
    with exclusive_transaction():
        execute_write(
            "INSERT INTO npc_action_log(player_id,decision,reason,result) VALUES(?,?,?,?)",
            (player_id, decision, reason[:500], result[:1000])
        )
        execute_write(
            """INSERT INTO player_activity_log
               (player_id,category,action,status,message,details_json,source)
               VALUES(?, 'NPC', ?, 'SUCCESS', ?, ?, 'NPC')""",
            (player_id, decision, reason[:1000],
             json.dumps({"decision": decision, "reason": reason,
                         "result": result}, default=str)[:8000])
        )
