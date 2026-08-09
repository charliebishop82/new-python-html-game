"""Pure dice, damage, initiative, progression, and opposed-roll calculations."""
# combat/engine.py
# Core combat math. All dice rolls, stat modifiers, damage resolution,
# resistance/weakness checks, crit, and durability.
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
    """Parse and roll a damage expression such as ``d8`` or ``2d4``."""
    count_text, sides_text = str(die_str).lower().split("d", 1)
    count = int(count_text or 1)
    sides = int(sides_text)
    if count < 1 or sides < 1:
        raise ValueError(f"Invalid damage die: {die_str}")
    return sum(roll(sides) for _ in range(count))


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
    """10 + half AGI + equipped armor and special-item AC bonuses."""
    ac = 10 + stat_mod(combatant["agi_stat"])
    if armor:
        ac += armor.get("ac_bonus", 0)
    ac += int(combatant.get("special_ac_bonus", 0) or 0)
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
    """Roll initiative: d20 + floor(AGI/2) + initiative_bonus + initiative_modifier.
    initiative_modifier comes from status_effects (STAT_BOOST/PENALTY_INITIATIVE).
    Returns (total, raw_agi) — raw AGI used for tie-breaking."""
    raw_roll = roll(20)
    status_init_mod = combatant.get("initiative_modifier", 0)
    total = raw_roll + stat_mod(combatant["agi_stat"]) + initiative_bonus + status_init_mod
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
        # Stored as a fraction (0.05 = one additional natural-d20 face).
        threshold -= int(round(float(special.get("crit_chance_bonus", 0) or 0) * 20))
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
    """Handle the hits ac workflow."""
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
        sources += max(1, int(special.get(dtype_col) or 0))
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
    1. Attack roll vs AC
    2. Crit check
    3. Weapon damage roll + stat mod
    4. Resistance + weakness resolution
    5. Special item bonus damage (separate resistance check)
    6. Durability effects
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

    # --- Step 1: Attack roll vs AC ---
    attack_total, raw_d20, attack_mod = calc_attack_roll(attacker, attacker_weapon)
    attack_total += attack_bonus
    defender_ac   = calc_ac(defender, defender_armor)
    if active_buffs:
        defender_ac += sum(
            int(buff.get("value", 0)) for buff in active_buffs
            if buff.get("buff_type") == "BRACE_AC_BONUS"
        )
        defender_ac -= sum(
            int(buff.get("value", 0)) for buff in active_buffs
            if buff.get("buff_type") == "SWAP_GEAR_AC_PENALTY"
        )

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
    bonus_components = (attacker_special or {}).get("bonus_damage_components") or []
    if not bonus_components and attacker_special and attacker_special.get("bonus_damage_amount"):
        bonus_components = [{"amount": attacker_special["bonus_damage_amount"],
                             "type": attacker_special.get("bonus_damage_type", "")}]
    for component in bonus_components:
        raw_bonus = int(component.get("amount", 0) or 0) * (2 if is_crit else 1)
        bonus_type = component.get("type", "")
        if raw_bonus and bonus_type:
            final_bonus, bonus_res_note = resolve_resistance(
                raw_bonus, bonus_type, defender_armor, defender_special, boss_resistance_type
            )
            if boss:
                final_bonus, bonus_weak_note = resolve_weakness(final_bonus, bonus_type, boss)
            else:
                bonus_weak_note = ""
            bonus_dmg += final_bonus
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
                   defender_max_hp: int, attacker_current_hp: int | None = None,
                   defender_current_hp: int | None = None) -> tuple[float, float]:
    """Tiebreak score formula:
    (HP% * COMBAT_WIN_HP_WEIGHT) + (Damage Dealt% * COMBAT_WIN_DMG_WEIGHT)
    Always produces a winner."""
    settings   = get_all_settings()
    hp_weight  = settings.get("COMBAT_WIN_HP_WEIGHT",  cfg.COMBAT_WIN_HP_WEIGHT)
    dmg_weight = settings.get("COMBAT_WIN_DMG_WEIGHT", cfg.COMBAT_WIN_DMG_WEIGHT)

    att_hp = session["attacker_hp_start"] if attacker_current_hp is None else attacker_current_hp
    def_hp = session["defender_hp_start"] if defender_current_hp is None else defender_current_hp
    att_hp_pct = att_hp / attacker_max_hp if attacker_max_hp else 0
    def_hp_pct = def_hp / defender_max_hp if defender_max_hp else 0

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
    reduction = max(0.0, min(1.0, float(special["durability_reduction"])))
    reduced = base_loss * (1 - reduction)
    whole = int(reduced)
    # Probabilistic rounding lets protection affect ordinary one-point wear;
    # e.g. 25% protection prevents roughly one in four such losses.
    return whole + (1 if random.random() < reduced - whole else 0)


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
            """UPDATE players SET level = level + 1,
               pending_levelup = pending_levelup + 1,
               pending_perk = pending_perk + CASE WHEN ((level + 1) % 3)=0 THEN 1 ELSE 0 END
               WHERE id = ?""", (player_id,)
        )
    return True


################################################################################
