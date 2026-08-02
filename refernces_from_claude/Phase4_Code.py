################################################################################
# PHASE 4 CODE — Combat Engine
# BBS-Inspired Multiplayer Dueling Game
#
# Files included:
#   1. combat/__init__.py     (empty — makes combat/ a Python package)
#   2. combat/engine.py       — Core math: rolls, damage, resistance, dodge, crit
#   3. combat/flavour.py      — All flavor text generation
#   4. combat/actions.py      — Per-action handlers + opponent automation + post-combat
#
# Requires Phase 1-3 files to already be in place.
# Create an empty combat/__init__.py file before placing these files.
################################################################################

################################################################################
# FILE: combat/__init__.py (empty)
################################################################################

# (empty file)


################################################################################
# FILE: combat/engine.py
################################################################################

# combat/engine.py
# Core combat math. All dice rolls, stat modifiers, damage resolution,
# resistance/weakness checks, dodge, crit, and durability.
# Stateless pure functions — takes input dicts, returns result dicts.
# Never writes to the DB directly.

import math
import random
import logging

import config_defaults as cfg
from database import get_all_settings

logger = logging.getLogger(__name__)

# The 7 damage types
DAMAGE_TYPES = {"blade", "blunt", "ballistic", "energy", "arcane", "explosive", "venom"}

# Resistance column names on armor/special_items/bosses
RES_COLS  = [f"res_{t}"  for t in DAMAGE_TYPES]
WEAK_COLS = [f"weak_{t}" for t in DAMAGE_TYPES]


# ─────────────────────────────────────────────────────────────────────────────
# DICE & STAT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def roll(sides: int) -> int:
    """Roll a single die with the given number of sides."""
    return random.randint(1, sides)


def roll_damage_die(die_str: str) -> int:
    """Parse and roll a damage die string like 'd8', 'd12', etc."""
    sides = int(die_str.lstrip("d"))
    return roll(sides)


def stat_mod(stat: int) -> int:
    """Standard stat modifier: floor(stat / 2)."""
    return math.floor(stat / 2)


# ─────────────────────────────────────────────────────────────────────────────
# DERIVED STAT CALCULATIONS
# ─────────────────────────────────────────────────────────────────────────────

def calc_max_hp(player: dict) -> int:
    """10 + END + (5 * level)"""
    return 10 + player["end_stat"] + (5 * player["level"])


def calc_ac(combatant: dict, armor: dict | None) -> int:
    """10 + floor(AGI/2) + armor.ac_bonus (if equipped)"""
    ac = 10 + stat_mod(combatant["agi_stat"])
    if armor:
        ac += armor.get("ac_bonus", 0)
    return ac


def calc_max_ap(player: dict, is_cursed: bool = False) -> int:
    """BASE_DAILY_AP + floor(END/2), reduced by CURSE_AP_REDUCTION if cursed."""
    settings  = get_all_settings()
    base      = settings.get("BASE_DAILY_AP",       cfg.BASE_DAILY_AP)
    cap       = settings.get("AP_CARRYOVER_CAP",    cfg.AP_CARRYOVER_CAP)
    curse_red = settings.get("CURSE_AP_REDUCTION",  cfg.CURSE_AP_REDUCTION)
    raw       = base + stat_mod(player["end_stat"])
    if is_cursed:
        raw = int(raw * (1 - curse_red))
    return min(raw, cap)


def calc_passive_regen(player: dict, special: dict | None = None) -> int:
    """AP_PASSIVE_HP_REGEN + floor(END/END_HP_REGEN_DIVISOR) + HP_REGEN_BONUS (special)"""
    settings  = get_all_settings()
    base_regen = settings.get("AP_PASSIVE_HP_REGEN",   cfg.AP_PASSIVE_HP_REGEN)
    divisor    = settings.get("END_HP_REGEN_DIVISOR",  cfg.END_HP_REGEN_DIVISOR)
    bonus      = special.get("hp_regen_bonus", 0) if special else 0
    return base_regen + math.floor(player["end_stat"] / divisor) + bonus


def calc_initiative(combatant: dict, initiative_bonus: int = 0) -> tuple[int, int]:
    """Roll initiative: d20 + floor(AGI/2) + initiative_bonus.
    Returns (total, raw_roll) — raw AGI used for tie-breaking."""
    raw_roll = roll(20)
    total    = raw_roll + stat_mod(combatant["agi_stat"]) + initiative_bonus
    return total, combatant["agi_stat"]


def calc_crit_threshold(combatant: dict, special: dict | None = None) -> int:
    """max(CRIT_MIN_THRESHOLD, 20 - floor(LCK / CRIT_LCK_DIVISOR))
    Further reduced by special.crit_chance_bonus if equipped."""
    settings  = get_all_settings()
    base      = settings.get("CRIT_BASE_THRESHOLD", cfg.CRIT_BASE_THRESHOLD)
    divisor   = settings.get("CRIT_LCK_DIVISOR",   cfg.CRIT_LCK_DIVISOR)
    min_thr   = settings.get("CRIT_MIN_THRESHOLD",  cfg.CRIT_MIN_THRESHOLD)
    threshold = base - math.floor(combatant["lck_stat"] / divisor)
    if special:
        threshold -= int(special.get("crit_chance_bonus", 0))
    return max(min_thr, threshold)


# ─────────────────────────────────────────────────────────────────────────────
# ATTACK ROLL
# ─────────────────────────────────────────────────────────────────────────────

def calc_attack_roll(attacker: dict, weapon: dict) -> tuple[int, int, bool]:
    """Roll an attack.
    Melee: d20 + floor(STR/2). Ranged: d20 + floor(AGI/2).
    Returns (total, raw_d20, is_crit_range_roll)."""
    raw_d20 = roll(20)
    if weapon["weapon_type"] == "Melee":
        modifier = stat_mod(attacker["str_stat"])
    else:
        modifier = stat_mod(attacker["agi_stat"])
    total = raw_d20 + modifier
    return total, raw_d20, modifier


def hits_ac(attack_total: int, target_ac: int) -> bool:
    return attack_total >= target_ac


# ─────────────────────────────────────────────────────────────────────────────
# DAMAGE CALCULATION
# ─────────────────────────────────────────────────────────────────────────────

def calc_weapon_damage(attacker: dict, weapon: dict, is_crit: bool) -> tuple[int, str]:
    """Roll weapon damage + stat modifier.
    Doubles on crit. Returns (damage, detail_str)."""
    die_roll = roll_damage_die(weapon["damage_die"])
    if weapon["weapon_type"] == "Melee":
        modifier = stat_mod(attacker["str_stat"])
    else:
        modifier = stat_mod(attacker["agi_stat"])
    base = die_roll + modifier
    if is_crit:
        base *= 2
    detail = f"{weapon['damage_die']}({die_roll})+{modifier}={'CRIT:' if is_crit else ''}{base}"
    return base, detail


def calc_bonus_damage(special: dict, is_crit: bool) -> tuple[int, str]:
    """Calculate bonus damage from an equipped special item.
    Doubles on crit. Returns (damage, damage_type)."""
    if not special or not special.get("bonus_damage_amount"):
        return 0, ""
    amount = special["bonus_damage_amount"]
    if is_crit:
        amount *= 2
    return amount, special.get("bonus_damage_type", "")


# ─────────────────────────────────────────────────────────────────────────────
# RESISTANCE & WEAKNESS
# ─────────────────────────────────────────────────────────────────────────────

def resolve_resistance(damage: int, damage_type: str,
                       armor: dict | None,
                       special: dict | None,
                       boss_buff_resistance: str | None = None) -> tuple[int, str]:
    """Apply resistance stacking rule.
    0 sources → full damage
    1 source  → half damage
    2+ sources → floor at RESISTANCE_STACK_MIN_DAMAGE_PERCENT
    Returns (final_damage, note_str)."""
    settings   = get_all_settings()
    floor_pct  = settings.get("RESISTANCE_STACK_MIN_DAMAGE_PERCENT",
                               cfg.RESISTANCE_STACK_MIN_DAMAGE_PERCENT)
    dtype_col  = f"res_{damage_type.lower()}"

    sources = 0
    if armor  and armor.get(dtype_col):
        sources += 1
    if special and special.get(dtype_col):
        sources += 1
    if boss_buff_resistance and boss_buff_resistance.lower() == damage_type.lower():
        sources += 1

    if sources == 0:
        return damage, ""
    elif sources == 1:
        final = max(1, damage // 2)
        return final, f"Resisted ({damage}→{final})"
    else:
        floor_dmg = max(1, int(damage * floor_pct))
        return floor_dmg, f"Stacked resistance ({damage}→{floor_dmg})"


def resolve_weakness(damage: int, damage_type: str, boss: dict) -> tuple[int, str]:
    """If boss has weakness to damage_type, double damage. Players never have weaknesses."""
    dtype_col = f"weak_{damage_type.lower()}"
    if boss and boss.get(dtype_col):
        doubled = damage * 2
        return doubled, f"Weakness! ({damage}→{doubled})"
    return damage, ""


# ─────────────────────────────────────────────────────────────────────────────
# DODGE
# ─────────────────────────────────────────────────────────────────────────────

def resolve_dodge(defender: dict, attacker: dict,
                  brace_dodge_bonus: int = 0) -> tuple[bool, str]:
    """Player-only dodge check. Bosses/minions do not dodge.
    Defender: d20 + floor(AGI/2) + floor(LCK/2) + BRACE_DODGE_BONUS
    Attacker: d20 + floor(AGI/2)  (Initiative Bonus does NOT apply here)
    Ties go to attacker (harder to dodge).
    Returns (dodged: bool, detail_str)."""
    def_roll = roll(20)
    def_mod  = stat_mod(defender["agi_stat"]) + stat_mod(defender["lck_stat"]) + brace_dodge_bonus
    def_total = def_roll + def_mod

    att_roll  = roll(20)
    att_mod   = stat_mod(attacker["agi_stat"])
    att_total = att_roll + att_mod

    dodged = def_total > att_total  # ties go to attacker
    detail = (f"Dodge: {def_roll}+{def_mod}={def_total} vs "
              f"{att_roll}+{att_mod}={att_total} → {'DODGE!' if dodged else 'Hit'}")
    return dodged, detail


# ─────────────────────────────────────────────────────────────────────────────
# FULL ATTACK RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

def resolve_full_attack(attacker: dict, defender: dict,
                        attacker_weapon: dict,
                        attacker_special: dict | None,
                        defender_armor: dict | None,
                        defender_special: dict | None,
                        boss: dict | None = None,
                        brace_dodge_bonus: int = 0,
                        active_buffs: list | None = None,
                        is_player_attacker: bool = True) -> dict:
    """Run the full attack sequence for one attack action.
    Returns a result dict with all details for combat log rendering.

    Sequence:
    1. Dodge check (player defenders only)
    2. Attack roll vs AC
    3. Crit check
    4. Weapon damage roll + stat mod
    5. Resistance + weakness resolution
    6. Special item bonus damage (separate resistance check)
    7. Durability effects
    Returns:
        hit, dodged, damage_total, is_crit,
        weapon_durability_loss, armor_durability_loss,
        roll_detail, outcome_detail
    """
    settings = get_all_settings()

    # --- Get active boss resistance buff if any ---
    boss_resistance_type = None
    if active_buffs:
        for buff in active_buffs:
            if buff.get("buff_type") == "BOSS_RESISTANCE_TYPE":
                boss_resistance_type = buff.get("damage_type")

    # --- Get active combat modifiers from buffs ---
    attack_bonus = 0
    if active_buffs:
        for buff in active_buffs:
            if buff.get("buff_type") == "BOSS_ATTACK_BONUS":
                attack_bonus += int(buff.get("value", 0))

    # --- Step 1: Dodge check (only when defender is a player) ---
    defender_is_player = boss is None
    dodged      = False
    dodge_detail = ""
    if defender_is_player:
        dodged, dodge_detail = resolve_dodge(defender, attacker, brace_dodge_bonus)
        if dodged:
            return {
                "hit": False, "dodged": True, "damage_total": 0, "is_crit": False,
                "weapon_durability_loss": 0, "armor_durability_loss": 0,
                "roll_detail": dodge_detail, "outcome_detail": "Attack dodged — no damage.",
                "damage_breakdown": []
            }

    # --- Step 2: Attack roll vs AC ---
    attack_total, raw_d20, attack_mod = calc_attack_roll(attacker, attacker_weapon)
    attack_total += attack_bonus
    defender_ac   = calc_ac(defender, defender_armor)

    # Apply over-encumbered attack penalty if attacker is a player
    if is_player_attacker and attacker.get("is_overencumbered"):
        over_penalty = settings.get("OVERENCUMBERED_ATTACK_PENALTY", cfg.OVERENCUMBERED_ATTACK_PENALTY)
        attack_total -= over_penalty

    # Apply swap gear penalty if active
    swap_penalty = 0
    if active_buffs and is_player_attacker:
        for buff in active_buffs:
            if buff.get("buff_type") == "SWAP_GEAR_ACCURACY_PENALTY":
                swap_penalty = int(buff.get("value", 0))
    attack_total -= swap_penalty

    hit = hits_ac(attack_total, defender_ac)
    attack_detail = (f"Attack: d20({raw_d20})+{attack_mod}"
                     f"{'−'+str(swap_penalty) if swap_penalty else ''}"
                     f"={attack_total} vs AC {defender_ac} → {'HIT' if hit else 'MISS'}")

    if not hit:
        return {
            "hit": False, "dodged": False, "damage_total": 0, "is_crit": False,
            "weapon_durability_loss": 0, "armor_durability_loss": 0,
            "roll_detail": attack_detail, "outcome_detail": "Miss — no damage.",
            "damage_breakdown": []
        }

    # --- Step 3: Crit check ---
    crit_threshold = calc_crit_threshold(attacker, attacker_special)
    # Extra crit bonus from boss buff
    if active_buffs:
        for buff in active_buffs:
            if buff.get("buff_type") == "BOSS_CRIT_BONUS":
                crit_threshold = max(
                    settings.get("CRIT_MIN_THRESHOLD", cfg.CRIT_MIN_THRESHOLD),
                    crit_threshold - int(buff.get("value", 0))
                )
    is_crit = raw_d20 >= crit_threshold
    if is_crit:
        attack_detail += f" CRITICAL HIT (rolled {raw_d20} ≥ {crit_threshold})!"

    # --- Step 4: Weapon damage ---
    weapon_dmg, weapon_detail = calc_weapon_damage(attacker, attacker_weapon, is_crit)

    # --- Step 5: Resistance + weakness ---
    weapon_dmg, res_note = resolve_resistance(
        weapon_dmg, attacker_weapon["damage_type"],
        defender_armor, defender_special, boss_resistance_type
    )
    if boss:
        weapon_dmg, weak_note = resolve_weakness(
            weapon_dmg, attacker_weapon["damage_type"], boss
        )
    else:
        weak_note = ""

    damage_breakdown = [{
        "type": attacker_weapon["damage_type"],
        "raw": weapon_dmg,
        "note": " ".join(filter(None, [res_note, weak_note]))
    }]

    # --- Step 6: Special item bonus damage ---
    bonus_dmg = 0
    if attacker_special and attacker_special.get("bonus_damage_amount"):
        raw_bonus, bonus_type = calc_bonus_damage(attacker_special, is_crit)
        if raw_bonus and bonus_type:
            final_bonus, bonus_res_note = resolve_resistance(
                raw_bonus, bonus_type, defender_armor, defender_special, boss_resistance_type
            )
            if boss:
                final_bonus, bonus_weak_note = resolve_weakness(final_bonus, bonus_type, boss)
            else:
                bonus_weak_note = ""
            bonus_dmg = final_bonus
            damage_breakdown.append({
                "type": bonus_type,
                "raw": final_bonus,
                "note": " ".join(filter(None, [bonus_res_note, bonus_weak_note]))
            })

    # Crit DMG multiplier from special item (applies on top)
    if is_crit and attacker_special and attacker_special.get("crit_dmg_multiplier"):
        mult = attacker_special["crit_dmg_multiplier"]
        weapon_dmg  = int(weapon_dmg  * (1 + mult))
        bonus_dmg   = int(bonus_dmg   * (1 + mult))

    damage_total = weapon_dmg + bonus_dmg

    # Boss DMG_REDUCTION buff
    if active_buffs:
        for buff in active_buffs:
            if buff.get("buff_type") == "BOSS_DMG_REDUCTION":
                reduction = int(buff.get("value", 0))
                damage_total = max(0, damage_total - reduction)

    # --- Step 7: Durability ---
    weapon_dur_loss = _calc_durability_loss(1, attacker_special)
    armor_dur_loss  = _calc_durability_loss(1, defender_special)

    outcome = (f"{weapon_detail} → {damage_total} damage"
               f"{' (' + damage_breakdown[0]['note'] + ')' if damage_breakdown[0]['note'] else ''}")

    return {
        "hit":                   True,
        "dodged":                False,
        "damage_total":          max(0, damage_total),
        "is_crit":               is_crit,
        "weapon_durability_loss": weapon_dur_loss,
        "armor_durability_loss":  armor_dur_loss,
        "roll_detail":           attack_detail,
        "outcome_detail":        outcome,
        "damage_breakdown":      damage_breakdown,
        "weapon_damage_type":    attacker_weapon["damage_type"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# OPPOSED ROLLS (steal, escape, observe, minion PER)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_opposed_roll(actor_agi: int, actor_lck: int,
                         defender_agi: int, defender_lck: int,
                         actor_per: int = 0, defender_per: int = 0,
                         steal_bonus_pct: float = 0.0,
                         tie_goes_to: str = "defender") -> dict:
    """Generic opposed roll for steal, escape, observe, minion PER check.
    Actor:    d20 + floor(AGI/2) + floor(LCK/2) [+ floor(PER/2) if observe]
    Defender: d20 + floor(AGI/2) + floor(LCK/2) [+ floor(PER/2) if observe]
    Steal bonus adds a flat roll bonus on top.

    tie_goes_to: 'defender' (steal, observe, minion PER) or 'opponent' (escape)
    Returns: {actor_roll, defender_roll, success, detail}"""
    actor_roll    = roll(20) + stat_mod(actor_agi) + stat_mod(actor_lck) + stat_mod(actor_per)
    actor_roll   += int(steal_bonus_pct * 20)  # steal bonus as flat roll bonus
    defender_roll = roll(20) + stat_mod(defender_agi) + stat_mod(defender_lck) + stat_mod(defender_per)

    if tie_goes_to == "defender":
        success = actor_roll > defender_roll
    else:  # tie goes to opponent/defender — actor needs strict win
        success = actor_roll > defender_roll

    detail = f"Roll: {actor_roll} vs {defender_roll} → {'Success' if success else 'Fail'}"
    return {
        "actor_roll":    actor_roll,
        "defender_roll": defender_roll,
        "success":       success,
        "detail":        detail,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PVP SCORE FORMULA
# ─────────────────────────────────────────────────────────────────────────────

def calc_pvp_score(session: dict, attacker_max_hp: int,
                   defender_max_hp: int) -> tuple[float, float]:
    """Tiebreak score formula:
    (HP% * COMBAT_WIN_HP_WEIGHT) + (Damage Dealt% * COMBAT_WIN_DMG_WEIGHT)
    Always produces a winner."""
    settings   = get_all_settings()
    hp_weight  = settings.get("COMBAT_WIN_HP_WEIGHT",  cfg.COMBAT_WIN_HP_WEIGHT)
    dmg_weight = settings.get("COMBAT_WIN_DMG_WEIGHT", cfg.COMBAT_WIN_DMG_WEIGHT)

    att_hp_pct  = session["attacker_hp_start"] / attacker_max_hp if attacker_max_hp else 0
    def_hp_pct  = session["defender_hp_start"] / defender_max_hp if defender_max_hp else 0

    total_dmg = (session["attacker_total_damage_dealt"] +
                 session["defender_total_damage_dealt"])

    att_dmg_pct = session["attacker_total_damage_dealt"] / total_dmg if total_dmg else 0
    def_dmg_pct = session["defender_total_damage_dealt"] / total_dmg if total_dmg else 0

    att_score = (att_hp_pct * hp_weight) + (att_dmg_pct * dmg_weight)
    def_score = (def_hp_pct * hp_weight) + (def_dmg_pct * dmg_weight)

    # Guarantee a winner — nudge attacker score if truly tied
    if att_score == def_score:
        att_score += 0.001

    return att_score, def_score


# ─────────────────────────────────────────────────────────────────────────────
# DURABILITY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _calc_durability_loss(base_loss: int, special: dict | None) -> int:
    """Apply durability_reduction modifier from special item.
    base_loss * (1 - durability_reduction), minimum 1."""
    if not special or not special.get("durability_reduction"):
        return base_loss
    reduction = special["durability_reduction"]
    return max(1, int(base_loss * (1 - reduction)))


def calc_special_item_round_loss(special: dict | None) -> int:
    """SPECIAL_ITEM_DURABILITY_LOSS_PER_ROUND % of 100 per round, both sides."""
    if not special:
        return 0
    settings = get_all_settings()
    pct = settings.get("SPECIAL_ITEM_DURABILITY_LOSS_PER_ROUND",
                       cfg.SPECIAL_ITEM_DURABILITY_LOSS_PER_ROUND)
    return max(1, int(100 * pct))


def apply_pvp_loss_durability_hits(player_id: int, equipped: dict):
    """Additional durability hits on all equipped gear when losing PvP.
    Called from post-combat resolution BEFORE item steal roll.
    Imported and called by combat/actions.py."""
    from database import execute_write, exclusive_transaction
    for slot, item in equipped.items():
        if item is None:
            continue
        inv_id   = item["inv_id"]
        new_dur  = max(0, item["current_durability"] - 10)  # flat -10 on PvP loss
        with exclusive_transaction():
            execute_write(
                "UPDATE inventory_items SET current_durability = ? WHERE id = ?",
                (new_dur, inv_id)
            )


# ─────────────────────────────────────────────────────────────────────────────
# XP SCALING
# ─────────────────────────────────────────────────────────────────────────────

def calc_xp_reward(base_xp: int, winner_level: int, opponent_level: int,
                   xp_multiplier: float = 0.0) -> int:
    """Scale XP by level difference. Higher opponent = bonus, lower = penalty."""
    level_diff = opponent_level - winner_level
    if level_diff > 0:
        scale = 1.0 + (level_diff * 0.1)    # +10% per level above
    elif level_diff < 0:
        scale = max(0.1, 1.0 + (level_diff * 0.15))  # -15% per level below, min 10%
    else:
        scale = 1.0

    raw = int(base_xp * scale)
    if xp_multiplier:
        raw = int(raw * (1 + xp_multiplier))
    return max(0, raw)


def check_level_up(player_id: int, current_xp: int, current_level: int) -> bool:
    """Check if player has enough XP to level up. Sets pending_levelup if so.
    Returns True if a level-up occurred."""
    settings  = get_all_settings()
    xp_curve  = cfg.XP_CURVE
    next_level = current_level + 1
    if next_level > 15:
        return False  # Max level — XP accumulates but no more level-ups
    threshold = xp_curve.get(next_level)
    if threshold is None or current_xp < threshold:
        return False

    from database import execute_write, exclusive_transaction
    with exclusive_transaction():
        execute_write(
            "UPDATE players SET level = level + 1, pending_levelup = 1 WHERE id = ?",
            (player_id,)
        )
    return True


################################################################################
# FILE: combat/flavour.py
################################################################################

# combat/flavour.py
# Generates all flavor text strings for combat logs, feed entries,
# and event results. Keeps narrative text out of logic files.
# All functions return plain strings ready for template rendering.

import random


# ─────────────────────────────────────────────────────────────────────────────
# COMBAT INTRO
# ─────────────────────────────────────────────────────────────────────────────

def combat_intro(combat_type: str, opponent_name: str,
                 boss_flavor: str = "", boss_phase: int = 1) -> str:
    if combat_type == "BOSS":
        lines = [
            f"═══ BOSS FIGHT: {opponent_name.upper()} ════════════════════════════════",
        ]
        if boss_flavor:
            lines.append(boss_flavor)
        if boss_phase > 1:
            lines.append(f"[Phase {boss_phase} active]")
        return "\n".join(lines)
    elif combat_type == "MINION":
        return (f"═══ MINION ENCOUNTER: {opponent_name.upper()} ══════════════════════\n"
                f"A lesser foe blocks your path!")
    else:  # PVP
        return f"═══ PVP: You challenge {opponent_name} ═══════════════════════════════"


def round_header(round_num: int) -> str:
    return f"─── Round {round_num} ─────────────────────────────────────────────────────"


def combat_warning(warning_type: str, opponent_name: str = "",
                   level_diff: int = 0) -> str:
    if warning_type == "empty_weapon":
        return "⚠ WARNING: You are unarmed. Fists deal minimal damage."
    elif warning_type == "empty_armor":
        return "⚠ WARNING: You have no armor equipped."
    elif warning_type == "level_mismatch":
        return (f"⚠ WARNING: {opponent_name} is {level_diff} levels above you. "
                f"This fight may be extremely dangerous. Proceed?")
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# ATTACK FLAVOR
# ─────────────────────────────────────────────────────────────────────────────

ATTACK_VERBS_MELEE  = ["swings", "strikes at", "slashes at", "lunges at", "hammers"]
ATTACK_VERBS_RANGED = ["fires at", "shoots at", "takes aim at", "blasts", "unleashes on"]
DODGE_VERBS         = ["sidesteps", "ducks under", "narrowly evades", "deflects", "rolls away from"]
HIT_VERBS           = ["connects with", "lands a hit on", "strikes", "hits"]


def attack_flavor(attacker_name: str, weapon_name: str,
                  weapon_type: str,
                  hit: bool, dodged: bool, is_crit: bool,
                  damage: int, damage_type: str,
                  res_note: str = "") -> str:
    verb = random.choice(ATTACK_VERBS_MELEE if weapon_type == "Melee" else ATTACK_VERBS_RANGED)

    if dodged:
        evade = random.choice(DODGE_VERBS)
        return f"{attacker_name} {verb} with the {weapon_name} — opponent {evade}! (Dodged)"

    if not hit:
        return f"{attacker_name} {verb} with the {weapon_name} — Miss!"

    if is_crit:
        line = f"★ CRITICAL HIT! {attacker_name} {verb} with the {weapon_name}!"
    else:
        hit_v = random.choice(HIT_VERBS)
        line  = f"{attacker_name} {verb} with the {weapon_name} and {hit_v}!"

    line += f" {damage} {damage_type} damage"
    if res_note:
        line += f" ({res_note})"
    line += "."
    return line


def bonus_damage_flavor(damage: int, damage_type: str, res_note: str = "") -> str:
    line = f"  → Bonus {damage_type} damage: {damage}"
    if res_note:
        line += f" ({res_note})"
    return line + "."


# ─────────────────────────────────────────────────────────────────────────────
# STEAL FLAVOR
# ─────────────────────────────────────────────────────────────────────────────

def steal_flavor(attacker_name: str, target_name: str, success: bool,
                 item_name: str = "", credits: int = 0,
                 xp_bonus: int = 0, is_vs_boss: bool = False) -> str:
    if not success:
        return (f"{attacker_name} attempts to steal from {target_name} — "
                f"caught! AC penalty incoming.")
    if is_vs_boss:
        if item_name:
            return (f"{attacker_name} makes a daring grab and seizes "
                    f"the {item_name} from {target_name}!")
        else:
            return (f"{attacker_name} pilfers {credits} credits worth of valuables "
                    f"from {target_name}.")
    # vs player cascade
    parts = []
    if item_name:
        parts.append(f"snatched the {item_name}")
    if credits:
        parts.append(f"took {credits} credits")
    if xp_bonus:
        parts.append(f"+{xp_bonus} XP consolation")
    result = " → ".join(parts) if parts else "nothing left to steal"
    return f"{attacker_name} steals from {target_name}: {result}."


# ─────────────────────────────────────────────────────────────────────────────
# BRACE FLAVOR
# ─────────────────────────────────────────────────────────────────────────────

def brace_flavor(player_name: str, hp_restored: int,
                 ac_bonus: int, dodge_bonus: int) -> str:
    line = f"{player_name} takes a defensive stance, bracing for impact."
    if hp_restored:
        line += f" +{hp_restored} HP."
    line += f" AC+{ac_bonus}, Dodge+{dodge_bonus} until next hit."
    return line


# ─────────────────────────────────────────────────────────────────────────────
# ESCAPE FLAVOR
# ─────────────────────────────────────────────────────────────────────────────

def escape_flavor(player_name: str, success: bool,
                  credits_lost: int = 0) -> str:
    if success:
        line = f"{player_name} breaks away and flees the fight!"
        if credits_lost:
            line += f" {credits_lost} credits spilled in the retreat."
        return line
    return (f"{player_name} tries to escape but is cut off! "
            f"AC reduced for the next incoming attack.")


# ─────────────────────────────────────────────────────────────────────────────
# OBSERVE FLAVOR
# ─────────────────────────────────────────────────────────────────────────────

def observe_flavor(player_name: str, success: bool,
                   opponent_name: str, revealed: dict | None = None) -> str:
    if not success:
        return (f"{player_name} tries to read {opponent_name} but reveals nothing.")
    line = f"{player_name} studies {opponent_name} carefully."
    if revealed:
        parts = []
        if revealed.get("resistances"):
            parts.append(f"Resistant: {', '.join(revealed['resistances'])}")
        if revealed.get("weaknesses"):
            parts.append(f"Weak to: {', '.join(revealed['weaknesses'])}")
        if revealed.get("exact_hp") is not None:
            parts.append(f"HP: {revealed['exact_hp']}")
        if parts:
            line += " — " + " | ".join(parts)
    return line


# ─────────────────────────────────────────────────────────────────────────────
# SWAP GEAR FLAVOR
# ─────────────────────────────────────────────────────────────────────────────

def swap_gear_flavor(player_name: str, new_item_name: str) -> str:
    return (f"{player_name} quickly swaps to {new_item_name}. "
            f"Attack and AC reduced this round.")


# ─────────────────────────────────────────────────────────────────────────────
# BOSS SPECIAL MOVES
# ─────────────────────────────────────────────────────────────────────────────

def boss_special_attack_flavor(boss_name: str, attack_name: str,
                                damage: int, attack_flavor_text: str = "") -> str:
    line = f"★ {boss_name.upper()} uses {attack_name}!"
    if attack_flavor_text:
        line += f" {attack_flavor_text}"
    line += f" {damage} damage!"
    return line


def boss_special_buff_flavor(boss_name: str, buff_name: str,
                              buff_flavor_text: str = "") -> str:
    line = f"★ {boss_name.upper()} activates {buff_name}!"
    if buff_flavor_text:
        line += f" {buff_flavor_text}"
    line += " (Effect lasts rest of fight.)"
    return line


# ─────────────────────────────────────────────────────────────────────────────
# POST-COMBAT RESULT (for feeds)
# ─────────────────────────────────────────────────────────────────────────────

def combat_result_flavor(winner_name: str, loser_name: str,
                         combat_type: str,
                         credits_stolen: int = 0,
                         item_stolen: str = "",
                         result_type: str = "1HP_WIN") -> str:
    """Global feed entry for a completed fight."""
    if combat_type == "BOSS":
        line = f"{winner_name} has defeated {loser_name}!"
    elif combat_type == "MINION":
        line = f"{winner_name} dispatched a {loser_name}."
    else:  # PVP
        if result_type == "ESCAPE":
            return f"{loser_name} fled a fight with {winner_name}."
        elif result_type == "SCORE_WIN":
            line = f"{winner_name} outlasted {loser_name} in a grinding battle!"
        else:
            line = f"{winner_name} defeated {loser_name} in combat!"

    if credits_stolen:
        line += f" Claimed {credits_stolen} credits."
    if item_stolen:
        line += f" Seized the {item_stolen}!"
    return line


def level_up_flavor(player_name: str, new_level: int) -> str:
    return f"⬆ {player_name} has reached Level {new_level}!"


def special_item_pool_flavor(item_name: str, reason: str = "released") -> str:
    """Global feed: special item returned to/entered the loot pool."""
    if reason == "destroyed":
        return f"The {item_name} has been destroyed and returned to the loot pool."
    elif reason == "sold":
        return f"The {item_name} is now available in the shop."
    else:
        return f"The {item_name} has returned to the loot pool."


# ─────────────────────────────────────────────────────────────────────────────
# RANDOM EVENT FLAVOR
# ─────────────────────────────────────────────────────────────────────────────

def random_event_flavor(event: dict, player_name: str) -> str:
    """Render event flavor text with player name substituted."""
    text = event.get("flavor_text", "Something happens...")
    return text.replace("{player}", player_name).replace("{name}", player_name)


# ─────────────────────────────────────────────────────────────────────────────
# HP DESCRIPTOR
# ─────────────────────────────────────────────────────────────────────────────

def hp_descriptor(current_hp: int, max_hp: int, observed: bool = False) -> str:
    """Return HP description. Exact value if observed, tier name otherwise."""
    if observed:
        return f"{current_hp}/{max_hp} HP"
    pct = (current_hp / max_hp * 100) if max_hp else 0
    if pct >= 76: return "Healthy"
    if pct >= 51: return "Wounded"
    if pct >= 26: return "Hurt"
    if pct >= 2:  return "Critical"
    return "Near Death"


################################################################################
# FILE: combat/actions.py
################################################################################

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
    """Resolve a steal attempt by the player (attacker side only)."""
    session  = state["session"]
    attacker = state["attacker"]
    settings = get_all_settings()

    special     = state["attacker_equipped"].get("special")
    steal_bonus = special.get("steal_bonus", 0.0) if special else 0.0

    if session["combat_type"] == "PVP":
        defender = state["defender"]
        roll_result = engine.resolve_opposed_roll(
            actor_agi=attacker["agi_stat"],
            actor_lck=attacker["lck_stat"],
            defender_agi=defender["agi_stat"],
            defender_lck=defender["lck_stat"],
            steal_bonus_pct=steal_bonus,
            tie_goes_to="defender"
        )
        if not roll_result["success"]:
            _apply_steal_fail_penalty(session_id, "ATTACKER")
            return {"action": "STEAL", "success": False,
                    "roll_detail": roll_result["detail"],
                    "flavor": flavour.steal_flavor(
                        attacker["character_name"], defender["character_name"], False)}

        # Cascade: item → credits → XP
        result = _pvp_steal_cascade(player_id, session["defender_player_id"],
                                    steal_bonus, settings)
        _write_combat_log(session_id, session["current_round"], "ATTACKER",
                          "STEAL", roll_result["detail"], str(result))
        return {"action": "STEAL", "success": True,
                "roll_detail": roll_result["detail"],
                "flavor": flavour.steal_flavor(
                    attacker["character_name"], defender["character_name"], True,
                    item_name=result.get("item_name", ""),
                    credits=result.get("credits", 0),
                    xp_bonus=result.get("xp_bonus", 0))}

    else:
        # vs boss or minion
        opponent = state["boss"] or state["minion"]
        opp_agi  = opponent["agi_stat"]
        opp_lck  = opponent["lck_stat"]
        roll_result = engine.resolve_opposed_roll(
            actor_agi=attacker["agi_stat"],
            actor_lck=attacker["lck_stat"],
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
                        attacker["character_name"], opponent["name"], False,
                        is_vs_boss=True)}

        result = _boss_steal_result(player_id, opponent, steal_bonus, settings,
                                    session["combat_type"])
        _write_combat_log(session_id, session["current_round"], "ATTACKER",
                          "STEAL", roll_result["detail"], str(result))
        return {"action": "STEAL", "success": True,
                "roll_detail": roll_result["detail"],
                "flavor": flavour.steal_flavor(
                    attacker["character_name"], opponent["name"], True,
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


def _boss_steal_result(player_id: int, opponent: dict, steal_bonus: float,
                       settings: dict, combat_type: str) -> dict:
    base_chance   = settings.get("STEAL_SPECIAL_BASE_CHANCE", cfg.STEAL_SPECIAL_BASE_CHANCE)
    cr_multiplier = settings.get("STEAL_BOSS_CREDIT_MULTIPLIER", cfg.STEAL_BOSS_CREDIT_MULTIPLIER)

    player = execute_one("SELECT lck_stat FROM players WHERE id = ?", (player_id,))
    lck_bonus_chance = math.floor(player["lck_stat"] / 2) / 100

    # Try for special item
    if random.random() < (base_chance + lck_bonus_chance):
        # Check if special item is in pool
        association_type = "Boss" if combat_type == "BOSS" else "Minion"
        special_def = execute_one(
            """SELECT si.id, sir.status FROM special_items si
               JOIN special_item_registry sir ON sir.special_item_id = si.id
               WHERE si.associated_to = ? AND si.association_type = ? AND sir.status = 'IN_POOL'""",
            (opponent["name"], association_type)
        )
        if special_def:
            with exclusive_transaction():
                inv_id = execute_write(
                    """INSERT INTO inventory_items
                       (player_id, item_type, item_id, current_durability, acquired_method)
                       VALUES (?, 'SPECIAL', ?, 100, 'COMBAT_STEAL')""",
                    (player_id, special_def["id"])
                )
                execute_write(
                    """UPDATE special_item_registry
                       SET status='IN_INVENTORY', current_owner_player_id=?,
                           inventory_item_id=?, last_acquired_method='COMBAT_STEAL',
                           updated_at=?
                       WHERE special_item_id=?""",
                    (player_id, inv_id, datetime.utcnow().isoformat(), special_def["id"])
                )
            item_name = execute_one(
                "SELECT name FROM special_items WHERE id = ?", (special_def["id"],)
            )["name"]
            return {"item_name": item_name}

    # Credits fallback
    credits_stolen = int(opponent["level"] * (cr_multiplier + steal_bonus * cr_multiplier))
    with exclusive_transaction():
        execute_write("UPDATE players SET credits = credits + ? WHERE id = ?",
                      (credits_stolen, player_id))
    return {"credits": credits_stolen}


# ─────────────────────────────────────────────────────────────────────────────
# ACTION: BRACE
# ─────────────────────────────────────────────────────────────────────────────

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
    """Boss chooses between attack, special attack, and special buff."""
    boss    = state["boss"]
    session = state["session"]

    s_atk_used = boss["special_attack_used"]
    s_buf_used = boss["special_buff_used"]

    # Determine action probabilities
    if not s_atk_used and not s_buf_used:
        # Phase 1: 33/33/33
        r = random.random()
        if r < 0.333:
            chosen = "SPECIAL_ATTACK"
        elif r < 0.666:
            chosen = "SPECIAL_BUFF"
        else:
            chosen = "ATTACK"
    elif s_atk_used and s_buf_used:
        chosen = "ATTACK"
    else:
        chosen = ("SPECIAL_BUFF" if s_atk_used else "SPECIAL_ATTACK") \
                 if random.random() < 0.5 else "ATTACK"

    if chosen == "SPECIAL_ATTACK" and not s_atk_used:
        return _boss_special_attack(session_id, state)
    elif chosen == "SPECIAL_BUFF" and not s_buf_used:
        return _boss_special_buff(session_id, state)
    else:
        # Build a synthetic "boss as attacker" for the engine
        boss_as_attacker = {**boss, "str_stat": boss["str_stat"],
                            "agi_stat": boss["agi_stat"], "lck_stat": boss["lck_stat"]}
        # Boss uses its weapon from master table
        boss_weapon = _get_boss_weapon(boss)
        attacker_player = state["attacker"]
        att_armor  = state["attacker_equipped"].get("armor")
        att_special = state["attacker_equipped"].get("special")
        att_buffs  = state["attacker_buffs"]
        brace_dodge = sum(
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
                    "UPDATE combat_sessions SET defender_total_damage_dealt = defender_total_damage_dealt + ? WHERE id = ?",
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
        return {"action": "ATTACK", "hit": result["hit"], "dodged": result["dodged"],
                "damage_total": result["damage_total"], "flavor": flv}


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
        # Update kill count
        if session["combat_type"] == "BOSS":
            execute_write(
                "UPDATE boss_instances SET kill_count = kill_count + 1 WHERE id = ?",
                (session["boss_instance_id"],)
            )
            # Reset boss instance for next fight
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


