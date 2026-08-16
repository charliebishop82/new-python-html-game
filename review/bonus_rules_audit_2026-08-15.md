# Bonus Rules Audit — 2026-08-15

## Bonus sources

- Identity is applied once to the stored core statistic at character creation:
  Male +1 STR, Female +1 AGI, Other +1 LCK.
- Class and allocated level-up points are also stored in the core statistics.
- Active random-event effects are added when a player record is loaded.
- Equipped weapon, outfit, and special core-stat bonuses are added to effective
  combat and derived statistics.
- Permanent perks are scaled, capped, aggregated, and added to the same bonus
  profile as the equipped special item.

Because identity, class, and allocated points are part of the stored core
statistics, every formula using STR, END, AGI, LCK, or PER automatically uses
those creation bonuses. They must not be added again at runtime.

## Verified gameplay uses

| Bonus | Gameplay use |
| --- | --- |
| STR | Melee attack/damage and inventory capacity |
| END | Maximum HP, daily AP, passive regeneration |
| AGI | Ranged attack/damage, AC, initiative, opposed actions |
| LCK | Critical range, steals/escape/observe, repairs, random events |
| PER | Observe, shop discount, scene checks, minion interruption checks |
| Initiative | Combat initiative in all combat modes |
| AC | Defense from outfits, specials, and perks |
| Resistances | Typed damage reduction; matching sources stack |
| Bonus damage | Separate typed components with resistance/weakness resolution |
| Extra attack | One additional attack when the ability is active |
| Critical chance/damage | Critical threshold and additional critical damage |
| XP/credit multiplier | Combat action and combat completion rewards |
| Steal bonus | Steal rolls and applicable PvP credit seizure |
| Bonus AP | Daily AP calculation and reset |
| HP regeneration | AP-spend healing and displayed passive regeneration |
| Durability reduction | Probabilistic reduction of combat durability loss |
| Shop/sell bonus | Purchase discount and sale return |
| Encounter bonus | Random-event frequency/alignment and rarity calculations |

## Corrections made during this audit

1. PvP defenders now receive their special/perk initiative bonus. Previously
   only the initiating player received this otherwise-valid bonus.
2. Dormant Cinematic Scene combat now uses universal natural 20/natural 1 hit
   rules, applies all three actors' initiative bonuses, and applies critical
   damage multipliers. This does not enable Scenes in the player interface.
3. Authored boss and world-boss resistance flags now participate in typed
   damage reduction. Previously their weaknesses worked, but their base
   resistance columns were never supplied to the resistance calculation.

## Deliberate boundaries

- Reward multipliers currently describe and affect combat rewards. Contracts,
  crew dividends, auctions, and administrative grants are not multiplied.
- A resistance is a source-based flag, not a percentage. One source halves
  matching damage; multiple sources use the configured stacked-resistance floor.
- Core-stat bonuses are applied regardless of which equipped item supplied them.
- Boss/minion-associated loot is treated as the reward represented by that
  enemy, not as another complete equipped player loadout. Creature base stats,
  authored resistance/weakness fields, phase effects, and attack weapons remain
  the authoritative enemy combat profile; applying every loot bonus again would
  silently and substantially rebalance all imported encounters.
- Existing saved characters are not retroactively changed by the new identity
  rule; new player and NPC creation uses it automatically.
