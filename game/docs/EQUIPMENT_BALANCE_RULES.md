# Movie Multiverse Equipment Balance Rules

**Status:** Authoritative design reference  
**Version:** 1.0 — 2026-08-14  
**Applies to:** Excel content, importer validation, admin item editing, combat calculations, NPC item scoring, and future balancing.

## 1. Design intent

Equipment should create meaningful choices without making a character untouchable, guaranteeing victory, or allowing one reward to replace every other progression system.

- Ordinary equipment supports progression within its movie and level tier.
- Special items provide focused utility or one unusual combat advantage.
- World-boss rewards are the strongest individual items, but remain inside the game's bounded combat range.
- No item should make a natural 20 irrelevant. A natural 20 always hits and a natural 1 always misses.
- A reward may be broadly useful or exceptionally strong in one area, but should not be best in every area simultaneously.

## 2. Shared formulas and definitions

### Core attribute modifier

`stat modifier = floor(effective attribute / 2)`

Effective attributes include base statistics plus equipped weapon, armor, special-item, perk, and temporary-effect bonuses.

### Armor Class

`AC = 10 + floor(effective AGI / 2) + armor AC bonus + special AC bonus`

Because AGI and direct AC both increase Armor Class, an item that grants both must be budgeted more conservatively. Do not treat them as unrelated bonuses.

### Attack rolls

- Melee: `d20 + floor(effective STR / 2) + proficiency`
- Ranged: `d20 + floor(effective AGI / 2) + proficiency`
- Proficiency: `+2 at Level 1, then +1 every four levels`
- Natural 20: automatic hit and critical hit.
- Natural 1: automatic miss.

### Weapon damage

- Melee: `weapon die + floor(effective STR / 2)`
- Ranged: `weapon die + floor(effective AGI / 2)`
- A critical doubles weapon damage and typed bonus damage before resistance is applied.

### Resistance

- One resistance source halves matching damage, with a minimum of 1 damage.
- Two or more resistance sources use the configured stacked-resistance floor.
- Resistance breadth is part of an item's power budget. Broad resistance must be offset by lower AC, attributes, or utility.

## 3. Target combat ranges

These are design targets, not automatic hard caps. Any exception requires a documented reason and a combat review.

| Measure | Normal target | Exceptional target | Review threshold |
|---|---:|---:|---:|
| Active player AC | 14–20 | 21–24 | 25 or higher |
| Ordinary armor AC bonus | 1–4 | — | Above 4 |
| World-boss armor AC bonus | 5–7 | 7 | Above 7 |
| Ordinary item single attribute | 0–4 | 5 on a signature weapon | Above 5 |
| World-boss item single attribute | 0–3 | 4 on a signature weapon | Above 4 |
| Ordinary special typed damage | 0–5 | 5 | Above 5 |
| World-boss special typed damage | 5–7 | 7 | Above 7 |

An AC above 24 is not forbidden, but it must be intentional, temporary, or costly. Permanent AC in the 30s is prohibited.

## 4. Weapons

Weapons define the primary damage die, damage type, attack attribute, and supporting attributes.

### Ordinary weapons

- Typical damage dice: d4 through d10.
- Maximum recommended attribute total: 8.
- Maximum recommended single attribute: +4.
- A signature weapon may reach +5 in its primary attribute only if its other bonuses are reduced.
- Avoid giving strong bonuses to both STR and AGI unless the total attribute budget remains unchanged.

### World-boss weapons

- Damage die: d12.
- Recommended attribute total: 10–12.
- Maximum single attribute: +4.
- Item level should normally equal the associated world-boss level plus 3.
- A world-boss weapon should be stronger than an ordinary weapon through damage and a clear attribute profile—not through five oversized attributes.

## 5. Armor and outfits

Armor contributes direct AC, attributes, and resistances.

### Ordinary armor

- Direct AC bonus: +1 to +4.
- Maximum recommended attribute total: 6.
- Maximum recommended single attribute: +3.
- One to three relevant resistances is normal; broader resistance should reduce other bonuses.

### World-boss armor

- Direct AC bonus: +5 to +7.
- Recommended attribute total: 7–10.
- Maximum single attribute: +3.
- Item level should normally equal the associated world-boss level plus 3.
- Broad thematic resistance is allowed, but AC and AGI must not both sit at the top of their ranges.
- +7 AC is reserved for the most defensive world-boss reward.

### Double-counting warning

Every +2 AGI adds approximately +1 AC and may also improve ranged attacks, initiative, dodge-related checks, and other AGI-based calculations. When armor grants AGI, count that implied AC against its defensive budget.

## 6. Special items

Special items should provide focused utility. Ordinary specials may break one normal rule; world-boss specials may combine several restrained benefits.

### Ordinary special guidelines

| Bonus | Normal maximum |
|---|---:|
| Total core attributes | 6 |
| Single core attribute | +4 |
| Initiative | +3 |
| AC | +2 |
| Typed bonus damage | +5 |
| Critical chance | +5 percentage points |
| Critical damage multiplier | +0.25 |
| XP multiplier | +15% |
| Credit multiplier | +10% |
| Bonus AP | +2 |
| HP regeneration | +4 |
| Durability reduction | 15% |
| Shop discount | 10% |
| Sell bonus | 10% |
| Encounter modifier | 15% |

An ordinary special should normally use only a subset of these maxima.

### World-boss special guidelines

- Core attribute total: 8–11; no single attribute above +3.
- Initiative: +2 to +3.
- AC: +2 to +3.
- Typed bonus damage: +5 to +7.
- Critical chance: no more than +5 percentage points.
- Critical damage multiplier: no more than +0.25.
- XP and credit multipliers: normally +10% each.
- Bonus AP: +2.
- HP regeneration: +1.
- Durability reduction: 10%.
- Shop discount: 5%; sell bonus: 10%; encounter modifier: 10%.
- Thematic resistances may remain broad because only one special can be equipped.

### Extra attacks

`ExtraAttack` grants another complete attack and is therefore one of the strongest binary effects in the game.

- Never combine ExtraAttack with world-boss-level AC, large typed damage, broad attributes, and economy multipliers.
- World-boss specials do not receive unconditional ExtraAttack under the current balance model.
- An ordinary special with ExtraAttack must have a deliberately reduced bonus package and requires a combat test.
- Multiple ExtraAttack sources must not stack into multiple additional attacks.

## 7. Stacking rules and total-load review

Equipment must be reviewed as a full loadout, not one row at a time.

1. Add weapon, armor, special, perk, and temporary bonuses to obtain effective attributes.
2. Calculate AC using effective AGI plus direct armor and special AC.
3. Calculate melee and ranged attack modifiers.
4. Calculate normal and critical damage, including every typed bonus-damage component.
5. Count resistance sources by damage type.
6. Add economy and AP effects separately.
7. Flag the loadout if it crosses a review threshold or dominates offense, defense, and economy simultaneously.

No single item should simultaneously provide all of the following:

- Top-tier direct AC.
- Top-tier AGI.
- ExtraAttack.
- Top-tier typed bonus damage.
- Broad resistance.
- Large XP, credit, AP, healing, and shop bonuses.

## 8. Item-tier budgets

Use these budgets as practical authoring guidance.

| Tier | Expected role | Attribute budget | Defensive budget | Utility budget |
|---|---|---:|---|---|
| Starter | Establishes a build | 0–2 total | AC +0–1 or one resistance | Minimal |
| Ordinary | Supports progression | 3–6 total | AC +1–3 or focused resistance | One small effect |
| High-tier ordinary | Strong movie reward | 6–8 total | AC +3–4 or several resistances | One meaningful effect |
| World-boss | Best-in-slot candidate | 8–12 total | AC +5–7 or broad resistance | Several restrained effects |

The budgets are alternatives, not shopping lists. An item at the top of one column should usually be below the top in another.

## 9. Import and admin validation

Future importer or admin validation should warn—not necessarily reject—when:

- Ordinary armor has more than +4 AC.
- World-boss armor has more than +7 AC.
- Any permanent item grants more than +5 to one core attribute.
- A world-boss item grants more than +4 to one core attribute.
- A special grants ExtraAttack plus typed damage above +3.
- A special grants ExtraAttack plus direct AC above +1.
- An item has an unusually high total attribute budget.
- A projected equipped loadout reaches AC 25 or higher.
- A single item is simultaneously top-tier in offense, defense, and economy.

Warnings should identify the item, the exceeded threshold, and the projected consequence.

## 10. Balance review checklist

Before importing or approving equipment:

- Confirm association, item tier, level, slot, and uniqueness.
- Confirm the damage die and damage type.
- Sum all five core attributes.
- Calculate implied AC from AGI and add direct AC.
- Count resistance types.
- Review critical, extra-attack, and typed-damage interactions.
- Review AP, healing, XP, credit, shop, and durability effects.
- Compare against the strongest existing item in the same slot and tier.
- Test a representative low-, mid-, and high-level loadout.
- Test against a player, NPC, ordinary boss, and world boss where relevant.
- Confirm that natural 20 and natural 1 behavior remains universal.
- Record any approved exception in this document or a linked balance note.

## 11. Current world-boss reward baseline

As of version 1.0:

- World-boss weapons use d12 and carry 10–12 total attribute points.
- World-boss armor provides +5 to +7 AC and 7–10 total attribute points.
- World-boss specials provide +2 to +3 AC, +5 to +7 typed damage, restrained attributes, and no unconditional extra attack.
- Existing equipped rewards use these definitions immediately because inventory entries reference shared item records.

This section describes the current baseline. If the combat model changes, update both the formulas and the permitted ranges in this document.
