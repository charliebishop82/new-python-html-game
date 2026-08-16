# Formula, Bonus, and Statistics Review — 2026-08-16

## Outcome

The active game rules are substantially connected and internally consistent. All 27 supported special-item/perk bonus fields are imported, stored, aggregated, and referenced by gameplay code. A live cross-check of all nine current characters found no disagreement between combat and the character screen for effective core attributes, maximum HP, Armor Class, capped AP, or passive HP regeneration.

No database values were changed during this review.

## Verification performed

- Compiled the complete Python codebase successfully.
- Traced each bonus from Excel import through database storage, perk scaling, equipped-item aggregation, player display, combat, rewards, economy, interruptions, scheduled maintenance, and NPC valuation.
- Ran read-only database integrity checks against the current `game.db`.
- Compared UI-derived and combat-derived statistics for every current player and NPC.
- Exercised the pure combat formulas for proficiency, weapon tiers, outfit tiers, natural 1/20 rules, resistance stacking, and weaknesses.
- Checked active weapons for malformed dice and unsupported damage types.
- Checked active typed special damage for unsupported damage types.
- Checked equipped inventory references and current HP caps.

## Confirmed working

### Core attributes

- **STR** affects melee attack, melee damage, and inventory capacity.
- **END** affects maximum HP, daily AP, AP-triggered healing, and midnight healing limits.
- **AGI** affects ranged attack, ranged damage, Armor Class, initiative, steal, escape, and observe.
- **LCK** affects critical range, steal/escape/observe contests, random events, repair bonuses, and some combat theft outcomes.
- **PER** affects observe, shop discount, and relevant encounter/opposed checks.
- Sex, class, assigned level-up points, equipment, perks, and temporary event modifiers reach the effective statistics used in combat.

### Equipment and perks

- Weapon, outfit, and special core-stat bonuses are each applied once.
- Permanent perk bonuses combine with the equipped special without replacing it.
- Perk bonus damage retains separate damage types, so multiple perks can be resisted or exploit weaknesses independently.
- Runtime perk scaling and caps are active. Large raw workbook values such as `+25 STR` become bounded effective values, currently capped at `+5` for a single core-stat perk.
- Weapon level damage bonuses follow `+0/+1/+2/+3/+4/+5` across levels 1–18.
- Outfit level AC bonuses follow `+0/+1/+2/+3` across levels 1–18.
- Active weapon dice and damage types are valid.

### Combat bonuses

- Initiative, extra attack, critical chance, critical damage, AC, typed bonus damage, resistances, weaknesses, steal bonus, and durability protection are connected to combat.
- A natural 20 always hits and a natural 1 always misses.
- One resistance source halves damage; two or more sources reduce it to the configured 25% floor.
- Creature weaknesses double post-resistance damage.
- Boss and minion resistance/weakness fields are used by the same attack engine.
- Player and NPC combat use the same equipped-stat and bonus aggregation.

### Rewards, economy, and encounters

- XP multipliers affect combat wins, successful steal XP, defeat XP, protagonist interruptions, and world-boss attempt XP.
- Credit multipliers affect enemy credit drops, enemy-combat steal fallback credits, protagonist interruptions, and world-boss attempt credits.
- Steal bonuses affect opposed rolls, item opportunity, and applicable stolen-credit percentages.
- Shop discount and sell bonus include both the equipped special and permanent perks.
- Bonus AP and HP regeneration are included in midnight/AP calculations.
- Encounter bonus affects interruption probability and random-event probability/alignment.
- NPC perk selection and equipment scoring recognize combat, growth, economy, and utility bonuses.

## Findings requiring correction or a decision

### 1. Daily AP equipment preview can display an uncapped value

**Priority: Medium — presentation and comparison accuracy**

The character/equipment derived-stat calculator displays raw daily AP without applying `AP_CARRYOVER_CAP` or the cursed reduction. The authoritative player/sidebar and midnight-award calculations do apply those limits. For example, a loadout may preview 41 AP while the actual cap remains 40. This can also make a shop item look like an upgrade when its AP bonus is currently absorbed by the cap.

Recommended correction: display both `Raw Daily AP` and `Effective Daily AP`, or cap the displayed value and label bonuses that are currently constrained by the cap. Cursed characters should show the reduced result.

Relevant code: `routes/character.py` derived-stat calculation versus `database.py` player calculation and `scheduler.py` midnight award.

### 2. Two public engine helpers no longer express the complete rules

**Priority: Medium — future regression risk**

`combat.engine.calc_max_ap()` and `calc_passive_regen()` are currently unused by operational gameplay. They omit parts of the modern aggregation unless callers first construct a specially augmented player/special profile. The live database, scheduler, and action code contain the complete formulas instead.

Recommended correction: replace duplicate implementations with shared authoritative helpers that explicitly accept effective END and the aggregated bonus profile. Then use those helpers in the database, character display, scheduler, and action paths.

### 3. AP bonuses can be valid but have no observable effect at the cap

**Priority: Low — rule clarity**

`bonus_ap` is correctly included before the 40 AP cap. Several current characters already reach that cap through END and other bonuses, so further AP bonuses do not increase their actual allowance. This is not a calculation failure, but the interface should state `+N AP (limited by cap)` when applicable.

### 4. Raw perk values remain intentionally much larger than runtime values

**Priority: Low — admin clarity**

The current database contains raw perk values as high as +25 core stats, +18 AC, +20 bonus damage, and +75% XP. Runtime scaling and per-effect caps reduce these before use, so players are not receiving the raw numbers. The admin inspector should clearly distinguish **authored value** from **effective scaled value** to prevent balancing mistakes.

### 5. Movement bonuses are not part of the operational vocabulary yet

**Priority: Deferred by design**

The game-board position and tile infrastructure exists, but there is no imported `movement_bonus` field in the active special/perk bonus vocabulary and no live movement action. This matches the decision to keep the board system inactive, but it remains future work rather than a currently working bonus.

## Balance observations—not wiring defects

- Active outfit authored AC ranges from 0 to 7 before the level-tier bonus. A level 16–18 outfit can therefore contribute up to 10 AC before AGI and special/perk AC. Natural 20 prevents complete invulnerability, but high-tier hit rates should be monitored.
- All active world bosses resist Ballistic damage, and most resist several other types. This makes weakness selection and typed bonus damage important, but can make a poorly matched loadout feel ineffective.
- Current bosses range from 65–262 HP; minions from 32–156 HP. These values are consistent with level progression but remain a tuning question rather than a formula defect.
- Current characters have no orphaned equipped items and none presently exceed their effective HP cap.

## Supporting audit files

- `review/formula_bonus_audit.py` — reusable read-only vocabulary/content audit.
- `review/formula_bonus_audit_results.json` — current database results.
- `review/formula_consistency_check.py` — reusable UI-versus-combat consistency test.

## Recommended next action

Fix the Daily AP preview first, then consolidate the duplicated AP/regen formulas into shared helpers. Those changes should not alter intended balance; they will make the displayed rules and future calculations harder to diverge.
