"""Independent three-actor combat for Cinematic Scenes.

This module intentionally does not call the existing combat action handlers or
write to their sessions/logs. It reuses only stateless dice and damage helpers
from ``combat.engine`` so Boss, Minion, PvP, and World Boss behavior cannot be
changed by scene development.
"""

import json
import random
from datetime import datetime

import config_defaults as cfg
from combat import engine
from combat.actions import apply_equipped_stat_bonuses
from database import (execute, execute_one, execute_write, exclusive_transaction, get_db,
                      get_all_settings, get_player, get_player_bonus_profile,
                      get_player_equipped)


FISTS = {"name": "Fists", "weapon_type": "Melee", "damage_die": "d4",
         "damage_type": "Blunt", "str_bonus": 0, "end_bonus": 0,
         "agi_bonus": 0, "lck_bonus": 0, "per_bonus": 0}
VALID_ACTIONS = {"ATTACK", "PROTECT", "ASSIST", "OBSERVE", "ESCAPE"}


def _content(table: str, item_id: int | None) -> dict | None:
    return execute_one(f"SELECT * FROM {table} WHERE id=?", (item_id,)) if item_id else None


def _special_profile(special: dict | None) -> dict:
    profile = dict(special or {})
    if special and special.get("bonus_damage_amount") and special.get("bonus_damage_type"):
        profile["bonus_damage_components"] = [{"amount": special["bonus_damage_amount"],
                                                "type": special["bonus_damage_type"]}]
    return profile


def _apply_item_stats(actor: dict, equipment: dict) -> dict:
    result = dict(actor)
    for stat in ("str", "end", "agi", "lck", "per"):
        result[f"{stat}_stat"] += sum(
            int((equipment.get(slot) or {}).get(f"{stat}_bonus", 0) or 0)
            for slot in ("weapon", "armor", "special")
        )
    result["special_ac_bonus"] = int((equipment.get("special") or {}).get("ac_bonus", 0) or 0)
    return result


def _player_snapshot(player_id: int) -> dict:
    player = get_player(player_id)
    equipment = get_player_equipped(player)
    actor = apply_equipped_stat_bonuses(player, {
        **equipment,
        "perk_bonuses": __import__("database").get_player_perk_bonuses(player_id),
        "bonuses": get_player_bonus_profile(player_id, equipment.get("special")),
    })
    return {"name": player["character_name"], "actor": actor,
            "weapon": equipment.get("weapon") or FISTS,
            "armor": equipment.get("armor"),
            "special": get_player_bonus_profile(player_id, equipment.get("special"))}


def _scene_cast(scene: dict) -> tuple[dict, dict]:
    master = execute_one("SELECT * FROM master WHERE movie_name=? AND is_active=1",
                         (scene["movie_name"],))
    if not master:
        raise ValueError("The scene's movie cast is not available.")
    prefix = "boss" if scene["enemy_type"] == "BOSS" else "minion"
    enemy_table = "bosses" if prefix == "boss" else "minions"
    enemy = _content(enemy_table, master[f"{prefix}_id"])
    if not enemy:
        raise ValueError("The scene enemy is no longer available.")
    enemy_equipment = {
        "weapon": _content("weapons", master[f"{prefix}_weapon_id"]) or FISTS,
        "armor": _content("armor", master[f"{prefix}_armor_id"]),
        "special": _content("special_items", master[f"{prefix}_special_item_id"]),
    }
    enemy_actor = _apply_item_stats(enemy, enemy_equipment)
    enemy_snapshot = {"name": enemy["name"], "kind": scene["enemy_type"],
                      "actor": enemy_actor, **enemy_equipment,
                      "special": _special_profile(enemy_equipment["special"]),
                      "content": enemy}

    # Protagonists do not have a separate stat sheet in Excel yet. Their level
    # tracks the scene enemy, while each core stat begins at 85% of the enemy's
    # authored value before protagonist equipment is applied.
    protagonist_equipment = {
        "weapon": _content("weapons", master.get("protagonist_weapon_id")) or FISTS,
        "armor": _content("armor", master.get("protagonist_armor_id")),
        "special": _content("special_items", master.get("protagonist_special_item_id")),
    }
    protagonist_actor = {"level": enemy["level"], "initiative_modifier": 0}
    for stat in ("str", "end", "agi", "lck", "per"):
        protagonist_actor[f"{stat}_stat"] = max(3, int(round(enemy[f"{stat}_stat"] * .85)))
    protagonist_actor = _apply_item_stats(protagonist_actor, protagonist_equipment)
    protagonist_snapshot = {
        "name": scene["protagonist_name"], "actor": protagonist_actor,
        **protagonist_equipment,
        "special": _special_profile(protagonist_equipment["special"]),
        "behavior": scene["protagonist_behavior"],
    }
    return protagonist_snapshot, enemy_snapshot


def begin_scene_combat(player_id: int, attempt_id: int) -> dict:
    """Create an isolated combat session from one failed scene challenge."""
    attempt = execute_one(
        """SELECT sa.*,s.* FROM scene_attempts sa JOIN scenes s ON s.id=sa.scene_id
           WHERE sa.id=? AND sa.player_id=?""", (attempt_id, player_id),
    )
    if not attempt or attempt["status"] != "COMBAT_PENDING":
        raise ValueError("This scene is not waiting for combat.")
    active = execute_one(
        "SELECT id FROM scene_combat_sessions WHERE player_id=? AND status='ACTIVE'", (player_id,)
    )
    if active:
        return scene_combat_state(active["id"], player_id)
    player = get_player(player_id)
    if player["in_combat"]:
        raise ValueError("Finish the existing combat before entering scene combat.")
    player_snapshot = _player_snapshot(player_id)
    protagonist, enemy = _scene_cast(attempt)
    player_max = int(player_snapshot["actor"]["max_hp"])
    protagonist_max = engine.calc_max_hp(protagonist["actor"])
    hp_scale = float(get_all_settings().get("SCENE_ENEMY_HP_SCALE", cfg.SCENE_ENEMY_HP_SCALE))
    enemy_max = max(1, int(enemy["content"]["max_hp"] * hp_scale))
    opening_damage = max(0, int(execute_one(
        "SELECT failure_value FROM scene_choices WHERE id=?", (attempt["choice_id"],)
    )["failure_value"] or 0))
    player_hp = max(1, min(player_max, player["current_hp"]) - opening_damage)
    # Scene choices use the game's established XP and credit rewards. Failed
    # checks may deal their authored opening damage, but do not invent a second
    # temporary buff/debuff system for cinematic combat.
    player_attack = protagonist_attack = enemy_penalty = player_guard = 0
    now = datetime.utcnow().isoformat()
    with exclusive_transaction():
        session_id = execute_write(
            """INSERT INTO scene_combat_sessions
               (attempt_id,player_id,player_hp,player_max_hp,protagonist_hp,
                protagonist_max_hp,enemy_hp,enemy_max_hp,player_guard,
                player_attack_bonus,protagonist_attack_bonus,enemy_attack_penalty,
                player_snapshot_json,protagonist_snapshot_json,enemy_snapshot_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (attempt_id, player_id, player_hp, player_max, protagonist_max,
             protagonist_max, enemy_max, enemy_max, player_guard, player_attack,
             protagonist_attack, enemy_penalty, json.dumps(player_snapshot, default=str),
             json.dumps(protagonist, default=str), json.dumps(enemy, default=str)),
        )
        execute_write("UPDATE players SET in_scene_combat=1,in_combat=1,current_hp=? WHERE id=?",
                      (player_hp, player_id))
        execute_write(
            "UPDATE scene_attempts SET status='SCENE_COMBAT_ACTIVE',scene_combat_session_id=?,resolved_at=NULL WHERE id=?",
            (session_id, attempt_id),
        )
    return scene_combat_state(session_id, player_id)


def scene_combat_state(session_id: int, player_id: int | None = None) -> dict:
    """Load one scene fight plus frozen cast and ordered round logs."""
    sql = """SELECT scs.*,sa.scene_id,s.scene_name,s.movie_name,s.setup_text,
             s.protagonist_ko_fails_scene,s.enemy_targeting,s.enemy_gear_reward_chance,
             s.protagonist_gear_reward_chance
             FROM scene_combat_sessions scs JOIN scene_attempts sa ON sa.id=scs.attempt_id
             JOIN scenes s ON s.id=sa.scene_id WHERE scs.id=?"""
    params = [session_id]
    if player_id is not None:
        sql += " AND scs.player_id=?"; params.append(player_id)
    row = execute_one(sql, tuple(params))
    if not row:
        raise ValueError("Scene combat not found.")
    row["player_snapshot"] = json.loads(row.pop("player_snapshot_json"))
    row["protagonist_snapshot"] = json.loads(row.pop("protagonist_snapshot_json"))
    row["enemy_snapshot"] = json.loads(row.pop("enemy_snapshot_json"))
    row["logs"] = execute(
        "SELECT * FROM scene_combat_logs WHERE scene_combat_session_id=? ORDER BY id", (session_id,)
    )
    return row


def _attack(attacker: dict, defender: dict, attack_bonus: int = 0,
            guard_bonus: int = 0, enemy_weakness: bool = False,
            damage_scale: float = 1.0) -> dict:
    """Resolve an isolated scene attack using the game's stateless formulas."""
    weapon = attacker.get("weapon") or FISTS
    special = attacker.get("special") or {}
    target_actor = defender["actor"]
    total, raw, modifier = engine.calc_attack_roll(attacker["actor"], weapon)
    total += int(attack_bonus)
    ac = engine.calc_ac(target_actor, defender.get("armor")) + int(guard_bonus)
    # Preserve the universal natural-d20 rule used by every live combat mode.
    hit = engine.hits_ac(total, ac, raw)
    detail = f"d20({raw})+{modifier}+{int(attack_bonus)}={total} vs AC {ac}"
    if not hit:
        return {"hit": False, "damage": 0, "roll": detail, "text": "MISS"}
    crit = raw >= engine.calc_crit_threshold(attacker["actor"], special)
    damage, damage_detail = engine.calc_weapon_damage(attacker["actor"], weapon, crit)
    damage, resistance = engine.resolve_resistance(
        damage, weapon["damage_type"], defender.get("armor"), defender.get("special"))
    weakness = ""
    if enemy_weakness:
        damage, weakness = engine.resolve_weakness(damage, weapon["damage_type"], defender.get("content"))
    bonus_total = 0
    for component in special.get("bonus_damage_components", []):
        amount = int(component.get("amount", 0) or 0) * (2 if crit else 1)
        if amount:
            amount, _ = engine.resolve_resistance(amount, component.get("type", ""),
                                                   defender.get("armor"), defender.get("special"))
            if enemy_weakness:
                amount, _ = engine.resolve_weakness(amount, component.get("type", ""),
                                                    defender.get("content"))
            bonus_total += amount
    if crit and special.get("crit_dmg_multiplier"):
        multiplier = 1 + float(special.get("crit_dmg_multiplier", 0) or 0)
        damage = int(damage * multiplier)
        bonus_total = int(bonus_total * multiplier)
    damage = max(1, int((damage + bonus_total) * max(0.0, damage_scale)))
    notes = "; ".join(filter(None, [resistance, weakness]))
    return {"hit": True, "damage": damage, "roll": detail,
            "text": f"{'CRITICAL · ' if crit else ''}{damage_detail}; {damage} total damage{(' · '+notes) if notes else ''}"}


def _log(session: dict, sequence: int, actor: str, action: str, target: str,
         result: dict, player_hp: int, protagonist_hp: int, enemy_hp: int):
    execute_write(
        """INSERT INTO scene_combat_logs
           (scene_combat_session_id,round_number,sequence_number,actor,action,target,
            roll_detail,outcome_detail,damage,player_hp,protagonist_hp,enemy_hp)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (session["id"], session["round_number"], sequence, actor, action, target,
         result.get("roll", ""), result.get("text", ""), result.get("damage", 0),
         player_hp, protagonist_hp, enemy_hp),
    )


def take_scene_combat_turn(player_id: int, session_id: int, action: str,
                           expected_version: int | None = None) -> dict:
    """Resolve one complete three-part round in initiative order."""
    action = action.upper()
    if action not in VALID_ACTIONS:
        raise ValueError("Unknown scene-combat action.")
    state = scene_combat_state(session_id, player_id)
    if state["status"] != "ACTIVE":
        raise ValueError("This scene combat has already ended.")
    if expected_version is not None and int(expected_version) != state["version"]:
        raise ValueError("That scene round was already resolved. The display has been refreshed.")
    # Claim this exact displayed state before rolling. A rapid double-click can
    # therefore resolve at most one round; the duplicate sees a stale version.
    with exclusive_transaction():
        changed = get_db().execute(
            """UPDATE scene_combat_sessions SET version=version+1
               WHERE id=? AND player_id=? AND status='ACTIVE' AND version=?""",
            (session_id, player_id, state["version"]),
        ).rowcount
        if changed != 1:
            raise ValueError("That scene round was already resolved. The display has been refreshed.")
    player = state["player_snapshot"]; protagonist = state["protagonist_snapshot"]
    enemy = state["enemy_snapshot"]
    initiatives = [
        (engine.calc_initiative(
            player["actor"], (player.get("special") or {}).get("initiative_bonus", 0)
        )[0], "PLAYER"),
        (engine.calc_initiative(
            protagonist["actor"], (protagonist.get("special") or {}).get("initiative_bonus", 0)
        )[0], "PROTAGONIST"),
        (engine.calc_initiative(
            enemy["actor"], (enemy.get("special") or {}).get("initiative_bonus", 0)
        )[0], "ENEMY"),
    ]
    initiatives.sort(reverse=True)
    php, ahp, ehp = state["player_hp"], state["protagonist_hp"], state["enemy_hp"]
    pth, ath = state["player_threat"], state["protagonist_threat"]
    pguard, aguard = state["player_guard"], state["protagonist_guard"]
    pab, aab, enemy_penalty = state["player_attack_bonus"], state["protagonist_attack_bonus"], state["enemy_attack_penalty"]
    sequence = 0
    round_logs = []
    settings = get_all_settings()
    enemy_scale = float(settings.get("SCENE_ENEMY_DAMAGE_SCALE", cfg.SCENE_ENEMY_DAMAGE_SCALE))
    for _, actor_name in initiatives:
        if ehp <= 0 or php <= 1 or (ahp <= 0 and state["protagonist_ko_fails_scene"]):
            break
        sequence += 1
        if actor_name == "PLAYER":
            if action == "ATTACK":
                result = _attack(player, enemy, pab, enemy_weakness=True)
                ehp = max(0, ehp - result["damage"]); pth += max(1, result["damage"]); pab = max(0, pab - 1)
            elif action == "PROTECT":
                pguard = max(pguard, 3); aguard = 1; pth += 6
                result = {"damage": 0, "roll": "", "text": "You draw the enemy's attention and guard your ally."}
            elif action == "ASSIST":
                heal = max(1, engine.roll(4) + engine.stat_mod(player["actor"]["per_stat"]))
                old = ahp; ahp = min(state["protagonist_max_hp"], ahp + heal); aab = max(aab, 2); pth += 1
                result = {"damage": 0, "roll": f"Support restored {ahp-old} HP",
                          "text": f"You rally {protagonist['name']} and create an opening."}
            elif action == "OBSERVE":
                raw = engine.roll(20); total = raw + engine.stat_mod(player["actor"]["per_stat"])
                dc = 10 + engine.stat_mod(enemy["actor"]["per_stat"]); success = total >= dc
                if success: pab = min(4, pab + 2)
                result = {"damage": 0, "roll": f"d20({raw})+PER={total} vs {dc}",
                          "text": "You expose a repeatable weakness. Attack bonus gained." if success else "The enemy conceals its pattern."}
            else:
                raw = engine.roll(20); total = raw + engine.stat_mod(player["actor"]["agi_stat"]) + engine.stat_mod(player["actor"]["lck_stat"])
                dc = 10 + engine.stat_mod(enemy["actor"]["agi_stat"]) + engine.stat_mod(enemy["actor"]["lck_stat"])
                result = {"damage": 0, "roll": f"Escape {total} vs {dc}",
                          "text": "You withdraw from the scene." if total >= dc else "The enemy cuts off your escape."}
                if total >= dc:
                    with exclusive_transaction():
                        _log(state, sequence, "PLAYER", action, "SELF", result, php, ahp, ehp)
                        execute_write("""UPDATE scene_combat_sessions SET player_hp=?,protagonist_hp=?,enemy_hp=?,updated_at=? WHERE id=?""",
                                      (php, ahp, ehp, datetime.utcnow().isoformat(), session_id))
                    return finalize_scene_combat(session_id, "WITHDRAWN")
            target = "ENEMY" if action in ("ATTACK", "OBSERVE", "ESCAPE") else ("PROTAGONIST" if action == "ASSIST" else "TEAM")
        elif actor_name == "PROTAGONIST":
            if ahp <= 0: continue
            result = _attack(protagonist, enemy, aab, enemy_weakness=True)
            ehp = max(0, ehp - result["damage"]); ath += max(1, result["damage"]); aab = max(0, aab - 1); target = "ENEMY"
        else:
            if state["enemy_snapshot"]["kind"] == "BOSS" and not state["enemy_special_used"] and random.random() < .20:
                target_player = ahp <= 0 or random.random() < (pth / max(1, pth + ath))
                target_data = player if target_player else protagonist
                raw_damage = engine.roll_damage_die(enemy["content"]["special_attack_die"])
                damage, note = engine.resolve_resistance(raw_damage, enemy["content"]["special_attack_damage_type"], target_data.get("armor"), target_data.get("special"))
                damage = max(1, int(damage * enemy_scale)); result = {"damage": damage, "roll": enemy["content"]["special_attack_die"], "text": f"{enemy['content']['special_attack_name']}: {enemy['content']['special_attack_flavor']} · {damage} damage {note}"}
                state["enemy_special_used"] = 1
            else:
                target_player = ahp <= 0 or random.random() < (pth / max(1, pth + ath))
                target_data = player if target_player else protagonist
                guard = pguard if target_player else 0
                result = _attack(enemy, target_data, -enemy_penalty, guard_bonus=guard, damage_scale=enemy_scale)
            if target_player:
                php = max(1, php - result["damage"]); target = "PLAYER"; pguard = 0
            else:
                damage = result["damage"] // 2 if aguard else result["damage"]
                result["damage"] = damage; ahp = max(0, ahp - damage); target = "PROTAGONIST"; aguard = 0
        round_logs.append((sequence, actor_name, action if actor_name == "PLAYER" else "ATTACK", target, result, php, ahp, ehp))
    next_round = state["round_number"] + 1
    with exclusive_transaction():
        execute_write(
            """UPDATE scene_combat_sessions SET player_hp=?,protagonist_hp=?,enemy_hp=?,
               player_threat=?,protagonist_threat=?,player_guard=?,protagonist_guard=?,
               player_attack_bonus=?,protagonist_attack_bonus=?,enemy_attack_penalty=?,
               enemy_special_used=?,player_damage_dealt=player_damage_dealt+?,
               protagonist_damage_dealt=protagonist_damage_dealt+?,enemy_damage_dealt=enemy_damage_dealt+?,
               round_number=?,updated_at=? WHERE id=?""",
            (php, ahp, ehp, pth, ath, pguard, aguard, pab, aab, enemy_penalty,
             state["enemy_special_used"],
             sum(x[4]["damage"] for x in round_logs if x[1] == "PLAYER"),
             sum(x[4]["damage"] for x in round_logs if x[1] == "PROTAGONIST"),
             sum(x[4]["damage"] for x in round_logs if x[1] == "ENEMY"),
             next_round, datetime.utcnow().isoformat(), session_id),
        )
        for entry in round_logs: _log(state, *entry)
        execute_write("UPDATE players SET current_hp=? WHERE id=?", (php, player_id))
    if ehp <= 0: return finalize_scene_combat(session_id, "VICTORY")
    if php <= 1 or (ahp <= 0 and state["protagonist_ko_fails_scene"]):
        return finalize_scene_combat(session_id, "DEFEAT")
    hard_cap = int(settings.get("SCENE_COMBAT_MAX_ROUNDS", cfg.SCENE_COMBAT_MAX_ROUNDS))
    if next_round > hard_cap:
        team_pct = ((php / state["player_max_hp"]) + (ahp / state["protagonist_max_hp"])) / 2
        enemy_pct = ehp / state["enemy_max_hp"]
        return finalize_scene_combat(session_id, "VICTORY" if team_pct > enemy_pct else "DEFEAT")
    return scene_combat_state(session_id, player_id)


def _grant_item(player_id: int, item_type: str, item_id: int | None,
                acquired_method: str) -> str | None:
    """Grant one scene item without calling ordinary combat-drop handlers."""
    if not item_id: return None
    table = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}[item_type]
    item = _content(table, item_id)
    if not item: return None
    if item_type != "SPECIAL" and execute_one(
        "SELECT id FROM inventory_items WHERE player_id=? AND item_type=? AND item_id=?",
        (player_id, item_type, item_id)):
        return None
    if item_type == "SPECIAL":
        registry = execute_one("SELECT * FROM special_item_registry WHERE special_item_id=?", (item_id,))
        if not registry or registry["status"] != "IN_POOL": return None
    inv_id = execute_write(
        """INSERT INTO inventory_items(player_id,item_type,item_id,current_durability,acquired_method)
           VALUES(?,?,?,?,?)""", (player_id, item_type, item_id,
                                  item.get("starting_durability", 100), acquired_method))
    if item_type == "SPECIAL":
        execute_write(
            """UPDATE special_item_registry SET status='IN_INVENTORY',current_owner_player_id=?,
               inventory_item_id=?,last_acquired_method=?,updated_at=? WHERE special_item_id=?""",
            (player_id, inv_id, acquired_method, datetime.utcnow().isoformat(), item_id))
    execute_write(
        "INSERT INTO item_history(player_id,item_type,item_id,item_name,event_type) VALUES(?,?,?,?,?)",
        (player_id, item_type, item_id, item["name"], "RECEIVED_SCENE_REWARD"))
    return item["name"]


def _scene_rewards(state: dict) -> list[str]:
    scene = execute_one("SELECT * FROM scenes WHERE id=?", (state["scene_id"],))
    master = execute_one("SELECT * FROM master WHERE movie_name=?", (state["movie_name"],))
    rewards = []
    for prefix, chance, method in (
        (("boss" if state["enemy_snapshot"]["kind"] == "BOSS" else "minion"),
         float(scene["enemy_gear_reward_chance"]), "SCENE_ENEMY_REWARD"),
        ("protagonist", float(scene["protagonist_gear_reward_chance"]), "SCENE_PROTAGONIST_REWARD"),
    ):
        if random.random() >= chance: continue
        slots = [("WEAPON", master.get(f"{prefix}_weapon_id")),
                 ("ARMOR", master.get(f"{prefix}_armor_id")),
                 ("SPECIAL", master.get(f"{prefix}_special_item_id"))]
        random.shuffle(slots)
        for item_type, item_id in slots:
            name = _grant_item(state["player_id"], item_type, item_id, method)
            if name: rewards.append(name); break
    return rewards


def finalize_scene_combat(session_id: int, result: str) -> dict:
    """Finalize only scene tables, player HP, rewards, feeds, and audit history."""
    state = scene_combat_state(session_id)
    if state["status"] != "ACTIVE": return state
    now = datetime.utcnow().isoformat(); victory = result == "VICTORY"
    rewards = []
    with exclusive_transaction():
        if victory: rewards = _scene_rewards(state)
        execute_write("UPDATE scene_combat_sessions SET status='RESOLVED',result=?,resolved_at=?,updated_at=? WHERE id=? AND status='ACTIVE'",
                      (result, now, now, session_id))
        attempt_status = {"VICTORY": "SCENE_COMPLETED", "DEFEAT": "SCENE_FAILED",
                          "WITHDRAWN": "WITHDRAWN"}.get(result, "SCENE_FAILED")
        execute_write("UPDATE scene_attempts SET status=?,resolved_at=? WHERE id=?",
                      (attempt_status, now, state["attempt_id"]))
        execute_write("UPDATE players SET in_scene_combat=0,in_combat=0,current_hp=? WHERE id=?",
                      (max(1, state["player_hp"]), state["player_id"]))
        message = (f"Completed {state['scene_name']} with {state['protagonist_snapshot']['name']}."
                   if victory else f"{state['scene_name']} ended in {result.lower()}.")
        if rewards: message += " Recovered: " + ", ".join(rewards) + "."
        execute_write("INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category) VALUES('PERSONAL',?,?,'SCENE_COMBAT')",
                      (state["player_id"], message))
        execute_write("""INSERT INTO player_activity_log(player_id,category,action,status,message,details_json,source)
                         VALUES(?,'SCENE','scene_combat',?,?,?,'GAME')""",
                      (state["player_id"], "SUCCESS" if victory else "FAILED", message,
                       json.dumps({"session_id": session_id, "result": result, "rewards": rewards})))
    final = scene_combat_state(session_id)
    final["rewards"] = rewards
    return final


def recover_scene_combat(player_id: int | None = None) -> dict:
    """Clear impossible or duplicate scene sessions without touching normal combat."""
    params = () if player_id is None else (player_id,)
    where = "" if player_id is None else "WHERE player_id=?"
    sessions = execute(f"SELECT * FROM scene_combat_sessions {where} ORDER BY id DESC", params)
    active_seen = set(); abandoned = []
    with exclusive_transaction():
        for row in sessions:
            if row["status"] != "ACTIVE": continue
            player = execute_one("SELECT id,retired_at,is_banned FROM players WHERE id=?", (row["player_id"],))
            attempt = execute_one("SELECT status FROM scene_attempts WHERE id=?", (row["attempt_id"],))
            broken = (not player or player["retired_at"] or player["is_banned"] or not attempt or
                      attempt["status"] != "SCENE_COMBAT_ACTIVE" or row["player_id"] in active_seen)
            if broken:
                execute_write("UPDATE scene_combat_sessions SET status='ABANDONED',result='RECOVERED',resolved_at=? WHERE id=?",
                              (datetime.utcnow().isoformat(), row["id"]))
                if player:
                    execute_write(
                        """UPDATE players SET in_scene_combat=0,
                           in_combat=CASE WHEN EXISTS(
                             SELECT 1 FROM combat_sessions cs WHERE cs.status='ACTIVE'
                             AND (cs.attacker_player_id=players.id OR cs.defender_player_id=players.id)
                           ) THEN 1 ELSE 0 END WHERE id=?""", (row["player_id"],)
                    )
                abandoned.append(row["id"])
            else: active_seen.add(row["player_id"])
        for pid in active_seen:
            execute_write("UPDATE players SET in_scene_combat=1,in_combat=1 WHERE id=?", (pid,))
        if player_id is None:
            execute_write(
                """UPDATE players SET in_scene_combat=0,
                   in_combat=CASE WHEN EXISTS(
                     SELECT 1 FROM combat_sessions cs WHERE cs.status='ACTIVE'
                     AND (cs.attacker_player_id=players.id OR cs.defender_player_id=players.id)
                   ) THEN 1 ELSE 0 END
                   WHERE id NOT IN (SELECT player_id FROM scene_combat_sessions WHERE status='ACTIVE')"""
            )
    return {"active": len(active_seen), "abandoned": abandoned}
