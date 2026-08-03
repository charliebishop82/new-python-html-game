"""Automated player-character decisions using the normal queued action handlers."""

import logging
import math
import random
import hashlib
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

    _equip_best_core_items(player_id)
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

    hoard_result = _maybe_hoard(player, profile)
    if hoard_result:
        return _finish_turn(profile, "HOARD", hoard_result[0], hoard_result[1])

    pvp_targets = _eligible_pvp_targets(player)
    if profile["thief"] >= max(profile["player_hunter"], profile["boss_killer"],
                                profile["hoarder"]):
        last_mode = execute_one(
            """SELECT decision FROM npc_action_log WHERE player_id=?
               AND decision IN ('PVP_STEAL','BOSS') ORDER BY id DESC LIMIT 1""",
            (player_id,)
        )
        steal_turn = not last_mode or last_mode["decision"] == "BOSS"
        if steal_turn and pvp_targets:
            target = random.choice(pvp_targets)
            result = enqueue_and_process(
                player_id, "start_pvp_fight",
                {"target_id": target["id"], "cost_ap": settings.get("AP_COST_PVP", cfg.AP_COST_PVP)}
            )
            if result.get("error"):
                return _finish_turn(profile, "PVP_STEAL", "Random eligible target selected", result["error"])
            combat = _finish_thief_combat(player_id, result["session_id"])
            return _finish_turn(profile, "PVP_STEAL", f"Attempted theft from {target['character_name']}", combat)
        # Alternate with a boss fight for XP. If PvP was unavailable, boss is
        # also the normal fallback under the existing eligibility rules.
        opponent = _choose_boss(player)
        if opponent:
            result = enqueue_and_process(
                player_id, "start_boss_fight",
                {"opponent_id": opponent["id"], "encounter_type": "BOSS",
                 "cost_ap": settings.get("AP_COST_BOSS", cfg.AP_COST_BOSS)}
            )
            if not result.get("error"):
                combat = _finish_active_combat(player_id, result["session_id"], profile)
                return _finish_turn(profile, "BOSS", f"Alternated to boss {opponent['name']} for XP", combat)
            return _finish_turn(profile, "BOSS", "Thief's XP-building turn", result["error"])

    pvp_score = profile["player_hunter"] + random.randint(-10, 10)
    boss_score = profile["boss_killer"] + random.randint(-10, 10)
    if not pvp_targets:
        boss_score += profile["player_hunter"]  # hunter fallback

    if pvp_targets and pvp_score >= boss_score:
        target = _choose_pvp_target(player, pvp_targets, profile["aggression"])
        result = enqueue_and_process(
            player_id, "start_pvp_fight",
            {"target_id": target["id"], "cost_ap": settings.get("AP_COST_PVP", cfg.AP_COST_PVP)}
        )
        if result.get("error"):
            return _finish_turn(profile, "PVP", "Highest motivation was player hunting", result["error"])
        combat = _finish_active_combat(player_id, result["session_id"], profile)
        return _finish_turn(profile, "PVP", f"Targeted {target['character_name']}", combat)

    opponent = _choose_boss(player)
    if opponent:
        result = enqueue_and_process(
            player_id, "start_boss_fight",
            {"opponent_id": opponent["id"], "encounter_type": "BOSS",
             "cost_ap": settings.get("AP_COST_BOSS", cfg.AP_COST_BOSS)}
        )
        if not result.get("error"):
            combat = _finish_active_combat(player_id, result["session_id"], profile)
            return _finish_turn(profile, "BOSS", f"Hunted {opponent['name']}", combat)
        return _finish_turn(profile, "BOSS", "Boss hunt selected", result["error"])

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
    return f"Combat {session_id} remains active after safety limit"


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
    """Provide the internal maybe repair operation used by this module."""
    if random.randint(1, 100) > profile["repair_tendency"]:
        return None
    threshold = 40 + profile["repair_tendency"] // 2
    equipped = [player.get("equipped_weapon_id"), player.get("equipped_armor_id")]
    damaged = execute(
        "SELECT id,current_durability FROM inventory_items WHERE player_id=? AND id IN (?,?)",
        (player["id"], equipped[0] or -1, equipped[1] or -1)
    )
    if not any(item["current_durability"] < threshold for item in damaged):
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


def _maybe_hoard(player: dict, profile: dict):
    """Provide the internal maybe hoard operation used by this module."""
    if profile["hoarder"] <= 0:
        return None
    inv_count = execute_one("SELECT COUNT(*) cnt FROM inventory_items WHERE player_id=?", (player["id"],))["cnt"]
    if inv_count >= player["inventory_limit"]:
        cheapest = execute_one(
            """SELECT ii.id FROM inventory_items ii JOIN special_items si ON si.id=ii.item_id
               WHERE ii.player_id=? AND ii.item_type='SPECIAL' AND ii.id != COALESCE(?, -1)
               ORDER BY si.credit_cost ASC LIMIT 1""", (player["id"], player.get("equipped_special_id"))
        )
        if cheapest:
            result = enqueue_and_process(player["id"], "shop_sell", {"inv_id": cheapest["id"]})
            return ("Inventory was full; sold the cheapest unequipped special", str(result))
    listing = execute_one(
        """SELECT sl.id FROM shop_listings sl WHERE sl.item_type='SPECIAL' AND sl.price<=?
           ORDER BY sl.price ASC LIMIT 1""", (player["credits"],)
    )
    if listing and random.randint(1, 100) <= profile["hoarder"]:
        result = enqueue_and_process(player["id"], "shop_buy", {"listing_id": listing["id"]})
        return ("An affordable special item was available", str(result))
    return None


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


def _equip_best_core_items(player_id: int):
    """Provide the internal equip best core items operation used by this module."""
    updates = {}
    for item_type, table, field in (("WEAPON", "weapons", "equipped_weapon_id"),
                                    ("ARMOR", "armor", "equipped_armor_id")):
        item = execute_one(
            f"""SELECT ii.id FROM inventory_items ii JOIN {table} c ON c.id=ii.item_id
                WHERE ii.player_id=? AND ii.item_type=?
                ORDER BY c.level DESC,c.credit_cost DESC,ii.current_durability DESC LIMIT 1""",
            (player_id, item_type)
        )
        if item:
            updates[field] = item["id"]
    if updates:
        with exclusive_transaction():
            execute_write(
                "UPDATE players SET equipped_weapon_id=COALESCE(?,equipped_weapon_id),"
                "equipped_armor_id=COALESCE(?,equipped_armor_id) WHERE id=?",
                (updates.get("equipped_weapon_id"), updates.get("equipped_armor_id"), player_id)
            )


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
    """Provide the internal log operation used by this module."""
    with exclusive_transaction():
        execute_write(
            "INSERT INTO npc_action_log(player_id,decision,reason,result) VALUES(?,?,?,?)",
            (player_id, decision, reason[:500], result[:1000])
        )
