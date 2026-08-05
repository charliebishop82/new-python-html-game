# Movie Multiverse Gameplay Rules

This file is the maintainer index for formula-driven gameplay. Player wording lives in `templates/help/game_help.html`; administrator wording lives in `templates/admin/rules.html`. When a rule changes, update the calculation and both explanations in the same change.

## Canonical implementation map

- `combat/engine.py`: stat modifiers, HP, AP, AC, initiative, attacks, damage, criticals, resistance, weakness, dodge, opposed rolls, PvP scoring, durability, and XP scaling.
- `combat/actions.py`: action consequences, combat rewards, theft transfers, notifications, durability changes, and finalization.
- `routes/combat.py`: round order, initiative sequencing, round limits, rendering results, and readable daily round history.
- `routes/actions.py`: encounter entry, AP admission costs, random events, Boss/Minion/PvP selection, and Tavern behavior.
- `routes/shop.py` and `routes/blacksmith.py`: economy, selling, shop admission, and repairs.
- `npc.py`: automated decision flow. NPCs use normal action handlers and ordinary player resources.
- `config_defaults.py`: typed fallback values; database `settings` rows override these values.

## Documentation rules

1. Explain player decisions in plain language before showing a formula.
2. Display configurable values from the active settings dictionary rather than copying a number into a template.
3. Do not expose hidden opponent numbers that gameplay intentionally describes as health tiers or unknown intel.
4. Every administrative mutation needs a concise tooltip and an audit explanation where applicable.
5. A new flow or formula is incomplete until it has a player explanation, an admin reference, and a focused code docstring.

## Current formula summary

- Stat modifier: `floor(stat / 2)`.
- Maximum HP: `10 + END + (5 × level)`.
- Maximum AP: `BASE_DAILY_AP + floor(END / 2)`, capped by `AP_CARRYOVER_CAP`.
- Armor Class: `10 + floor(AGI / 2) + armor AC bonus`.
- Initiative: `d20 + floor(AGI / 2) + equipment/status bonuses`.
- Melee attack/damage uses STR; ranged attack/damage uses AGI.
- One resistance source halves matching damage; stacked sources use `RESISTANCE_STACK_MIN_DAMAGE_PERCENT`.
- Boss weakness doubles matching damage.
- Opposed actions use AGI and LCK; Observe additionally uses PER; ties fail for the actor.
- PvP round-limit score combines remaining HP percentage and share of damage dealt using the configured weights.
- XP starts with encounter-type XP per opponent level, adjusts for level difference, then applies equipment multipliers.

The player and administrator HTML guides contain the complete current flow descriptions.
