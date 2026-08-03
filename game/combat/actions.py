# combat/actions.py
# Per-action handlers for all 6 combat actions plus opponent automation.
# Each handler resolves the action, writes to DB, and returns a result dict.
# All DB writes happen inside exclusive_transaction() via queue_handler.

import math
import random
import logging
from datetime import datetime

from database import (execute, execute_one, execute_write,
                      exclusive_transaction, get_all_settings)
from combat import engine
from combat import flavour
import config_defaults as cfg

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# COMBAT STATE LOADER
# ─────────────────────────────────────────────────────────────────────────────

def get_combat_state(session_id: int) -> dict:
    """Load the full combat state for a given session.
    Returns dict with session, attacker, defender/boss/minion, equipped gear,
    active combat_buffs, and derived values."""
    session = execute_one(
        "SELECT * FROM combat_sessions WHERE id = ?", (session_id,)
    )
    if session is None:
        raise ValueError(f"Combat session {session_id} not found.")

    attacker = execute_one(
        "SELECT * FROM players WHERE id = ?", (session["attacker_player_id"],)
    )
    attacker_equipped = _load_equipped(attacker)

    # Load defender (player, boss, or minion)
    defender = defender_equipped = boss = minion = None

    if session["combat_type"] == "PVP":
        defender = execute_one(
            "SELECT * FROM players WHERE id = ?", (session["defender_player_id"],)
        )
        defender_equipped = _load_equipped(defender)

    elif session["combat_type"] == "BOSS":
        instance = execute_one(
            "SELECT * FROM boss_instances WHERE id = ?", (session["boss_instance_id"],)
        )
        boss = execute_one("SELECT * FROM bosses WHERE id = ?", (instance["boss_id"],))
        boss = {**boss,
                "current_hp":          instance["current_hp"],
                "special_attack_used": instance["special_attack_used"],
                "special_buff_used":   instance["special_buff_used"],
                "current_phase":       instance["current_phase"],
                "instance_id":         instance["id"]}

    elif session["combat_type"] == "MINION":
        instance = execute_one(
            "SELECT * FROM minion_instances WHERE id = ?", (session["minion_instance_id"],)
        )
        minion = execute_one("SELECT * FROM minions WHERE id = ?", (instance["minion_id"],))
        minion = {**minion,
                  "current_hp": instance["current_hp"],
                  "instance_id": instance["id"]}

    # Active combat buffs
    buffs = execute(
        "SELECT * FROM combat_buffs WHERE combat_session_id = ?", (session_id,)
    )
    attacker_buffs = [b for b in buffs if b["side"] == "ATTACKER"]
    defender_buffs = [b for b in buffs if b["side"] == "DEFENDER"]

    return {
        "session":            session,
        "attacker":           attacker,
        "attacker_equipped":  attacker_equipped,
        "defender":           defender,
        "defender_equipped":  defender_equipped,
        "boss":               boss,
        "minion":             minion,
        "attacker_buffs":     attacker_buffs,
        "defender_buffs":     defender_buffs,
    }


def _load_equipped(player: dict) -> dict:
    """Load weapon, armor, and special item rows for a player."""
    result = {"weapon": None, "armor": None, "special": None}
    if player is None:
        return result
    for slot, col, table in [
        ("weapon",  "equipped_weapon_id",  "weapons"),
        ("armor",   "equipped_armor_id",   "armor"),
        ("special", "equipped_special_id", "special_items"),
    ]:
        inv_id = player.get(col)
        if inv_id:
            inv = execute_one("SELECT * FROM inventory_items WHERE id = ?", (inv_id,))
            if inv:
                item = execute_one(f"SELECT * FROM {table} WHERE id = ?", (inv["item_id"],))
                if item:
                    result[slot] = {**item, "inv_id": inv_id,
                                    "current_durability": inv["current_durability"]}
    return result


def check_combat_end(state: dict) -> tuple[bool, str | None]:
    """Check if the fight should end. Returns (ended, winner_side).
    winner_side: 'ATTACKER', 'DEFENDER', or None."""
    session = state["session"]

    if session["combat_type"] == "PVP":
        # Check current HP from DB (may have changed mid-round)
        att = execute_one(
            "SELECT current_hp FROM players WHERE id = ?",
            (session["attacker_player_id"],)
        )
        dfn = execute_one(
            "SELECT current_hp FROM players WHERE id = ?",
            (session["defender_player_id"],)
        )
        if att["current_hp"] <= 1:
            return True, "DEFENDER"
        if dfn["current_hp"] <= 1:
            return True, "ATTACKER"

    elif session["combat_type"] in ("BOSS", "MINION"):
        table = "boss_instances" if session["combat_type"] == "BOSS" else "minion_instances"
        id_col = "boss_instance_id" if session["combat_type"] == "BOSS" else "minion_instance_id"
        inst = execute_one(
            f"SELECT current_hp FROM {table} WHERE id = ?", (session[id_col],)
        )
        if inst["current_hp"] <= 0:
            return True, "ATTACKER"
        # Player floor: 1 HP
        att = execute_one(
            "SELECT current_hp FROM players WHERE id = ?",
            (session["attacker_player_id"],)
        )
        if att["current_hp"] <= 1:
            return True, "DEFENDER"  # Boss/minion wins

    return False, None


# ─────────────────────────────────────────────────────────────────────────────
# ACTION: ATTACK
# ─────────────────────────────────────────────────────────────────────────────

def handle_attack(session_id: int, actor_side: str, state: dict) -> dict:
    """Resolve a full attack from one side.
    actor_side: 'ATTACKER' or 'DEFENDER'"""
    session = state["session"]
    is_attacker = actor_side == "ATTACKER"

    attacker    = state["attacker"] if is_attacker else state["defender"]
    defender    = state["defender"] if is_attacker else state["attacker"]
    att_eq      = state["attacker_equipped"] if is_attacker else state["defender_equipped"]
    def_eq      = state["defender_equipped"] if is_attacker else state["attacker_equipped"]
    att_buffs   = state["attacker_buffs"] if is_attacker else state["defender_buffs"]
    def_buffs   = state["defender_buffs"] if is_attacker else state["attacker_buffs"]
    boss        = state["boss"] if session["combat_type"] == "BOSS" else None
    minion      = state["minion"] if session["combat_type"] == "MINION" else None
    opponent    = boss or minion or defender

    weapon  = att_eq.get("weapon")
    armor   = def_eq.get("armor") if def_eq else None
    special = att_eq.get("special")
    def_special = def_eq.get("special") if def_eq else None

    if weapon is None:
        # Unarmed: d4 Blunt, no stat bonus weapon
        weapon = {"weapon_type": "Melee", "damage_die": "d4",
                  "damage_type": "Blunt", "name": "Fists",
                  "str_bonus": 0, "credit_cost": 0}

    # Brace dodge bonus for defender
    brace_dodge = sum(
        int(b["value"]) for b in def_buffs
        if b["buff_type"] == "BRACE_DODGE_BONUS"
    )

    result = engine.resolve_full_attack(
        attacker=attacker,
        defender=opponent,
        attacker_weapon=weapon,
        attacker_special=special,
        defender_armor=armor,
        defender_special=def_special,
        boss=boss,
        brace_dodge_bonus=brace_dodge,
        active_buffs=def_buffs,
        is_player_attacker=is_attacker,
    )

    # Extra attack (special item)
    extra_attack_result = None
    if special and special.get("extra_attack") and result["hit"]:
        extra_attack_result = engine.resolve_full_attack(
            attacker=attacker,
            defender=opponent,
            attacker_weapon=weapon,
            attacker_special=special,
            defender_armor=armor,
            defender_special=def_special,
            boss=boss,
            brace_dodge_bonus=brace_dodge,
            active_buffs=def_buffs,
            is_player_attacker=is_attacker,
        )

    # --- Write to DB ---
    with exclusive_transaction():
        damage_total = result["damage_total"]
        if extra_attack_result:
            damage_total += extra_attack_result["damage_total"]

        # Update HP
        if session["combat_type"] == "PVP":
            target_id = session["defender_player_id"] if is_attacker else session["attacker_player_id"]
            if is_attacker:
                current = execute_one("SELECT current_hp FROM players WHERE id = ?", (target_id,))
                new_hp  = max(1, current["current_hp"] - damage_total)  # PvP floor: 1 HP
            else:
                current = execute_one("SELECT current_hp FROM players WHERE id = ?", (target_id,))
                new_hp  = max(1, current["current_hp"] - damage_total)
            execute_write("UPDATE players SET current_hp = ? WHERE id = ?", (new_hp, target_id))
        else:
            # Boss or minion HP: floor 0
            inst_id  = (session["boss_instance_id"] if session["combat_type"] == "BOSS"
                        else session["minion_instance_id"])
            tbl      = "boss_instances" if session["combat_type"] == "BOSS" else "minion_instances"
            current  = execute_one(f"SELECT current_hp FROM {tbl} WHERE id = ?", (inst_id,))
            new_hp   = max(0, current["current_hp"] - damage_total)
            execute_write(f"UPDATE {tbl} SET current_hp = ? WHERE id = ?", (new_hp, inst_id))

        # Update damage totals on session
        if is_attacker:
            execute_write(
                "UPDATE combat_sessions SET attacker_total_damage_dealt = attacker_total_damage_dealt + ? WHERE id = ?",
                (damage_total, session_id)
            )
        else:
            execute_write(
                "UPDATE combat_sessions SET defender_total_damage_dealt = defender_total_damage_dealt + ? WHERE id = ?",
                (damage_total, session_id)
            )

        # Weapon durability (attacker)
        if result["hit"] and att_eq.get("weapon"):
            _apply_durability_loss(att_eq["weapon"]["inv_id"],
                                   result["weapon_durability_loss"],
                                   session["attacker_player_id"])
            if extra_attack_result and extra_attack_result["hit"]:
                _apply_durability_loss(att_eq["weapon"]["inv_id"],
                                       extra_attack_result["weapon_durability_loss"],
                                       session["attacker_player_id"])

        # Armor durability (defender — only for PvP)
        if result["hit"] and session["combat_type"] == "PVP" and def_eq and def_eq.get("armor"):
            def_player_id = (session["defender_player_id"] if is_attacker
                             else session["attacker_player_id"])
            _apply_durability_loss(def_eq["armor"]["inv_id"],
                                   result["armor_durability_loss"],
                                   def_player_id)

        # Expire BRACE buffs after defender is hit
        if result["hit"] or result["dodged"] is False:
            execute_write(
                """DELETE FROM combat_buffs
                   WHERE combat_session_id = ? AND side = ? AND expires_on = 'NEXT_HIT_RESOLVED'""",
                (session_id, "ATTACKER" if not is_attacker else "DEFENDER")
            )

        # Write combat log
        execute_write(
            """INSERT INTO combat_logs
               (combat_session_id, round_number, actor, action_type, roll_detail, outcome_detail,
                hp_after_attacker, hp_after_defender)
               VALUES (?, ?, ?, 'ATTACK', ?, ?, ?, ?)""",
            (session_id, session["current_round"], actor_side,
             result["roll_detail"], result["outcome_detail"],
             None, None)  # HP values filled in by caller
        )

    # Build flavor text
    weapon_name = weapon.get("name", "weapon")
    flavor = flavour.attack_flavor(
        attacker_name=attacker.get("character_name", "Attacker"),
        weapon_name=weapon_name,
        weapon_type=weapon.get("weapon_type", "Melee"),
        hit=result["hit"],
        dodged=result["dodged"],
        is_crit=result["is_crit"],
        damage=damage_total,
        damage_type=weapon.get("damage_type", "Blunt"),
        res_note=result["damage_breakdown"][0]["note"] if result["damage_breakdown"] else ""
    )

    return {
        "action":         "ATTACK",
        "hit":            result["hit"],
        "dodged":         result["dodged"],
        "damage_total":   damage_total,
        "is_crit":        result["is_crit"],
        "new_target_hp":  new_hp,
        "roll_detail":    result["roll_detail"],
        "flavor":         flavor,
        "extra_attack":   extra_attack_result is not None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ACTION: STEAL
# ─────────────────────────────────────────────────────────────────────────────

def handle_steal(session_id: int, player_id: int, state: dict) -> dict:
    """Resolve a steal attempt by either PvP side using that actor's stats."""
    session  = state["session"]
    settings = get_all_settings()
    is_defender = (session["combat_type"] == "PVP" and
                   player_id == session["defender_player_id"])
    actor = state["defender"] if is_defender else state["attacker"]
    actor_side = "DEFENDER" if is_defender else "ATTACKER"
    actor_equipped = state["defender_equipped"] if is_defender else state["attacker_equipped"]

    special     = actor_equipped.get("special")
    steal_bonus = special.get("steal_bonus", 0.0) if special else 0.0

    if session["combat_type"] == "PVP":
        defender = state["attacker"] if is_defender else state["defender"]
        roll_result = engine.resolve_opposed_roll(
            actor_agi=actor["agi_stat"],
            actor_lck=actor["lck_stat"],
            defender_agi=defender["agi_stat"],
            defender_lck=defender["lck_stat"],
            steal_bonus_pct=steal_bonus,
            tie_goes_to="defender"
        )
        if not roll_result["success"]:
            _apply_steal_fail_penalty(session_id, actor_side)
            return {"action": "STEAL", "success": False,
                    "roll_detail": roll_result["detail"],
                    "flavor": flavour.steal_flavor(
                        actor["character_name"], defender["character_name"], False)}

        # Cascade: item → credits → XP
        result = _pvp_steal_cascade(player_id, defender["id"],
                                    steal_bonus, settings)
        _write_combat_log(session_id, session["current_round"], actor_side,
                          "STEAL", roll_result["detail"], str(result))
        return {"action": "STEAL", "success": True,
                "roll_detail": roll_result["detail"],
                "flavor": flavour.steal_flavor(
                    actor["character_name"], defender["character_name"], True,
                    item_name=result.get("item_name", ""),
                    credits=result.get("credits", 0),
                    xp_bonus=result.get("xp_bonus", 0))}

    else:
        # vs boss or minion
        opponent = state["boss"] or state["minion"]
        opp_agi  = opponent["agi_stat"]
        opp_lck  = opponent["lck_stat"]
        roll_result = engine.resolve_opposed_roll(
            actor_agi=actor["agi_stat"],
            actor_lck=actor["lck_stat"],
            defender_agi=opp_agi,
            defender_lck=opp_lck,
            steal_bonus_pct=steal_bonus,
            tie_goes_to="defender"
        )
        if not roll_result["success"]:
            _apply_steal_fail_penalty(session_id, "ATTACKER")
            return {"action": "STEAL", "success": False,
                    "roll_detail": roll_result["detail"],
                    "flavor": flavour.steal_flavor(
                        actor["character_name"], opponent["name"], False,
                        is_vs_boss=True)}

        result = _boss_steal_result(player_id, opponent, steal_bonus, settings,
                                    session["combat_type"])
        _write_combat_log(session_id, session["current_round"], "ATTACKER",
                          "STEAL", roll_result["detail"], str(result))
        return {"action": "STEAL", "success": True,
                "roll_detail": roll_result["detail"],
                "flavor": flavour.steal_flavor(
                    actor["character_name"], opponent["name"], True,
                    item_name=result.get("item_name", ""),
                    credits=result.get("credits", 0),
                    is_vs_boss=True)}


def _pvp_steal_cascade(attacker_id: int, defender_id: int,
                       steal_bonus: float, settings: dict) -> dict:
    steal_cr_pct  = settings.get("STEAL_ACTION_CREDIT_PERCENT", cfg.STEAL_ACTION_CREDIT_PERCENT)
    zero_xp_bonus = settings.get("ZERO_CREDIT_XP_BONUS",        cfg.ZERO_CREDIT_XP_BONUS)

    # Step 1: try to steal a random unequipped item
    defender = execute_one("SELECT * FROM players WHERE id = ?", (defender_id,))
    equipped  = {defender.get("equipped_weapon_id"),
                 defender.get("equipped_armor_id"),
                 defender.get("equipped_special_id")} - {None}
    inv_items = execute(
        "SELECT * FROM inventory_items WHERE player_id = ?", (defender_id,)
    )
    stealable = [i for i in inv_items if i["id"] not in equipped]

    if stealable:
        target_inv = random.choice(stealable)
        # Transfer to attacker
        with exclusive_transaction():
            execute_write(
                "UPDATE inventory_items SET player_id = ?, acquired_method = 'PVP_STEAL' WHERE id = ?",
                (attacker_id, target_inv["id"])
            )
            item_detail = execute_one(
                f"SELECT name FROM {'weapons' if target_inv['item_type']=='WEAPON' else 'armor' if target_inv['item_type']=='ARMOR' else 'special_items'} WHERE id = ?",
                (target_inv["item_id"],)
            )
            item_name = item_detail["name"] if item_detail else "item"
            execute_write(
                """INSERT INTO item_history (player_id, item_type, item_id, item_name, event_type, related_player_id)
                   VALUES (?, ?, ?, ?, 'STOLEN_BY_ME', ?)""",
                (attacker_id, target_inv["item_type"], target_inv["item_id"], item_name, defender_id)
            )
            execute_write(
                """INSERT INTO item_history (player_id, item_type, item_id, item_name, event_type, related_player_id)
                   VALUES (?, ?, ?, ?, 'STOLEN_FROM_ME', ?)""",
                (defender_id, target_inv["item_type"], target_inv["item_id"], item_name, attacker_id)
            )
        return {"item_name": item_name, "credits": 0, "xp_bonus": 0}

    # Step 2: try to steal credits
    if defender["credits"] > 0:
        steal_pct = steal_cr_pct + steal_bonus
        amount    = max(0, int(defender["credits"] * steal_pct))
        if amount > 0:
            with exclusive_transaction():
                execute_write("UPDATE players SET credits = credits - ? WHERE id = ?",
                              (amount, defender_id))
                execute_write("UPDATE players SET credits = credits + ? WHERE id = ?",
                              (amount, attacker_id))
            return {"credits": amount, "xp_bonus": 0}

    # Step 3: nothing left — XP consolation
    with exclusive_transaction():
        execute_write("UPDATE players SET xp = xp + ? WHERE id = ?",
                      (zero_xp_bonus, attacker_id))
    return {"xp_bonus": zero_xp_bonus}


def _boss_steal_result(player_id, opponent, steal_bonus, settings, combat_type):
    import random, math
    from datetime import datetime

    base_chance   = settings.get("STEAL_SPECIAL_BASE_CHANCE", cfg.STEAL_SPECIAL_BASE_CHANCE)
    cr_multiplier = settings.get("STEAL_BOSS_CREDIT_MULTIPLIER", cfg.STEAL_BOSS_CREDIT_MULTIPLIER)
    player        = execute_one("SELECT lck_stat FROM players WHERE id = ?", (player_id,))
    lck_bonus     = math.floor(player["lck_stat"] / 2) / 100

    # Try special item first
    if random.random() < (base_chance + lck_bonus):
        association_type = "Boss" if combat_type == "BOSS" else "Minion"
        special_def = execute_one(
            """SELECT si.id, si.name, si.starting_durability
               FROM special_items si
               JOIN special_item_registry sir ON sir.special_item_id = si.id
               WHERE si.associated_to = ? AND si.association_type = ?
                 AND sir.status = 'IN_POOL'""",
            (opponent["name"], association_type)
        )
        if special_def:
            with exclusive_transaction():
                inv_id = execute_write(
                    """INSERT INTO inventory_items
                       (player_id, item_type, item_id, current_durability, acquired_method)
                       VALUES (?, 'SPECIAL', ?, ?, 'COMBAT_STEAL')""",
                    (player_id, special_def["id"], special_def.get("starting_durability", 100))
                )
                execute_write(
                    """UPDATE special_item_registry
                       SET status='IN_INVENTORY', current_owner_player_id=?,
                           inventory_item_id=?, last_acquired_method='COMBAT_STEAL', updated_at=?
                       WHERE special_item_id=?""",
                    (player_id, inv_id, datetime.utcnow().isoformat(), special_def["id"])
                )
                execute_write(
                    """INSERT INTO item_history
                       (player_id, item_type, item_id, item_name, event_type)
                       VALUES (?, 'SPECIAL', ?, ?, 'RECEIVED_COMBAT_STEAL')""",
                    (player_id, special_def["id"], special_def["name"])
                )
            return {"item_name": special_def["name"]}

    # Minion only: try to steal the minion weapon
    if combat_type == "MINION":
        master = execute_one(
            """SELECT m.minion_weapon_id, w.name as weapon_name, w.starting_durability
               FROM master m
               JOIN minions mn ON mn.id = m.minion_id
               JOIN weapons w  ON w.id  = m.minion_weapon_id
               WHERE mn.name = ?""",
            (opponent["name"],)
        )
        if master and master["minion_weapon_id"]:
            already_owned = execute_one(
                "SELECT id FROM inventory_items WHERE player_id = ? AND item_type = 'WEAPON' AND item_id = ?",
                (player_id, master["minion_weapon_id"])
            )
            if not already_owned:
                with exclusive_transaction():
                    execute_write(
                        """INSERT INTO inventory_items
                           (player_id, item_type, item_id, current_durability, acquired_method)
                           VALUES (?, 'WEAPON', ?, ?, 'COMBAT_STEAL')""",
                        (player_id, master["minion_weapon_id"], master.get("starting_durability", 100))
                    )
                    execute_write(
                        """INSERT INTO item_history
                           (player_id, item_type, item_id, item_name, event_type)
                           VALUES (?, 'WEAPON', ?, ?, 'RECEIVED_COMBAT_STEAL')""",
                        (player_id, master["minion_weapon_id"], master["weapon_name"])
                    )
                return {"item_name": master["weapon_name"]}

    # Credits fallback
    credits_stolen = int(opponent["level"] * (cr_multiplier + steal_bonus * cr_multiplier))
    with exclusive_transaction():
        execute_write("UPDATE players SET credits = credits + ? WHERE id = ?",
                      (credits_stolen, player_id))
    return {"credits": credits_stolen}

def handle_brace(session_id: int, player_id: int, state: dict) -> dict:
    session  = state["session"]
    attacker = state["attacker"]
    settings = get_all_settings()
    heal_pct    = settings.get("BRACE_HEAL_PERCENT",      cfg.BRACE_HEAL_PERCENT)
    ac_pct      = settings.get("BRACE_AC_BONUS_PERCENT",  cfg.BRACE_AC_BONUS_PERCENT)
    dodge_bonus = settings.get("BRACE_DODGE_BONUS",       cfg.BRACE_DODGE_BONUS)

    armor    = state["attacker_equipped"].get("armor")
    current_ac = engine.calc_ac(attacker, armor)
    ac_bonus   = int(current_ac * ac_pct)

    max_hp   = engine.calc_max_hp(attacker)
    missing  = max_hp - attacker["current_hp"]
    heal     = max(0, int(missing * heal_pct))
    new_hp   = min(attacker["current_hp"] + heal, max_hp)

    with exclusive_transaction():
        execute_write("UPDATE players SET current_hp = ? WHERE id = ?", (new_hp, player_id))
        execute_write(
            """INSERT INTO combat_buffs
               (combat_session_id, side, buff_type, value, expires_on)
               VALUES (?, 'ATTACKER', 'BRACE_AC_BONUS', ?, 'NEXT_HIT_RESOLVED')""",
            (session_id, ac_bonus)
        )
        execute_write(
            """INSERT INTO combat_buffs
               (combat_session_id, side, buff_type, value, expires_on)
               VALUES (?, 'ATTACKER', 'BRACE_DODGE_BONUS', ?, 'NEXT_HIT_RESOLVED')""",
            (session_id, dodge_bonus)
        )
        # Armor durability loss on Brace
        if armor:
            _apply_durability_loss(armor["inv_id"], 1, player_id)
        _write_combat_log(session_id, session["current_round"], "ATTACKER",
                          "BRACE", "Brace action",
                          f"Healed {heal} HP, AC+{ac_bonus}, Dodge+{dodge_bonus}")

    flv = flavour.brace_flavor(attacker["character_name"], heal, ac_bonus, dodge_bonus)
    return {"action": "BRACE", "new_hp": new_hp, "ac_bonus": ac_bonus,
            "dodge_bonus": dodge_bonus, "heal": heal, "flavor": flv}


# ─────────────────────────────────────────────────────────────────────────────
# ACTION: ESCAPE
# ─────────────────────────────────────────────────────────────────────────────

def handle_escape(session_id: int, player_id: int, state: dict) -> dict:
    session  = state["session"]
    attacker = state["attacker"]
    settings = get_all_settings()
    ap_cost  = settings.get("AP_COST_ESCAPE", cfg.AP_COST_ESCAPE)
    cr_drop  = settings.get("ESCAPE_CREDIT_DROP_CHANCE", cfg.ESCAPE_CREDIT_DROP_CHANCE)

    if attacker["current_ap"] < ap_cost:
        raise ValueError(f"Not enough AP to attempt escape (need {ap_cost}).")

    # Determine opponent stats for roll
    if session["combat_type"] == "PVP":
        opp = state["defender"]
        opp_agi, opp_lck = opp["agi_stat"], opp["lck_stat"]
    else:
        opp = state["boss"] or state["minion"]
        opp_agi, opp_lck = opp["agi_stat"], opp["lck_stat"]

    roll_result = engine.resolve_opposed_roll(
        actor_agi=attacker["agi_stat"],
        actor_lck=attacker["lck_stat"],
        defender_agi=opp_agi,
        defender_lck=opp_lck,
        tie_goes_to="defender"
    )

    credits_lost = 0
    with exclusive_transaction():
        execute_write(
            "UPDATE players SET current_ap = current_ap - ? WHERE id = ?",
            (ap_cost, player_id)
        )
        if roll_result["success"]:
            # Escape: cancel session
            execute_write(
                "UPDATE combat_sessions SET status='RESOLVED', result='ESCAPE', resolved_at=? WHERE id=?",
                (datetime.utcnow().isoformat(), session_id)
            )
            execute_write(
                "UPDATE players SET in_combat = 0 WHERE id = ?", (player_id,)
            )
            if session["combat_type"] == "PVP":
                execute_write(
                    "UPDATE players SET in_combat = 0 WHERE id = ?",
                    (session["defender_player_id"],)
                )
            # Reset boss/minion HP on escape
            if session["combat_type"] == "BOSS":
                boss = state["boss"]
                execute_write(
                    "UPDATE boss_instances SET current_hp=?, special_attack_used=0, special_buff_used=0, current_phase=1 WHERE id=?",
                    (boss["max_hp"], boss["instance_id"])
                )
            elif session["combat_type"] == "MINION":
                minion = state["minion"]
                execute_write(
                    "UPDATE minion_instances SET current_hp=? WHERE id=?",
                    (minion["max_hp"], minion["instance_id"])
                )
            # PvP credit drop
            if session["combat_type"] == "PVP" and random.random() < cr_drop:
                player_row = execute_one("SELECT credits FROM players WHERE id=?", (player_id,))
                if player_row["credits"] > 0:
                    credits_lost = max(1, int(player_row["credits"] * 0.05))
                    execute_write(
                        "UPDATE players SET credits = credits - ? WHERE id = ?",
                        (credits_lost, player_id)
                    )
                    execute_write(
                        "UPDATE players SET credits = credits + ? WHERE id = ?",
                        (credits_lost, session["defender_player_id"])
                    )
            # Delete combat buffs
            execute_write("DELETE FROM combat_buffs WHERE combat_session_id = ?", (session_id,))
        else:
            # Fail: AC penalty
            execute_write(
                """INSERT INTO combat_buffs
                   (combat_session_id, side, buff_type, value, expires_on)
                   VALUES (?, 'ATTACKER', 'ESCAPE_FAIL_AC_PENALTY', 3, 'NEXT_HIT_RESOLVED')""",
                (session_id,)
            )
        _write_combat_log(session_id, session["current_round"], "ATTACKER",
                          "ESCAPE", roll_result["detail"],
                          f"{'Escaped' if roll_result['success'] else 'Failed'}, credits lost: {credits_lost}")

    flv = flavour.escape_flavor(attacker["character_name"],
                                roll_result["success"], credits_lost)
    return {"action": "ESCAPE", "success": roll_result["success"],
            "credits_lost": credits_lost, "roll_detail": roll_result["detail"],
            "flavor": flv, "escaped": roll_result["success"]}


# ─────────────────────────────────────────────────────────────────────────────
# ACTION: OBSERVE
# ─────────────────────────────────────────────────────────────────────────────

def handle_observe(session_id: int, player_id: int, state: dict) -> dict:
    session  = state["session"]
    attacker = state["attacker"]

    if session["combat_type"] == "PVP":
        opp = state["defender"]
        opp_per, opp_agi, opp_lck = opp["per_stat"], opp["agi_stat"], opp["lck_stat"]
    else:
        opp = state["boss"] or state["minion"]
        opp_per, opp_agi, opp_lck = opp.get("per_stat", 0), opp["agi_stat"], opp["lck_stat"]

    roll_result = engine.resolve_opposed_roll(
        actor_agi=attacker["agi_stat"], actor_lck=attacker["lck_stat"],
        defender_agi=opp_agi, defender_lck=opp_lck,
        actor_per=attacker["per_stat"], defender_per=opp_per,
        tie_goes_to="defender"
    )

    revealed = {}
    with exclusive_transaction():
        if roll_result["success"]:
            execute_write(
                "UPDATE combat_sessions SET attacker_observed = 1 WHERE id = ?",
                (session_id,)
            )
            if session["combat_type"] == "BOSS":
                boss = state["boss"]
                resistances = [t for t in engine.DAMAGE_TYPES if boss.get(f"res_{t}")]
                weaknesses  = [t for t in engine.DAMAGE_TYPES if boss.get(f"weak_{t}")]
                revealed = {
                    "resistances": resistances,
                    "weaknesses":  weaknesses,
                    "exact_hp":    boss["current_hp"],
                }
                # Save to boss_intel permanently
                execute_write(
                    """INSERT OR IGNORE INTO boss_intel (player_id, boss_id)
                       SELECT ?, boss_id FROM boss_instances WHERE id = ?""",
                    (player_id, session["boss_instance_id"])
                )
            elif session["combat_type"] == "MINION":
                revealed = {"exact_hp": (state["minion"] or {}).get("current_hp")}
            else:
                # PvP: reveal equipped gear
                def_eq = state["defender_equipped"]
                revealed = {
                    "weapon": def_eq["weapon"]["name"] if def_eq.get("weapon") else None,
                    "armor":  def_eq["armor"]["name"]  if def_eq.get("armor")  else None,
                }
        _write_combat_log(session_id, session["current_round"], "ATTACKER",
                          "OBSERVE", roll_result["detail"], str(revealed))

    flv = flavour.observe_flavor(
        attacker["character_name"], roll_result["success"],
        opp.get("character_name") or opp.get("name", "opponent"), revealed
    )
    return {"action": "OBSERVE", "success": roll_result["success"],
            "revealed": revealed, "roll_detail": roll_result["detail"], "flavor": flv}


# ─────────────────────────────────────────────────────────────────────────────
# ACTION: SWAP GEAR
# ─────────────────────────────────────────────────────────────────────────────

def handle_swap_gear(session_id: int, player_id: int, state: dict,
                     new_weapon_inv_id: int | None = None,
                     new_armor_inv_id:  int | None = None,
                     new_special_inv_id: int | None = None) -> dict:
    session  = state["session"]
    attacker = state["attacker"]
    settings = get_all_settings()
    acc_pen  = settings.get("SWAP_GEAR_ACCURACY_PENALTY", cfg.SWAP_GEAR_ACCURACY_PENALTY)
    ac_pen   = settings.get("SWAP_GEAR_AC_PENALTY",       cfg.SWAP_GEAR_AC_PENALTY)

    current_ac = engine.calc_ac(attacker, state["attacker_equipped"].get("armor"))
    ac_penalty = int(current_ac * ac_pen)

    with exclusive_transaction():
        if new_weapon_inv_id:
            execute_write(
                "UPDATE players SET equipped_weapon_id = ? WHERE id = ?",
                (new_weapon_inv_id, player_id)
            )
        if new_armor_inv_id:
            execute_write(
                "UPDATE players SET equipped_armor_id = ? WHERE id = ?",
                (new_armor_inv_id, player_id)
            )
        if new_special_inv_id:
            execute_write(
                "UPDATE players SET equipped_special_id = ? WHERE id = ?",
                (new_special_inv_id, player_id)
            )
        execute_write(
            """INSERT INTO combat_buffs
               (combat_session_id, side, buff_type, value, expires_on)
               VALUES (?, 'ATTACKER', 'SWAP_GEAR_ACCURACY_PENALTY', ?, 'END_OF_ROUND')""",
            (session_id, int(acc_pen * 100))
        )
        execute_write(
            """INSERT INTO combat_buffs
               (combat_session_id, side, buff_type, value, expires_on)
               VALUES (?, 'ATTACKER', 'SWAP_GEAR_AC_PENALTY', ?, 'END_OF_ROUND')""",
            (session_id, ac_penalty)
        )
        new_item = execute_one(
            """SELECT name FROM weapons WHERE id = (
               SELECT item_id FROM inventory_items WHERE id = ?)""",
            (new_weapon_inv_id,)
        ) if new_weapon_inv_id else None
        new_item_name = new_item["name"] if new_item else "new gear"
        _write_combat_log(session_id, session["current_round"], "ATTACKER",
                          "SWAP_GEAR", "Swap gear action",
                          f"Swapped to {new_item_name}, penalties applied this round")

    flv = flavour.swap_gear_flavor(attacker["character_name"], new_item_name)
    return {"action": "SWAP_GEAR", "flavor": flv,
            "accuracy_penalty_pct": int(acc_pen * 100), "ac_penalty": ac_penalty}


# ─────────────────────────────────────────────────────────────────────────────
# OPPONENT AUTOMATION
# ─────────────────────────────────────────────────────────────────────────────

def handle_opponent_action(session_id: int, state: dict) -> dict:
    """Automated opponent action for PvP defender (offline) or boss."""
    session = state["session"]

    if session["combat_type"] == "PVP":
        return _pvp_defender_action(session_id, state)
    else:
        return _boss_action(session_id, state)


def _pvp_defender_action(session_id: int, state: dict) -> dict:
    """PvP defending player uses their combat preference."""
    settings  = get_all_settings()
    defender  = state["defender"]
    pref      = defender.get("combat_preference", "Balanced")
    balanced  = settings.get("COMBAT_PREF_BALANCED_SPLIT",   cfg.COMBAT_PREF_BALANCED_SPLIT)
    opportunist = settings.get("COMBAT_PREF_OPPORTUNIST_SPLIT", cfg.COMBAT_PREF_OPPORTUNIST_SPLIT)

    if pref == "Aggressive":
        action = "ATTACK"
    elif pref == "Defensive":
        action = "BRACE"
    elif pref == "Opportunist":
        action = "STEAL" if random.random() < opportunist else "ATTACK"
    else:  # Balanced
        action = "BRACE" if random.random() < balanced else "ATTACK"

    # Resolve the chosen action from DEFENDER perspective
    if action == "ATTACK":
        return handle_attack(session_id, "DEFENDER", state)
    elif action == "BRACE":
        return handle_brace(session_id, state["session"]["defender_player_id"], state)
    else:
        return handle_steal(session_id, state["session"]["defender_player_id"], state)


def _boss_action(session_id: int, state: dict) -> dict:
    """Boss chooses and executes its action for this round.
    Checks phase thresholds first, updates phase if needed,
    then scales behavior to current phase."""
    boss    = state["boss"]
    session = state["session"]

    # ── Phase check ───────────────────────────────────────────────────────────
    max_hp        = boss["max_hp"]
    current_hp    = boss["current_hp"]
    hp_pct        = (current_hp / max_hp * 100) if max_hp else 100
    phase2_thresh = boss.get("phase2_hp_percent", 50)
    phase3_thresh = boss.get("phase3_hp_percent", 25)
    current_phase = boss.get("current_phase", 1)

    new_phase = current_phase
    if hp_pct <= phase3_thresh:
        new_phase = 3
    elif hp_pct <= phase2_thresh:
        new_phase = 2

    # Persist phase change and handle transition effects
    if new_phase != current_phase:
        with exclusive_transaction():
            # On entering phase 3: reset special move flags (can use again)
            if new_phase == 3:
                execute_write(
                    """UPDATE boss_instances
                       SET current_phase = 3,
                           special_attack_used = 0,
                           special_buff_used = 0
                       WHERE id = ?""",
                    (boss["instance_id"],)
                )
                flavor_text = (
                    f"{boss['name'].upper()} ENTERS PHASE 3 — "
                    f"desperate, enraged, and more dangerous than ever!"
                )
            else:
                execute_write(
                    "UPDATE boss_instances SET current_phase = ? WHERE id = ?",
                    (new_phase, boss["instance_id"])
                )
                flavor_text = (
                    f"{boss['name'].upper()} ENTERS PHASE 2 — "
                    f"wounded and furious, its attacks grow more deliberate."
                )
            # Personal feed entry for the phase transition
            execute_write(
                """INSERT INTO daily_feed
                   (feed_scope, player_id, flavor_text, event_category)
                   VALUES ('PERSONAL', ?, ?, 'COMBAT')""",
                (session["attacker_player_id"], flavor_text)
            )
        # Refresh boss state after update
        boss["current_phase"]       = new_phase
        boss["special_attack_used"] = 0 if new_phase == 3 else boss["special_attack_used"]
        boss["special_buff_used"]   = 0 if new_phase == 3 else boss["special_buff_used"]
        current_phase = new_phase

    # ── Choose action based on phase ──────────────────────────────────────────
    s_atk_used = boss["special_attack_used"]
    s_buf_used = boss["special_buff_used"]

    if current_phase == 1:
        # Phase 1: 33/33/33 split
        r = random.random()
        if   r < 0.333 and not s_atk_used: chosen = "SPECIAL_ATTACK"
        elif r < 0.666 and not s_buf_used:  chosen = "SPECIAL_BUFF"
        else:                                chosen = "ATTACK"

    elif current_phase == 2:
        # Phase 2: specials first if available, else attack
        if not s_atk_used and not s_buf_used:
            chosen = "SPECIAL_ATTACK" if random.random() < 0.5 else "SPECIAL_BUFF"
        elif not s_atk_used:
            chosen = "SPECIAL_ATTACK"
        elif not s_buf_used:
            chosen = "SPECIAL_BUFF"
        else:
            chosen = "ATTACK"

    else:
        # Phase 3: specials reset — same as phase 2 but with extra attack
        # (extra attack handled in combat round handler, see routes/combat.py patch)
        if not s_atk_used and not s_buf_used:
            chosen = "SPECIAL_ATTACK" if random.random() < 0.5 else "SPECIAL_BUFF"
        elif not s_atk_used:
            chosen = "SPECIAL_ATTACK"
        elif not s_buf_used:
            chosen = "SPECIAL_BUFF"
        else:
            chosen = "ATTACK"

    # ── Execute chosen action ─────────────────────────────────────────────────
    if chosen == "SPECIAL_ATTACK" and not s_atk_used:
        primary = _boss_special_attack(session_id, state)
    elif chosen == "SPECIAL_BUFF" and not s_buf_used:
        primary = _boss_special_buff(session_id, state)
    else:
        primary = _boss_regular_attack(session_id, state, current_phase)

    primary["boss_phase"] = current_phase
    primary["phase_changed"] = new_phase != (boss.get("current_phase", 1) if new_phase == current_phase else current_phase - 1)

    # Phase 3 extra attack — always attacks again after any action
    if current_phase == 3:
        # Reload state (HP may have changed)
        state2 = get_combat_state(session_id)
        if state2["session"]["status"] == "ACTIVE":
            extra = _boss_regular_attack(session_id, state2, current_phase)
            extra["is_extra_attack"] = True
            primary["extra_attack_result"] = extra

    return primary

def _boss_special_attack(session_id: int, state: dict) -> dict:
    boss    = state["boss"]
    session = state["session"]
    player  = state["attacker"]
    att_eq  = state["attacker_equipped"]

    die_sides = int(boss["special_attack_die"].lstrip("d"))
    raw_dmg   = sum(engine.roll(die_sides) for _ in range(2))  # 2 dice for special

    final_dmg, res_note = engine.resolve_resistance(
        raw_dmg, boss["special_attack_damage_type"],
        att_eq.get("armor"), att_eq.get("special")
    )
    new_hp = max(1, player["current_hp"] - final_dmg)

    with exclusive_transaction():
        execute_write("UPDATE players SET current_hp = ? WHERE id = ?",
                      (new_hp, session["attacker_player_id"]))
        execute_write(
            "UPDATE combat_sessions SET defender_total_damage_dealt = defender_total_damage_dealt + ? WHERE id = ?",
            (final_dmg, session_id)
        )
        instance_id = boss["instance_id"]
        execute_write(
            "UPDATE boss_instances SET special_attack_used = 1 WHERE id = ?", (instance_id,)
        )
        _write_combat_log(session_id, session["current_round"], "DEFENDER",
                          "SPECIAL_ATTACK", f"Special: {boss['special_attack_name']}",
                          f"{final_dmg} {boss['special_attack_damage_type']} damage")

    flv = flavour.boss_special_attack_flavor(
        boss["name"], boss["special_attack_name"], final_dmg, boss["special_attack_flavor"]
    )
    return {"action": "SPECIAL_ATTACK", "damage_total": final_dmg,
            "new_player_hp": new_hp, "flavor": flv}


def _boss_special_buff(session_id: int, state: dict) -> dict:
    boss    = state["boss"]
    session = state["session"]
    buff_type  = boss["special_buff_type"]
    buff_value = boss["special_buff_value"]

    expires_on = "END_OF_COMBAT"

    with exclusive_transaction():
        if buff_type == "HP_RESTORE":
            restore = int(boss["max_hp"] * buff_value)
            inst_id = boss["instance_id"]
            execute_write(
                "UPDATE boss_instances SET current_hp = MIN(current_hp + ?, ?) WHERE id = ?",
                (restore, boss["max_hp"], inst_id)
            )
        else:
            execute_write(
                """INSERT INTO combat_buffs
                   (combat_session_id, side, buff_type, damage_type, value, expires_on)
                   VALUES (?, 'DEFENDER', ?, ?, ?, ?)""",
                (session_id, f"BOSS_{buff_type}", boss.get("special_buff_damage_type"),
                 buff_value, expires_on)
            )
        instance_id = boss["instance_id"]
        execute_write(
            "UPDATE boss_instances SET special_buff_used = 1 WHERE id = ?", (instance_id,)
        )
        _write_combat_log(session_id, session["current_round"], "DEFENDER",
                          "SPECIAL_BUFF", f"Special buff: {boss['special_buff_name']}",
                          f"Type: {buff_type}, Value: {buff_value}")

    flv = flavour.boss_special_buff_flavor(
        boss["name"], boss["special_buff_name"], boss["special_buff_flavor"]
    )
    return {"action": "SPECIAL_BUFF", "buff_type": buff_type,
            "buff_value": buff_value, "flavor": flv}


def _get_boss_weapon(boss: dict) -> dict:
    """Load the boss's weapon from master table."""
    master = execute_one("SELECT boss_weapon_id FROM master WHERE boss_id = ?", (boss["id"],))
    if master:
        weapon = execute_one("SELECT * FROM weapons WHERE id = ?", (master["boss_weapon_id"],))
        if weapon:
            return weapon
    return {"weapon_type": "Melee", "damage_die": "d8", "damage_type": "Blunt",
            "name": "Attack", "str_bonus": 0}


# ─────────────────────────────────────────────────────────────────────────────
# POST-COMBAT RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

def finalize_combat(session_id: int, winner_side: str, result_type: str,
                    state: dict) -> dict:
    """Run full post-combat resolution sequence.
    Steps: XP → credits stolen → durability hits → item steal → over-encumbered check
           → feed entries → boss intel → clear in_combat → clear combat buffs."""
    session  = state["session"]
    attacker = state["attacker"]
    settings = get_all_settings()

    winner_is_attacker = winner_side == "ATTACKER"
    winner  = attacker if winner_is_attacker else state.get("defender")
    loser   = state.get("defender") if winner_is_attacker else attacker

    xp_earned     = 0
    credits_stolen = 0
    item_stolen    = None
    drops           = None

    # Step 1: XP award
    if session["combat_type"] in ("BOSS", "MINION") and winner_is_attacker:
        opp = state.get("boss") or state.get("minion")
        base_xp = 100 * opp["level"]
        special = state["attacker_equipped"].get("special")
        xp_mult = special.get("xp_multiplier", 0.0) if special else 0.0
        xp_earned = engine.calc_xp_reward(
            base_xp, attacker["level"], opp["level"], xp_mult
        )
        with exclusive_transaction():
            execute_write("UPDATE players SET xp = xp + ? WHERE id = ?",
                          (xp_earned, attacker["id"]))
            leveled = engine.check_level_up(
                attacker["id"], attacker["xp"] + xp_earned, attacker["level"]
            )
        # Update kill count and reset persistent encounter state atomically.
        with exclusive_transaction():
            if session["combat_type"] == "BOSS":
                execute_write(
                    "UPDATE boss_instances SET kill_count = kill_count + 1 WHERE id = ?",
                    (session["boss_instance_id"],)
                )
                execute_write(
                    """UPDATE boss_instances
                       SET current_hp = (SELECT max_hp FROM bosses WHERE id = boss_id),
                           special_attack_used=0, special_buff_used=0, current_phase=1
                       WHERE id = ?""",
                    (session["boss_instance_id"],)
                )
            else:
                execute_write(
                    "UPDATE minion_instances SET kill_count = kill_count + 1 WHERE id = ?",
                    (session["minion_instance_id"],)
                )

        drops = _award_drops(
            player_id=attacker["id"], player=attacker, opponent=opp,
            combat_type=session["combat_type"],
            master_row=_get_master_for_opponent(opp, session["combat_type"]),
            settings=settings,
            equipped_special=state["attacker_equipped"].get("special"),
        )

    elif session["combat_type"] == "PVP":
        zero_xp_bonus = settings.get("ZERO_CREDIT_XP_BONUS", cfg.ZERO_CREDIT_XP_BONUS)
        xp_loss_div   = settings.get("XP_LOSS_DIVISOR",       cfg.XP_LOSS_DIVISOR)
        special       = state["attacker_equipped"].get("special")
        xp_mult       = special.get("xp_multiplier", 0.0) if special else 0.0

        if winner_is_attacker:
            # Winner XP
            base_xp = 80 * (state["defender"]["level"] if state.get("defender") else 1)
            xp_earned = engine.calc_xp_reward(
                base_xp, attacker["level"],
                state["defender"]["level"] if state.get("defender") else attacker["level"],
                xp_mult
            )
            with exclusive_transaction():
                execute_write("UPDATE players SET xp = xp + ? WHERE id = ?",
                              (xp_earned, attacker["id"]))
                execute_write("UPDATE player_stats SET pvp_kills = pvp_kills + 1 WHERE player_id = ?",
                              (attacker["id"],))
                execute_write(
                    "UPDATE player_stats SET times_reduced_to_1hp = times_reduced_to_1hp + 1 WHERE player_id = ?",
                    (state["defender"]["id"],)
                )
        else:
            # Initiator lost — XP penalty
            base_xp = 80 * (state["defender"]["level"] if state.get("defender") else 1)
            potential_win_xp = engine.calc_xp_reward(base_xp, attacker["level"],
                                                       attacker["level"], xp_mult)
            xp_penalty = max(0, potential_win_xp // xp_loss_div)
            with exclusive_transaction():
                execute_write(
                    "UPDATE players SET xp = MAX(0, xp - ?) WHERE id = ?",
                    (xp_penalty, attacker["id"])
                )
                execute_write("UPDATE player_stats SET pvp_kills = pvp_kills + 1 WHERE player_id = ?",
                              (state["defender"]["id"],))
                execute_write(
                    "UPDATE player_stats SET times_reduced_to_1hp = times_reduced_to_1hp + 1 WHERE player_id = ?",
                    (attacker["id"],)
                )

        # Step 2: Credits stolen
        if winner and loser:
            cr_pct    = settings.get("CREDIT_STEAL_PERCENT",       cfg.CREDIT_STEAL_PERCENT)
            cr_lck_mult = settings.get("CREDIT_STEAL_LUCK_MULTIPLIER", cfg.CREDIT_STEAL_LUCK_MULTIPLIER)
            steal_bonus = (special.get("steal_bonus", 0.0) if special else 0.0)
            final_pct   = cr_pct + steal_bonus
            loser_player = execute_one("SELECT credits FROM players WHERE id = ?", (loser["id"],))
            credits_stolen = max(0, int(loser_player["credits"] * final_pct))
            # LCK double roll
            if random.random() < (engine.stat_mod(winner["lck_stat"]) * 0.05):
                credits_stolen *= cr_lck_mult
            credits_stolen = min(credits_stolen, loser_player["credits"])

            if credits_stolen == 0:
                # Zero credit bonus
                with exclusive_transaction():
                    execute_write("UPDATE players SET xp = xp + ? WHERE id = ?",
                                  (zero_xp_bonus, winner["id"]))
            else:
                with exclusive_transaction():
                    execute_write(
                        "UPDATE players SET credits = credits - ? WHERE id = ?",
                        (credits_stolen, loser["id"])
                    )
                    execute_write(
                        "UPDATE players SET credits = credits + ? WHERE id = ?",
                        (credits_stolen, winner["id"])
                    )

        # Step 3: Durability hits on loser's gear (before item steal)
        if loser:
            loser_eq = (state["attacker_equipped"] if not winner_is_attacker
                        else state["defender_equipped"])
            if loser_eq:
                engine.apply_pvp_loss_durability_hits(loser["id"], loser_eq)

        # Step 4: Item steal roll
        if winner and loser and result_type == "1HP_WIN":
            loser_eq  = (state["attacker_equipped"] if not winner_is_attacker
                         else state["defender_equipped"])
            steal_bonus = (special.get("steal_bonus", 0.0) if special else 0.0)
            loser_player = (state["defender"] if winner_is_attacker else attacker)
            roll_r = engine.resolve_opposed_roll(
                actor_agi=winner["agi_stat"], actor_lck=winner["lck_stat"],
                defender_agi=loser["agi_stat"], defender_lck=loser["lck_stat"],
                steal_bonus_pct=steal_bonus, tie_goes_to="defender"
            )
            if roll_r["success"]:
                loser_unequipped = [
                    i for i in execute(
                        "SELECT * FROM inventory_items WHERE player_id = ?", (loser["id"],)
                    )
                    if i["id"] not in {
                        loser_player.get("equipped_weapon_id"),
                        loser_player.get("equipped_armor_id"),
                        loser_player.get("equipped_special_id"),
                    }
                ]
                if loser_unequipped:
                    target = random.choice(loser_unequipped)
                    with exclusive_transaction():
                        execute_write(
                            "UPDATE inventory_items SET player_id = ?, acquired_method = 'PVP_STEAL' WHERE id = ?",
                            (winner["id"], target["id"])
                        )
                    item_detail = execute_one(
                        f"SELECT name FROM {'weapons' if target['item_type']=='WEAPON' else 'armor' if target['item_type']=='ARMOR' else 'special_items'} WHERE id = ?",
                        (target["item_id"],)
                    )
                    item_stolen = item_detail["name"] if item_detail else "item"

    # Finalize session
    with exclusive_transaction():
        execute_write(
            "UPDATE combat_sessions SET status='RESOLVED', result=?, resolved_at=? WHERE id=?",
            (result_type, datetime.utcnow().isoformat(), session_id)
        )
        execute_write(
            "UPDATE players SET in_combat = 0 WHERE id = ?",
            (session["attacker_player_id"],)
        )
        if session["combat_type"] == "PVP" and session.get("defender_player_id"):
            execute_write(
                "UPDATE players SET in_combat = 0 WHERE id = ?",
                (session["defender_player_id"],)
            )
        execute_write("DELETE FROM combat_buffs WHERE combat_session_id = ?", (session_id,))

    # Feed entries
    winner_name = winner.get("character_name") if winner else "Unknown"
    loser_name  = (loser.get("character_name") if loser
                   else (state.get("boss") or state.get("minion") or {}).get("name", "opponent"))
    global_text = flavour.combat_result_flavor(
        winner_name, loser_name, session["combat_type"],
        credits_stolen, item_stolen, result_type
    )
    with exclusive_transaction():
        execute_write(
            """INSERT INTO daily_feed (feed_scope, player_id, flavor_text, event_category, combat_session_id)
               VALUES ('GLOBAL', NULL, ?, 'COMBAT', ?)""",
            (global_text, session_id)
        )
        execute_write(
            """INSERT INTO daily_feed (feed_scope, player_id, flavor_text, event_category, combat_session_id)
               VALUES ('PERSONAL', ?, ?, 'COMBAT', ?)""",
            (attacker["id"], global_text, session_id)
        )

    return {
        "winner_side":     winner_side,
        "result_type":     result_type,
        "xp_earned":       xp_earned,
        "credits_stolen":  credits_stolen,
        "item_stolen":     item_stolen,
        "drops":           drops,
        "flavor":          global_text,
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _apply_durability_loss(inv_id: int, loss: int, player_id: int):
    """Apply durability loss to an inventory item. Destroys item if it hits 0.
    Must be called inside exclusive_transaction()."""
    row = execute_one("SELECT current_durability, item_type, item_id, player_id FROM inventory_items WHERE id = ?", (inv_id,))
    if row is None:
        return
    new_dur = max(0, row["current_durability"] - loss)
    if new_dur == 0:
        _destroy_item(inv_id, row, player_id)
    else:
        execute_write(
            "UPDATE inventory_items SET current_durability = ? WHERE id = ?",
            (new_dur, inv_id)
        )


def _destroy_item(inv_id: int, row: dict, player_id: int):
    """Delete an item at 0 durability, null out equipped slot, return special to pool."""
    execute_write("DELETE FROM inventory_items WHERE id = ?", (inv_id,))
    # Null out equipped slot if this was equipped
    for col in ("equipped_weapon_id", "equipped_armor_id", "equipped_special_id"):
        execute_write(
            f"UPDATE players SET {col} = NULL WHERE id = ? AND {col} = ?",
            (player_id, inv_id)
        )
    if row["item_type"] == "SPECIAL":
        execute_write(
            """UPDATE special_item_registry
               SET status='IN_POOL', current_owner_player_id=NULL, inventory_item_id=NULL,
                   last_released_method='DESTROYED', updated_at=?
               WHERE special_item_id=?""",
            (datetime.utcnow().isoformat(), row["item_id"])
        )
    # Log destruction
    item_detail = execute_one(
        f"SELECT name FROM {'weapons' if row['item_type']=='WEAPON' else 'armor' if row['item_type']=='ARMOR' else 'special_items'} WHERE id = ?",
        (row["item_id"],)
    )
    item_name = item_detail["name"] if item_detail else "Unknown Item"
    execute_write(
        """INSERT INTO item_history (player_id, item_type, item_id, item_name, event_type)
           VALUES (?, ?, ?, ?, 'DESTROYED')""",
        (player_id, row["item_type"], row["item_id"], item_name)
    )


def _apply_steal_fail_penalty(session_id: int, side: str):
    """Insert steal fail AC penalty buff. Inside exclusive_transaction()."""
    with exclusive_transaction():
        execute_write(
            """INSERT INTO combat_buffs
               (combat_session_id, side, buff_type, value, expires_on)
               VALUES (?, ?, 'STEAL_FAIL_AC_PENALTY', 3, 'NEXT_HIT_RESOLVED')""",
            (session_id, side)
        )


def _write_combat_log(session_id: int, round_num: int, actor: str,
                      action_type: str, roll_detail: str, outcome_detail: str):
    execute_write(
        """INSERT INTO combat_logs
           (combat_session_id, round_number, actor, action_type, roll_detail, outcome_detail)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, round_num, actor, action_type, roll_detail, outcome_detail)
    )


def _get_master_for_opponent(opponent: dict, combat_type: str) -> dict | None:
    """Load the master table row for a boss or minion by name."""
    col = "boss_id" if combat_type == "BOSS" else "minion_id"
    # opponent dict has 'id' which is the bosses/minions table id
    return execute_one(
        f"SELECT * FROM master WHERE {col} = (SELECT id FROM "
        f"{'bosses' if combat_type == 'BOSS' else 'minions'} WHERE name = ?)",
        (opponent["name"],)
    )


def _award_drops(player_id: int, player: dict, opponent: dict,
                 combat_type: str, master_row: dict | None,
                 settings: dict, equipped_special: dict | None) -> dict:
    """Roll all drop table entries for a defeated boss or minion.
    Returns dict with keys: credits, weapon, armor, special (each None or item name)."""
    import random
    from datetime import datetime

    result = {"credits": 0, "weapon": None, "armor": None, "special": None}

    if not master_row:
        return result

    # ── Credits ───────────────────────────────────────────────────────────────
    cr_min  = opponent.get("drop_credit_min", 0)
    cr_max  = opponent.get("drop_credit_max", 0)
    if cr_max > 0:
        credits = random.randint(cr_min, cr_max)
        # Apply credit multiplier from equipped special item
        if equipped_special and equipped_special.get("credit_multiplier"):
            credits = int(credits * (1 + equipped_special["credit_multiplier"]))
        if credits > 0:
            with exclusive_transaction():
                execute_write(
                    "UPDATE players SET credits = credits + ? WHERE id = ?",
                    (credits, player_id)
                )
            result["credits"] = credits

    # ── Determine which item IDs to roll for ──────────────────────────────────
    if combat_type == "BOSS":
        weapon_id  = master_row.get("boss_weapon_id")
        armor_id   = master_row.get("boss_armor_id")
        special_id = master_row.get("boss_special_item_id")
    else:
        weapon_id  = master_row.get("minion_weapon_id")
        armor_id   = master_row.get("minion_armor_id")
        special_id = master_row.get("minion_special_item_id")

    # ── Weapon drop ───────────────────────────────────────────────────────────
    weapon_chance = opponent.get("drop_weapon_chance", 0.0)
    if weapon_id and random.random() < weapon_chance:
        # Skip if player already owns this weapon
        already_owned = execute_one(
            "SELECT id FROM inventory_items WHERE player_id = ? AND item_type = 'WEAPON' AND item_id = ?",
            (player_id, weapon_id)
        )
        if not already_owned:
            weapon_detail = execute_one("SELECT * FROM weapons WHERE id = ?", (weapon_id,))
            if weapon_detail:
                with exclusive_transaction():
                    execute_write(
                        """INSERT INTO inventory_items
                           (player_id, item_type, item_id, current_durability, acquired_method)
                           VALUES (?, 'WEAPON', ?, ?, ?)""",
                        (player_id, weapon_id,
                         weapon_detail.get("starting_durability", 100),
                         "BOSS_DROP" if combat_type == "BOSS" else "MINION_DROP")
                    )
                    execute_write(
                        """INSERT INTO item_history
                           (player_id, item_type, item_id, item_name, event_type)
                           VALUES (?, 'WEAPON', ?, ?, ?)""",
                        (player_id, weapon_id, weapon_detail["name"],
                         "RECEIVED_BOSS_DROP" if combat_type == "BOSS" else "RECEIVED_MINION_DROP")
                    )
                result["weapon"] = weapon_detail["name"]

    # ── Armor drop ────────────────────────────────────────────────────────────
    armor_chance = opponent.get("drop_armor_chance", 0.0)
    if armor_id and random.random() < armor_chance:
        already_owned = execute_one(
            "SELECT id FROM inventory_items WHERE player_id = ? AND item_type = 'ARMOR' AND item_id = ?",
            (player_id, armor_id)
        )
        if not already_owned:
            armor_detail = execute_one("SELECT * FROM armor WHERE id = ?", (armor_id,))
            if armor_detail:
                with exclusive_transaction():
                    execute_write(
                        """INSERT INTO inventory_items
                           (player_id, item_type, item_id, current_durability, acquired_method)
                           VALUES (?, 'ARMOR', ?, ?, ?)""",
                        (player_id, armor_id,
                         armor_detail.get("starting_durability", 100),
                         "BOSS_DROP" if combat_type == "BOSS" else "MINION_DROP")
                    )
                    execute_write(
                        """INSERT INTO item_history
                           (player_id, item_type, item_id, item_name, event_type)
                           VALUES (?, 'ARMOR', ?, ?, ?)""",
                        (player_id, armor_id, armor_detail["name"],
                         "RECEIVED_BOSS_DROP" if combat_type == "BOSS" else "RECEIVED_MINION_DROP")
                    )
                result["armor"] = armor_detail["name"]

    # ── Special item drop ─────────────────────────────────────────────────────
    special_chance = opponent.get("drop_special_item_chance", 0.0)
    if special_id and random.random() < special_chance:
        # Check registry — must be IN_POOL
        reg = execute_one(
            "SELECT * FROM special_item_registry WHERE special_item_id = ?",
            (special_id,)
        )
        if reg and reg["status"] == "IN_POOL":
            special_detail = execute_one("SELECT * FROM special_items WHERE id = ?", (special_id,))
            if special_detail:
                with exclusive_transaction():
                    inv_id = execute_write(
                        """INSERT INTO inventory_items
                           (player_id, item_type, item_id, current_durability, acquired_method)
                           VALUES (?, 'SPECIAL', ?, ?, ?)""",
                        (player_id, special_id,
                         special_detail.get("starting_durability", 100),
                         "BOSS_DROP" if combat_type == "BOSS" else "MINION_DROP")
                    )
                    execute_write(
                        """UPDATE special_item_registry
                           SET status = 'IN_INVENTORY',
                               current_owner_player_id = ?,
                               inventory_item_id = ?,
                               last_acquired_method = ?,
                               updated_at = ?
                           WHERE special_item_id = ?""",
                        (player_id, inv_id,
                         "BOSS_DROP" if combat_type == "BOSS" else "MINION_DROP",
                         datetime.utcnow().isoformat(), special_id)
                    )
                    execute_write(
                        """INSERT INTO item_history
                           (player_id, item_type, item_id, item_name, event_type)
                           VALUES (?, 'SPECIAL', ?, ?, ?)""",
                        (player_id, special_id, special_detail["name"],
                         "RECEIVED_BOSS_DROP" if combat_type == "BOSS" else "RECEIVED_MINION_DROP")
                    )
                    # Global feed: special item enters world
                    execute_write(
                        """INSERT INTO daily_feed
                           (feed_scope, player_id, flavor_text, event_category)
                           VALUES ('GLOBAL', NULL, ?, 'ITEM')""",
                        (f"The {special_detail['name']} has been claimed from {opponent['name']}.",)
                    )
                result["special"] = special_detail["name"]

    # ── Personal feed entry summarising all drops ─────────────────────────────
    drop_lines = []
    if result["credits"]: drop_lines.append(f"+{result['credits']} credits")
    if result["weapon"]:  drop_lines.append(f"Found: {result['weapon']}")
    if result["armor"]:   drop_lines.append(f"Found: {result['armor']}")
    if result["special"]: drop_lines.append(f"★ Seized: {result['special']}")

    if drop_lines:
        with exclusive_transaction():
            execute_write(
                """INSERT INTO daily_feed
                   (feed_scope, player_id, flavor_text, event_category)
                   VALUES ('PERSONAL', ?, ?, 'ITEM')""",
                (player_id, " | ".join(drop_lines))
            )

    return result


def _boss_regular_attack(session_id: int, state: dict, phase: int) -> dict:
    """Execute a regular boss attack, with phase-based attack bonuses.
    Phase 2: +2 to attack roll. Phase 3: +4 to attack roll."""
    boss    = state["boss"]
    session = state["session"]

    # Phase attack bonus
    phase_attack_bonus = {1: 0, 2: 2, 3: 4}.get(phase, 0)

    # Inject phase bonus as a temporary combat buff for this round
    if phase_attack_bonus > 0:
        with exclusive_transaction():
            execute_write(
                """INSERT INTO combat_buffs
                   (combat_session_id, side, buff_type, value, expires_on)
                   VALUES (?, 'DEFENDER', 'BOSS_ATTACK_BONUS', ?, 'END_OF_ROUND')""",
                (session_id, phase_attack_bonus)
            )
        # Reload state to pick up the new buff
        state = get_combat_state(session_id)
        boss  = state["boss"]

    boss_as_attacker = {**boss}
    boss_weapon      = _get_boss_weapon(boss)
    attacker_player  = state["attacker"]
    att_armor        = state["attacker_equipped"].get("armor")
    att_special      = state["attacker_equipped"].get("special")
    att_buffs        = state["attacker_buffs"]
    brace_dodge      = sum(
        int(b["value"]) for b in att_buffs if b["buff_type"] == "BRACE_DODGE_BONUS"
    )

    result = engine.resolve_full_attack(
        attacker=boss_as_attacker,
        defender=attacker_player,
        attacker_weapon=boss_weapon,
        attacker_special=None,
        defender_armor=att_armor,
        defender_special=att_special,
        boss=None,
        brace_dodge_bonus=brace_dodge,
        active_buffs=att_buffs,
        is_player_attacker=False,
    )

    with exclusive_transaction():
        if result["hit"]:
            new_hp = max(1, attacker_player["current_hp"] - result["damage_total"])
            execute_write(
                "UPDATE players SET current_hp = ? WHERE id = ?",
                (new_hp, session["attacker_player_id"])
            )
            execute_write(
                """UPDATE combat_sessions
                   SET defender_total_damage_dealt = defender_total_damage_dealt + ?
                   WHERE id = ?""",
                (result["damage_total"], session_id)
            )
            if att_armor:
                _apply_durability_loss(att_armor["inv_id"], 1,
                                       session["attacker_player_id"])
            execute_write(
                """DELETE FROM combat_buffs
                   WHERE combat_session_id = ? AND side = 'ATTACKER'
                   AND expires_on = 'NEXT_HIT_RESOLVED'""",
                (session_id,)
            )
        _write_combat_log(session_id, session["current_round"], "DEFENDER",
                          "ATTACK", result["roll_detail"], result["outcome_detail"])

    flv = flavour.attack_flavor(
        attacker_name=boss["name"],
        weapon_name=boss_weapon.get("name", "attack"),
        weapon_type=boss_weapon.get("weapon_type", "Melee"),
        hit=result["hit"], dodged=result["dodged"],
        is_crit=result["is_crit"],
        damage=result["damage_total"],
        damage_type=boss_weapon.get("damage_type", "Blunt"),
    )
    return {
        "action": "ATTACK",
        "hit": result["hit"],
        "dodged": result["dodged"],
        "damage_total": result["damage_total"],
        "roll_detail": result["roll_detail"],
        "flavor": flv,
    }
