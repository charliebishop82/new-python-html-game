"""Build concise player-facing narrative text for combat outcomes."""
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
    """Build player-facing narrative text for combat intro."""
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
    """Build player-facing narrative text for round header."""
    return f"─── Round {round_num} ─────────────────────────────────────────────────────"


def combat_warning(warning_type: str, opponent_name: str = "",
                   level_diff: int = 0) -> str:
    """Build player-facing narrative text for combat warning."""
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

ATTACK_VERBS_MELEE  = ["swings", "strikes", "slashes", "lunges", "hammers"]
ATTACK_VERBS_RANGED = ["fires", "shoots", "takes aim", "blasts", "unleashes a shot"]
DODGE_VERBS         = ["sidesteps the attack", "ducks under the attack",
                       "narrowly evades", "deflects the blow", "rolls clear"]
HIT_VERBS           = ["connects with", "lands a hit on", "strikes", "hits"]


def attack_flavor(attacker_name: str, weapon_name: str,
                  weapon_type: str,
                  hit: bool, dodged: bool, is_crit: bool,
                  damage: int, damage_type: str,
                  res_note: str = "") -> str:
    """Build player-facing narrative text for attack flavor."""
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
    """Build player-facing narrative text for bonus damage flavor."""
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
    """Build player-facing narrative text for steal flavor."""
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

def brace_flavor(player_name: str, hp_restored: int, ac_bonus: int) -> str:
    """Build player-facing narrative text for brace flavor."""
    line = f"{player_name} takes a defensive stance, bracing for impact."
    if hp_restored:
        line += f" +{hp_restored} HP."
    line += f" AC+{ac_bonus} until the next attack resolves."
    return line


# ─────────────────────────────────────────────────────────────────────────────
# ESCAPE FLAVOR
# ─────────────────────────────────────────────────────────────────────────────

def escape_flavor(player_name: str, success: bool,
                  credits_lost: int = 0) -> str:
    """Build player-facing narrative text for escape flavor."""
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
    """Build player-facing narrative text for observe flavor."""
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
    """Build player-facing narrative text for swap gear flavor."""
    return (f"{player_name} quickly swaps to {new_item_name}. "
            f"Attack and AC reduced this round.")


# ─────────────────────────────────────────────────────────────────────────────
# BOSS SPECIAL MOVES
# ─────────────────────────────────────────────────────────────────────────────

def boss_special_attack_flavor(boss_name: str, attack_name: str,
                                damage: int, attack_flavor_text: str = "") -> str:
    """Build player-facing narrative text for boss special attack flavor."""
    line = f"★ {boss_name.upper()} uses {attack_name}!"
    if attack_flavor_text:
        line += f" {attack_flavor_text}"
    line += f" {damage} damage!"
    return line


def boss_special_buff_flavor(boss_name: str, buff_name: str,
                              buff_flavor_text: str = "") -> str:
    """Build player-facing narrative text for boss special buff flavor."""
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
    """Build player-facing narrative text for level up flavor."""
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


def hp_status(current_hp: int, max_hp: int) -> dict:
    """Return a deliberately imprecise five-segment health display."""
    pct = (current_hp / max_hp * 100) if max_hp else 0
    if pct >= 76:
        segments = 5
    elif pct >= 51:
        segments = 4
    elif pct >= 26:
        segments = 3
    elif pct >= 2:
        segments = 2
    else:
        segments = 1 if current_hp > 0 else 0
    return {
        "label": hp_descriptor(current_hp, max_hp),
        "meter": ("■" * segments) + ("□" * (5 - segments)),
    }


################################################################################
