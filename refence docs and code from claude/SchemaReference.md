# Database Schema Reference

**Project:** BBS-Inspired Multiplayer Dueling Game
**Database:** SQLite
**Status:** Living document — updated as schema decisions are made during design sessions.

This document tracks every table, its columns, relationships, and any special handling notes (derived fields, cleanup rules, permanence, etc.) discussed during design. All sections including Excel-imported content tables (Section 6) are now finalized. See GameContent_Template.xlsx for the corresponding spreadsheet structure.

---

## Table of Contents

1. [Players & Identity](#1-players--identity)
2. [Combat](#2-combat)
3. [Inventory & Items](#3-inventory--items)
4. [Economy](#4-economy)
5. [Feeds](#5-feeds)
6. [Excel-Imported Content Tables](#6-excel-imported-content-tables)
7. [Open Questions / TODO](#7-open-questions--todo)
8. [Decision Log](#8-decision-log)

---

## 1. Players & Identity

### `players`
Core identity and live combat-relevant state. Kept lean — anything purely cumulative/historical lives in `player_stats` instead.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| username | TEXT UNIQUE NOT NULL | **Permanent**, cannot be changed |
| password_hash | TEXT NOT NULL | |
| email | TEXT UNIQUE NOT NULL | Required at registration (for password recovery) |
| character_name | TEXT NOT NULL | **Permanent**, cannot be changed |
| sex | TEXT NOT NULL | |
| class_id | INTEGER NOT NULL FK → classes.id | **Permanent**, cannot be changed |
| str_stat / end_stat / agi_stat / lck_stat / per_stat | INTEGER NOT NULL DEFAULT 1 | Current totals: base 1 + class bonus + creation points (10) + level-up points |
| level | INTEGER NOT NULL DEFAULT 1 | Max 15, but XP keeps accumulating past cap |
| xp | INTEGER NOT NULL DEFAULT 0 | Floors at 0, never negative |
| current_hp | INTEGER NOT NULL | |
| current_ap | INTEGER NOT NULL | |
| credits | INTEGER NOT NULL DEFAULT 25 | Floors at 0, never negative |
| equipped_weapon_id | INTEGER FK → inventory_items.id | Nullable (unarmed allowed) |
| equipped_armor_id | INTEGER FK → inventory_items.id | Nullable (unarmored allowed) |
| equipped_special_id | INTEGER FK → inventory_items.id | Nullable |
| in_combat | BOOLEAN NOT NULL DEFAULT FALSE | Atomically managed by queue script |
| pending_levelup | BOOLEAN NOT NULL DEFAULT FALSE | Set TRUE when XP crosses a level threshold; cleared when stat point assigned. Checked on every request via before_request hook — redirects to /levelup if TRUE and in_combat is FALSE. |
| combat_preference | TEXT NOT NULL DEFAULT 'Balanced' | Aggressive / Defensive / Opportunist / Balanced |
| is_banned | BOOLEAN NOT NULL DEFAULT FALSE | Row retained, not deleted, on ban |
| last_login_at | DATETIME | Used to derive inactive status |
| created_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Derived fields (never stored, calculated on demand):**
- `max_hp` = `10 + end_stat + (5 * level)`
- `max_ap` = `BASE_DAILY_AP + floor(end_stat/2)`, reduced by `CURSE_AP_REDUCTION` if Cursed status active
- `inventory_limit` = `INVENTORY_LIMIT + floor(str_stat/2)`
- `is_inactive` = `(NOW - last_login_at) >= INACTIVE_DAYS_THRESHOLD` (7 days)
- AC, attack modifiers, dodge chance, etc. — all derived live at combat-time from stats + equipped gear, never cached

**On ban:** credits set to 0, all `inventory_items` rows deleted, special items released back to `special_item_registry` (status → `IN_POOL`), `in_combat` cleared.

---

### `player_stats`
One row per player (1:1, PK = player_id). Home for cumulative counters not naturally derivable elsewhere.

| Column | Type | Notes |
|---|---|---|
| player_id | INTEGER PK FK → players.id | |
| pvp_kills | INTEGER NOT NULL DEFAULT 0 | |
| times_reduced_to_1hp | INTEGER NOT NULL DEFAULT 0 | "Deaths" / Shame Board |
| updated_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Leaderboards NOT requiring a stored table (computed live via query):**
| Leaderboard | Query basis |
|---|---|
| Most Credits | `ORDER BY players.credits DESC` |
| Top Level / XP | `ORDER BY players.level DESC, players.xp DESC` |
| Most Boss Kills (Global) | `SUM(boss_instances.kill_count) GROUP BY player_id` |
| Most Boss Kills (Per Boss) | `boss_instances WHERE boss_id = X ORDER BY kill_count DESC` |
| Most Minion Kills (Global/Per Minion) | same pattern using `minion_instances` |

All leaderboard queries exclude players where `is_inactive = TRUE`.

---

### `level_up_history`
Audit-only. Never read during normal gameplay — QC/debugging purposes only.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| player_id | INTEGER NOT NULL FK → players.id | |
| level_reached | INTEGER NOT NULL | |
| stat_increased | TEXT NOT NULL | One of STR/END/AGI/LCK/PER |
| timestamp | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

---

### `status_effects`
Player-only effects that persist **outside** of combat. Currently only one effect type exists (Cursed), with room to grow.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| player_id | INTEGER NOT NULL FK → players.id | |
| effect_type | TEXT NOT NULL | Currently only `'CURSED'` |
| value | REAL NOT NULL | Magnitude (e.g. 0.20 for 20% AP reduction) |
| created_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Cleanup rule:** Every row in this table is, by definition, cleared in **Step 0** of the UTC midnight reset sequence. No `expiry_type` column needed since nothing in this table persists past one day.

---

### `combat_buffs`
Combat-scoped buffs/penalties tied to one active fight, applying to either the attacker or defender side (covers both player Brace effects and boss/minion special buffs).

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| combat_session_id | INTEGER NOT NULL FK → combat_sessions.id | |
| side | TEXT NOT NULL | `'ATTACKER'` or `'DEFENDER'` (relative to the session) |
| buff_type | TEXT NOT NULL | See full list below |
| damage_type | TEXT | Only used for `BOSS_RESISTANCE_TYPE` |
| value | REAL NOT NULL | |
| expires_on | TEXT NOT NULL | `NEXT_HIT_RESOLVED` / `END_OF_ROUND` / `END_OF_COMBAT` |
| created_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**buff_type values:**
`BRACE_AC_BONUS`, `BRACE_DODGE_BONUS`, `SWAP_GEAR_ACCURACY_PENALTY`, `SWAP_GEAR_AC_PENALTY`, `ESCAPE_FAIL_AC_PENALTY`, `STEAL_FAIL_AC_PENALTY`, `BOSS_AC_BONUS`, `BOSS_DMG_REDUCTION`, `BOSS_ATTACK_BONUS`, `BOSS_CRIT_BONUS`, `BOSS_RESISTANCE_TYPE`, `BOSS_HP_RESTORE_APPLIED`

**Cleanup rule:** All rows deleted when the parent `combat_session` ends or is cancelled (`DELETE WHERE combat_session_id = X`).

---

## 2. Combat

### `combat_sessions`
The central record of an active or completed fight.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| combat_type | TEXT NOT NULL | `'PVP'` / `'BOSS'` / `'MINION'` |
| attacker_player_id | INTEGER NOT NULL FK → players.id | |
| defender_player_id | INTEGER FK → players.id | NULL unless PVP |
| boss_instance_id | INTEGER FK → boss_instances.id | NULL unless BOSS |
| minion_instance_id | INTEGER FK → minion_instances.id | NULL unless MINION |
| status | TEXT NOT NULL DEFAULT 'ACTIVE' | `ACTIVE` / `RESOLVED` / `CANCELLED` |
| current_round | INTEGER NOT NULL DEFAULT 1 | |
| rounds_extended | INTEGER NOT NULL DEFAULT 0 | PvP only |
| attacker_hp_start | INTEGER NOT NULL | |
| defender_hp_start | INTEGER | NULL if vs boss/minion (HP lives on the instance row) |
| attacker_total_damage_dealt | INTEGER NOT NULL DEFAULT 0 | Tracked universally across ALL combat types (PvP, Boss, Minion) for consistency — used for PvP score formula, also useful for QC/logs on boss/minion fights |
| defender_total_damage_dealt | INTEGER NOT NULL DEFAULT 0 | Same as above |
| attacker_observed | BOOLEAN NOT NULL DEFAULT FALSE | Successful Observe this session |
| result | TEXT | NULL while ACTIVE. Set on resolution: 1HP_WIN / SCORE_WIN / ESCAPE / CANCELLED. Determines post-combat logic path. |
| defender_observed | BOOLEAN NOT NULL DEFAULT FALSE | |
| started_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| resolved_at | DATETIME | |

**Cancellation rule:** On disconnection or server downtime, status → `CANCELLED`, AP refunded, `in_combat` cleared for both sides, no feed/log entries persist as "happened" (though raw `combat_logs` rows for that session may still exist — see note in that table).

---

### `boss_instances`
Tracks one player's current attempt at one specific boss. Doubles as combat state + discovery/progress tracker.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| player_id | INTEGER NOT NULL FK → players.id | |
| boss_id | INTEGER NOT NULL FK → bosses.id | |
| current_hp | INTEGER NOT NULL | Reset to max on new fight |
| special_attack_used | BOOLEAN NOT NULL DEFAULT FALSE | One-use per fight, reset on new fight |
| special_buff_used | BOOLEAN NOT NULL DEFAULT FALSE | One-use per fight, reset on new fight |
| current_phase | INTEGER NOT NULL DEFAULT 1 | Reset on new fight |
| discovered_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | First encounter; used for "previously encountered" return-visit list |
| kill_count | INTEGER NOT NULL DEFAULT 0 | Per-boss leaderboard input |
| UNIQUE(player_id, boss_id) | | One row per player/boss pair |

**Reset rule:** `current_hp`, `special_attack_used`, `special_buff_used`, `current_phase` all reset to fresh values immediately whenever a new fight against this boss begins (on defeat, escape, disconnect, or server downtime ending the prior attempt).

---

### `minion_instances`
Same pattern as `boss_instances` but simpler — no phases or specials since minions don't have them.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| player_id | INTEGER NOT NULL FK → players.id | |
| minion_id | INTEGER NOT NULL FK → minions.id | |
| current_hp | INTEGER NOT NULL | |
| discovered_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| kill_count | INTEGER NOT NULL DEFAULT 0 | |
| UNIQUE(player_id, minion_id) | | |

---

### `boss_intel`
Permanent record of which bosses a player has successfully Observed. Deliberately decoupled from `boss_instances` so it survives even if combat state ever needed to reset independently.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| player_id | INTEGER NOT NULL FK → players.id | |
| boss_id | INTEGER NOT NULL FK → bosses.id | |
| learned_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| UNIQUE(player_id, boss_id) | | Row existence = intel known |

**No minion equivalent** — minions have no resistances/weaknesses to reveal. Observing a minion only reveals exact HP for that session (temporary, lives in `combat_sessions`/UI state, not persisted).

---

### `combat_logs`
Full round-by-round detail of every action and roll. **Permanent — never purged**, unlike the ephemeral `daily_feed`. This is the forensic/QC record; `daily_feed` just holds a one-line summary linking back here via `combat_session_id`.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| combat_session_id | INTEGER NOT NULL FK → combat_sessions.id | |
| round_number | INTEGER NOT NULL | |
| actor | TEXT NOT NULL | `'ATTACKER'` or `'DEFENDER'` |
| action_type | TEXT NOT NULL | `ATTACK` / `STEAL` / `BRACE` / `ESCAPE` / `SWAP_GEAR` / `OBSERVE` / `SPECIAL_ATTACK` / `SPECIAL_BUFF` |
| roll_detail | TEXT NOT NULL | Rendered text, e.g. `"Attack roll: 16+4=20 vs AC 15 — Hit!"` |
| outcome_detail | TEXT NOT NULL | Rendered text, e.g. `"8 Energy damage dealt. Resisted, halved to 4."` |
| hp_after_attacker | INTEGER | |
| hp_after_defender | INTEGER | |
| created_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

---

## 3. Inventory & Items

### `inventory_items`
One row = one physical item instance. Regular gear (weapons/armor) can have many simultaneous copies across different rows; special items are constrained to exactly one row in existence at a time (enforced by `special_item_registry`, not by this table itself).

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| player_id | INTEGER NOT NULL FK → players.id | |
| item_type | TEXT NOT NULL | `'WEAPON'` / `'ARMOR'` / `'SPECIAL'` |
| item_id | INTEGER NOT NULL | Polymorphic FK → weapons.id / armor.id / special_items.id depending on item_type |
| current_durability | INTEGER NOT NULL DEFAULT 100 | |
| acquired_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| acquired_method | TEXT NOT NULL | `STARTER` / `BOSS_DROP` / `MINION_DROP` / `PVP_STEAL` / `SHOP_PURCHASE` / `RANDOM_EVENT` / `COMBAT_STEAL` |

**Equipped status is NOT stored here** — determined entirely by whether this row's `id` matches `players.equipped_weapon_id` / `equipped_armor_id` / `equipped_special_id`. Avoids a duplicate source of truth.

**Cleanup on destroy/drop/sell:** Row deleted. If it was an equipped item, the application logic must also NULL out the corresponding `players.equipped_*_id` column. If it was a special item, `special_item_registry` status must be updated accordingly.

---

### `item_history`
**Permanent**, append-only audit trail for admin/QC lookup. Distinct from the ephemeral `daily_feed`.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| player_id | INTEGER NOT NULL FK → players.id | |
| item_type | TEXT NOT NULL | |
| item_id | INTEGER NOT NULL | |
| item_name | TEXT NOT NULL | Denormalized snapshot (survives content changes later) |
| event_type | TEXT NOT NULL | See full list below |
| credit_amount | INTEGER | Relevant for PURCHASED/SOLD, NULL otherwise |
| related_player_id | INTEGER FK → players.id | The other party for STOLEN_FROM_ME / STOLEN_BY_ME |
| occurred_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**event_type values:**
`PURCHASED`, `SOLD`, `DROPPED`, `DESTROYED`, `STOLEN_FROM_ME`, `STOLEN_BY_ME`, `RECEIVED_BOSS_DROP`, `RECEIVED_MINION_DROP`, `RECEIVED_RANDOM_EVENT`, `RECEIVED_STARTER`, `RECEIVED_COMBAT_STEAL`

> `RECEIVED_COMBAT_STEAL` is distinct from `RECEIVED_BOSS_DROP`/`RECEIVED_MINION_DROP` — it specifically covers the in-combat Steal action yielding a boss/minion's special item, which can happen even without defeating them (e.g. stealing then fleeing).

---

### `special_item_registry`
Enforces global uniqueness: only one copy of each special item can exist in the world at a time. One permanent row per special item definition, created at Excel import, never deleted.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| special_item_id | INTEGER NOT NULL UNIQUE FK → special_items.id | |
| status | TEXT NOT NULL DEFAULT 'IN_POOL' | `IN_POOL` / `IN_INVENTORY` / `IN_SHOP` |
| current_owner_player_id | INTEGER FK → players.id | Set only if `IN_INVENTORY` |
| inventory_item_id | INTEGER FK → inventory_items.id | The actual instance row, if owned |
| shop_listing_price | INTEGER | Set only if `IN_SHOP` |
| last_acquired_method | TEXT | `BOSS_DROP` / `MINION_DROP` / `PVP_STEAL` / `SHOP_PURCHASE` / `COMBAT_STEAL` / `RANDOM_EVENT` |
| last_released_method | TEXT | `SOLD` / `DROPPED` / `DESTROYED`, NULL if never released |
| updated_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Equipped status NOT tracked here** — redundant with `players.equipped_special_id`. Equipped-or-not doesn't matter to the registry; it only cares about the three statuses above.

**Race condition handling:** When awarding a special item, the queue script performs an atomic check-and-set on `status` here before creating the `inventory_items` row. A second simultaneous claimant naturally fails the check and falls back to the next available item or a credits/XP consolation reward — entirely transparent to the player.

**On sell-to-shop:** `inventory_items` row is deleted immediately (no orphan-linking), a `shop_listings` row is created with `durability_at_listing` snapshotting the current durability, and registry `status` → `IN_SHOP`.

---

## 4. Economy

### `shop_listings`
Both the daily rotation (weapons/armor) and player-sold listings (including special items) live in the same table. A row is deleted the instant it's purchased — no "sold" status needed.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| item_type | TEXT NOT NULL | `'WEAPON'` / `'ARMOR'` / `'SPECIAL'` |
| item_id | INTEGER NOT NULL | |
| listing_source | TEXT NOT NULL | `'DAILY_ROTATION'` or `'PLAYER_SOLD'` |
| seller_player_id | INTEGER FK → players.id | Set only if `PLAYER_SOLD` |
| durability_at_listing | INTEGER | NULL for `DAILY_ROTATION` (always fresh/100); snapshot value for `PLAYER_SOLD` |
| price | INTEGER NOT NULL | Base price; discounts (PER, Shop Discount modifier) applied at purchase time, not stored here |
| listed_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Daily rotation refresh:** At UTC midnight, all `DAILY_ROTATION` rows deleted and replaced with `SHOP_WEAPONS_COUNT` (10) fresh weapon rows + `SHOP_ARMOR_COUNT` (10) fresh armor rows.

**Special item slot cap:** Not a separate column — enforced by the queue script capping how many `item_type='SPECIAL'` rows can exist at once, at `floor(current_player_count / 2)`.

**Purchase flow:** Delete `shop_listings` row → create `inventory_items` row (durability = `durability_at_listing` if set, else 100) → if `item_type='SPECIAL'`, update `special_item_registry` (`status` → `IN_INVENTORY`, set `inventory_item_id`).

---

## 5. Feeds

### `daily_feed`
The **only** truly ephemeral table in the schema — fully cleared at UTC midnight (optionally archived to file first if `LOG_DAILY_ARCHIVE` is enabled). Drives the live-scrolling feed UI.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| feed_scope | TEXT NOT NULL | `'GLOBAL'` or `'PERSONAL'` |
| player_id | INTEGER FK → players.id | NULL if GLOBAL |
| flavor_text | TEXT NOT NULL | Rendered LORD-style narrative line |
| event_category | TEXT NOT NULL | `COMBAT` / `ITEM` / `LEVEL_UP` / `RANDOM_EVENT` / `SYSTEM` |
| combat_session_id | INTEGER FK → combat_sessions.id | NULL unless this entry summarizes a fight (links to full `combat_logs` detail) |
| occurred_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Design note:** A single combat result may insert multiple rows — one `GLOBAL` entry for the world feed, plus one `PERSONAL` entry for each participant — rather than sharing one row across views.

**Cleanup:** `DELETE FROM daily_feed` as part of the midnight reset sequence. If `LOG_DAILY_ARCHIVE` is enabled, export first to `LOG_ARCHIVE_PATH/game_log_YYYY_MM_DD.txt`. Note: `item_history` and `combat_logs` remain the actual permanent record — the daily archive file is a convenience export of rendered feed text, not the canonical source.

---

## 6. Excel-Imported Content Tables

### 6.1 Import & Refresh Model

Two distinct admin operations exist, with very different scope:

**A. Daily Content Refresh (routine)**
- Admin uploads a `.xlsx` file to a known staging path at any time during the day — it has no effect until applied.
- At UTC midnight reset, as one step in the sequence, the job checks for a staged file.
- If present: parse and validate the **entire** file (all sheets, required columns, cross-references).
  - **Valid:** apply all changes atomically inside one DB transaction. Matching is by `name` (unique key) — existing rows are **updated in place**, new names are **inserted**. The rest of the midnight reset sequence proceeds normally either way.
  - **Invalid:** reject the entire import, leave live content completely untouched, write an error log entry for the admin to review. The rest of the midnight reset sequence (AP, HP, shop rotation, etc.) still proceeds unaffected.
- **This path never deletes rows.** If a name present in the *current* live tables is missing from the new upload, that row is simply left alone — no automatic deactivation, no cascade. Excel-driven refresh is strictly additive/modifying.
- **Boss intel exception:** if a re-imported boss row's resistance/weakness columns (`res_*`, `weak_*`) OR its Special Attack/Buff damage-type columns differ from the previous live values, all `boss_intel` rows for that `boss_id` are cleared (player must re-Observe to relearn). Any other column changing (HP, stats, flavor text, drop rates, etc.) does **not** clear intel.

**B. Full Game Reset (rare, deliberate)**
- A separate, explicit admin action — not triggered by an Excel upload.
- Wipes `players` and everything that cascades from it (inventory, instances, history, feeds — effectively the entire operational dataset).
- Content tables are then reseeded fresh from the provided Excel file with no name-matching constraints — this is the only path where content can be freely renamed, restructured, or have items removed outright, since there's no live player data left to protect.
- Used for major overhauls (e.g. swapping the entire movie roster), not routine balance tweaks.

**`is_active` flag:** Every content table below carries a simple `is_active BOOLEAN` column as a manual admin escape hatch (e.g. temporarily hiding a broken boss from new discovery/rotation without a full reset). It is **never** set automatically by the daily refresh import — only by direct admin action via the local admin tools. Default `TRUE`.

---

### 6.2 `bosses`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT UNIQUE NOT NULL | Matched on import |
| is_active | BOOLEAN NOT NULL DEFAULT TRUE | Manual admin toggle only |
| level | INTEGER NOT NULL | 1-15 |
| str_stat / end_stat / agi_stat / lck_stat / per_stat | INTEGER NOT NULL | Same formulas as players |
| max_hp | INTEGER NOT NULL | Set directly by admin, not derived |
| phase2_hp_percent / phase3_hp_percent | INTEGER NOT NULL | HP% thresholds that trigger phase changes |
| special_attack_name / special_attack_die / special_attack_damage_type / special_attack_flavor | TEXT NOT NULL | One-time special attack |
| special_buff_name / special_buff_type / special_buff_value / special_buff_flavor | TEXT/REAL NOT NULL | One-time special buff |
| special_buff_damage_type | TEXT | Only used if `special_buff_type = 'RESISTANCE_TYPE'` |
| res_blade / res_blunt / res_ballistic / res_energy / res_arcane / res_explosive / res_venom | BOOLEAN NOT NULL DEFAULT FALSE | |
| weak_blade / weak_blunt / weak_ballistic / weak_energy / weak_arcane / weak_explosive / weak_venom | BOOLEAN NOT NULL DEFAULT FALSE | |
| drop_weapon_chance / drop_armor_chance / drop_special_item_chance | REAL NOT NULL | Independent rolls, 0-1 |
| drop_credit_min / drop_credit_max | INTEGER NOT NULL | Credits always awarded on kill |
| flavor_text | TEXT NOT NULL | |
| imported_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Intel-sensitive columns** (changing any of these clears `boss_intel` for this boss): all `res_*`, all `weak_*`, `special_attack_damage_type`, `special_buff_damage_type`.

---

### 6.3 `minions`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT UNIQUE NOT NULL | |
| is_active | BOOLEAN NOT NULL DEFAULT TRUE | |
| level | INTEGER NOT NULL | |
| str_stat / end_stat / agi_stat / lck_stat / per_stat | INTEGER NOT NULL | Same formulas as players; minions use the same Melee/STR vs Ranged/AGI weapon split since their weapon is lootable |
| max_hp | INTEGER NOT NULL | |
| drop_weapon_chance / drop_armor_chance / drop_special_item_chance | REAL NOT NULL | |
| drop_credit_min / drop_credit_max | INTEGER NOT NULL | |
| flavor_text | TEXT NOT NULL | |
| imported_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

No phases, no special attack/buff, no resistances/weaknesses — minions are intentionally simpler than bosses.

---

### 6.4 `weapons`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT UNIQUE NOT NULL | |
| is_active | BOOLEAN NOT NULL DEFAULT TRUE | |
| level | INTEGER NOT NULL | |
| weapon_type | TEXT NOT NULL | `'Melee'` or `'Ranged'` |
| damage_die | TEXT NOT NULL | `d4`/`d6`/`d8`/`d10`/`d12` |
| damage_type | TEXT NOT NULL | One of the 7 damage types |
| str_bonus / end_bonus / agi_bonus / lck_bonus / per_bonus | INTEGER NOT NULL DEFAULT 0 | Flat bonus while equipped |
| associated_to | TEXT | Informational only, e.g. `"The Predator (Boss)"`; auto-derivable from `master` but stored for convenience/display |
| credit_cost | INTEGER NOT NULL | |
| drop_chance | REAL NOT NULL | Applies ONLY to its associated boss/minion's defeat drop table, not the Shop daily rotation |
| starting_durability | INTEGER NOT NULL DEFAULT 100 | |
| imported_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

---

### 6.5 `armor`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT UNIQUE NOT NULL | |
| is_active | BOOLEAN NOT NULL DEFAULT TRUE | |
| level | INTEGER NOT NULL | |
| ac_bonus | INTEGER NOT NULL DEFAULT 0 | |
| res_blade / res_blunt / res_ballistic / res_energy / res_arcane / res_explosive / res_venom | BOOLEAN NOT NULL DEFAULT FALSE | Stacks with special item resistance to quarter damage (floored at `RESISTANCE_STACK_MIN_DAMAGE_PERCENT`) |
| str_bonus / end_bonus / agi_bonus / lck_bonus / per_bonus | INTEGER NOT NULL DEFAULT 0 | |
| associated_to | TEXT | Informational only |
| credit_cost | INTEGER NOT NULL | |
| drop_chance | REAL NOT NULL | Boss/minion drop table only, same caveat as weapons |
| starting_durability | INTEGER NOT NULL DEFAULT 100 | |
| imported_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

---

### 6.6 `special_items`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT UNIQUE NOT NULL | |
| is_active | BOOLEAN NOT NULL DEFAULT TRUE | |
| associated_to | TEXT NOT NULL | Required (unlike weapons/armor) — every special item belongs to exactly one boss or minion |
| association_type | TEXT NOT NULL | `'Boss'` or `'Minion'` |
| str_bonus / end_bonus / agi_bonus / lck_bonus / per_bonus | INTEGER NOT NULL DEFAULT 0 | |
| initiative_bonus | INTEGER NOT NULL DEFAULT 0 | Turn order only — does NOT apply to the dodge attacker roll |
| extra_attack | BOOLEAN NOT NULL DEFAULT FALSE | Two full independent attacks every round for the whole fight |
| crit_chance_bonus | REAL NOT NULL DEFAULT 0 | Expands crit range beyond the LCK formula |
| crit_dmg_multiplier | REAL NOT NULL DEFAULT 0 | Additional multiplier; applies to both weapon AND bonus damage on a crit |
| ac_bonus | INTEGER NOT NULL DEFAULT 0 | |
| res_blade / res_blunt / res_ballistic / res_energy / res_arcane / res_explosive / res_venom | BOOLEAN NOT NULL DEFAULT FALSE | Stacks with armor resistance |
| bonus_damage_type | TEXT | Nullable; one of 7 damage types |
| bonus_damage_amount | INTEGER NOT NULL DEFAULT 0 | Resolved with its own resistance/weakness check, independent of base weapon damage |
| xp_multiplier | REAL NOT NULL DEFAULT 0 | Applies to ALL XP sources (PvP, boss/minion, random events) |
| credit_multiplier | REAL NOT NULL DEFAULT 0 | PvP win credit steal + boss/minion defeat loot ONLY — does not affect Steal action or item-steal roll |
| steal_bonus | REAL NOT NULL DEFAULT 0 | Boosts ALL theft mechanics: in-combat Steal (roll + %), PvP win credit steal (%), PvP win item-steal roll |
| bonus_ap | INTEGER NOT NULL DEFAULT 0 | Still subject to `AP_CARRYOVER_CAP` |
| hp_regen_bonus | INTEGER NOT NULL DEFAULT 0 | Flat, stacks additively with `AP_PASSIVE_HP_REGEN` and the END contribution |
| durability_reduction | REAL NOT NULL DEFAULT 0 | % reduction applied to all durability loss sources |
| shop_discount | REAL NOT NULL DEFAULT 0 | Stacks additively with PER discount, capped at `SHOP_DISCOUNT_MAX` |
| sell_bonus | REAL NOT NULL DEFAULT 0 | Sells above default `SELL_PRICE_PERCENT` |
| encounter_bonus | REAL NOT NULL DEFAULT 0 | Acts as bonus LCK for random event checks (both midnight and in-game) |
| credit_cost | INTEGER NOT NULL | |
| drop_chance | REAL NOT NULL | Boss/minion drop table only |
| starting_durability | INTEGER NOT NULL DEFAULT 100 | |
| imported_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Note:** `special_item_registry` (Section 3) holds one permanent row per `special_items.id`, tracking world-state (`IN_POOL` / `IN_INVENTORY` / `IN_SHOP`). No `RETIRED` status exists — content removal is a full-reset-only operation, not something the live registry needs to handle.

---

### 6.7 `classes`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT UNIQUE NOT NULL | |
| is_active | BOOLEAN NOT NULL DEFAULT TRUE | Hides from new character creation only — has no effect on existing players who already chose it (their `class_id` FK and stat bonuses are untouched regardless) |
| str_bonus / end_bonus / agi_bonus / lck_bonus / per_bonus | INTEGER NOT NULL DEFAULT 0 | No negative values allowed |
| description | TEXT | |
| imported_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

---

### 6.8 `random_events`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT UNIQUE NOT NULL | |
| is_active | BOOLEAN NOT NULL DEFAULT TRUE | |
| event_type | TEXT NOT NULL | `'Good'` or `'Bad'` |
| rarity | TEXT NOT NULL | `'Common'` / `'Uncommon'` / `'Rare'` |
| flavor_text | TEXT NOT NULL | |
| effect_type | TEXT NOT NULL | `CREDITS`, `ITEM_AT_LEVEL`, `BONUS_AP`, `DURABILITY_RESTORE_RANDOM`, `SPECIAL_ITEM_FROM_POOL`, `HP_LOSS`, `DURABILITY_LOSS_RANDOM`, `XP_LOSS`, `AP_REDUCTION_PERCENT` |
| effect_amount | INTEGER NOT NULL | Magnitude, can be negative for losses |
| duration | TEXT NOT NULL | `'Instant'` or `'UntilMidnight'` |
| imported_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

---

### 6.9 `master`

The authoritative link table — full redundant FK linkage rather than relying on free-text `associated_to` matching, to avoid drift from admin typos.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| movie_name | TEXT UNIQUE NOT NULL | |
| is_active | BOOLEAN NOT NULL DEFAULT TRUE | |
| boss_id | INTEGER NOT NULL FK → bosses.id | |
| boss_weapon_id | INTEGER NOT NULL FK → weapons.id | |
| boss_armor_id | INTEGER NOT NULL FK → armor.id | |
| boss_special_item_id | INTEGER NOT NULL FK → special_items.id | |
| minion_id | INTEGER NOT NULL FK → minions.id | |
| minion_weapon_id | INTEGER NOT NULL FK → weapons.id | |
| minion_armor_id | INTEGER NOT NULL FK → armor.id | |
| minion_special_item_id | INTEGER NOT NULL FK → special_items.id | |
| imported_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

**Design note:** the import job can auto-populate each item's `associated_to` text field FROM this table (rather than trusting separately-typed text on each sheet), keeping the human-readable label and the authoritative FK relationship in sync automatically.

---

### 6.10 `settings`

Simple key-value store. ~85 rows, one per config constant.

| Column | Type | Notes |
|---|---|---|
| constant_name | TEXT PRIMARY KEY | e.g. `'BASE_DAILY_AP'` |
| value | TEXT NOT NULL | Stored as text; parsed to int/float/bool by the application layer based on `constant_name` |
| description | TEXT | |
| imported_at | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | |

Using `constant_name` as the primary key (rather than an autoincrement id) means daily refresh updates are a simple upsert keyed by name.

---

## 7. Open Questions / TODO

- [x] Finalize Excel-imported content table schemas (Section 6) — DONE
- [x] Define Flask route structure (Section 9) — DONE
- [x] Define queue/watchdog script design (Section 10) — DONE
- [x] Define indexing strategy (Section 11) — DONE
- [x] Midnight reset sequence fully documented (Section 10.5) — DONE
- [x] APScheduler confirmed for scheduled jobs (Section 10.4) — DONE
- [x] Settings fallback behavior defined (Section 12) — DONE
- [x] associated_to auto-population from master confirmed (Section 12) — DONE
- [ ] Define import validation rules (required columns, value ranges, cross-reference checks)
- [ ] Decide combat_logs retention/archival strategy long-term
- [x] Confirm admin tooling DB access pattern (Section 13) — DONE
- [x] All pre-build implementation decisions finalized (Section 13) — DONE

---

## 8. Decision Log

| Date/Session | Decision |
|---|---|
| Session N | `max_hp`, `max_ap`, `inventory_limit`, `is_inactive` are all derived on-demand, never stored columns |
| Session N | Level-up stat choices logged to `level_up_history` for audit only, never read in gameplay logic |
| Session N | Boss/minion buffs and player Brace effects share one `combat_buffs` table, scoped by `combat_session_id` + `side`, rather than reusing the player-only `status_effects` table |
| Session N | Equipped gear tracked via 3 FK columns on `players` (`equipped_weapon_id`/`equipped_armor_id`/`equipped_special_id`), not a flag on `inventory_items` |
| Session N | `item_history` (permanent) and `daily_feed` (ephemeral) are two separate tables — the feed is just a UI convenience layer, not the source of truth |
| Session N | Full round-by-round `combat_logs` are permanent (QC value), unlike `daily_feed` which clears nightly |
| Session N | Special item "equipped" status is never duplicated into `special_item_registry` — always derived from `players.equipped_special_id` |
| Session N | Selling a special item back to the shop deletes its `inventory_items` row entirely rather than keeping an orphaned link — `shop_listings.durability_at_listing` is just a snapshot |
| Session N | `attacker_total_damage_dealt` / `defender_total_damage_dealt` tracked universally across ALL combat types for consistency, even though only PvP needs them for the score formula |
| Session N | In-combat Steal success yielding a boss/minion's special item gets its own distinct `item_history.event_type` (`RECEIVED_COMBAT_STEAL`), separate from normal defeat drops |
| Session N | Leaderboard counters split: `pvp_kills` and `times_reduced_to_1hp` get a dedicated `player_stats` table (not columns on `players`); everything else is a live aggregate query |
| Balance Audit | `RESISTANCE_STACK_CAP` renamed to `RESISTANCE_STACK_MIN_DAMAGE_PERCENT` — original naming was ambiguous/backwards (a "25% cap" reads as max reduction, but the rule means damage floors at 25% remaining, i.e. quarter damage). No behavior change, just unambiguous naming. |
| Balance Audit | Confirmed as **intentional**: players get two layers of defense (AC then Dodge) while bosses/minions only get AC. Admin compensates per-encounter via Excel stat tuning, not a structural change. |
| Balance Audit | Added a second scheduled job: **AP trickle**, firing 4x/day (03:00/09:00/15:00/21:00 UTC) granting +3 AP independent of the once-daily midnight reset job. Banks while offline, capped at AP_CARRYOVER_CAP. Requires the scheduler/cron design to support two distinct recurring jobs, not just one daily reset. |
| Balance Audit | END strengthened: now also contributes `floor(END/2)` to passive HP regen per AP spent (stacks with `AP_PASSIVE_HP_REGEN` and `HP_REGEN_BONUS`), giving it a clearer "sustain" identity distinct from AGI/LCK's offense/avoidance niches. |
| Balance Audit | Added `BOSS_LEVEL_WARNING_THRESHOLD` (3): players get a non-blocking warning before engaging a boss/minion 3+ levels above their own, mirroring the existing warn-don't-block pattern used for empty slots, over-encumbrance, and 0-credit sales. |
| Content Tables | Excel import is **staged, not live** — file sits at a known path until the next UTC midnight reset applies it. Validation is all-or-nothing: invalid file = entire import rejected, rest of reset still runs normally. |
| Content Tables | Daily refresh is **additive/modifying only** (match by name: update or insert). It never deletes rows. Removing content requires a manual `is_active` flip or a full game reset. |
| Content Tables | **Intel-clearing diff**: re-import only clears `boss_intel` if resistance/weakness or damage-type columns specifically changed — HP, stats, flavor text, drop rates can change freely without invalidating player-learned knowledge. |
| Content Tables | **Two admin operations**: (1) daily refresh = minor tweaks, staged, applied at midnight; (2) full game reset = major overhauls, wipes ALL player data, reseeds from fresh Excel. Content can only be freely removed/renamed via the full reset path. |
| Content Tables | `is_active` flag kept on all content tables as a cheap manual admin escape hatch (e.g. temporarily hide a broken boss). Never set automatically by import — only by direct admin action. Removing content structurally still requires a full reset. |
| Content Tables | `special_item_registry` keeps original three states (`IN_POOL`/`IN_INVENTORY`/`IN_SHOP`) — no `RETIRED` state needed since content removal is a full-reset-only operation. `item_history` event types likewise unchanged (no `RETIRED_BY_ADMIN`). |
| Content Tables | `master` uses full FK linkage for all 8 references (boss/minion/weapon/armor/special per side) rather than relying on free-text `associated_to` fields, which could drift from admin typos. Import job auto-populates `associated_to` text fields FROM `master`, not from separately-typed admin text. |
| Content Tables | `settings` table uses `constant_name TEXT PRIMARY KEY` (not autoincrement id) — makes upsert-by-name clean with no extra lookup. |
| Routes/UI | Terminal-centric UI: dark bg, monospace font, content accumulates per session. Combat happens in terminal (no separate page). Shop/Blacksmith are full pages. PvP opponent list is a terminal fragment. |
| Routes/UI | `pending_levelup BOOLEAN` stored on `players` (not derived) — checked on every request via before_request hook, too expensive to derive from level_up_history count each time. |
| Routes/UI | JS footprint locked at exactly 3 things: left-column status updates, 5-second feed polling, round-4 countdown timer. Everything else is server-rendered HTML + standard form POSTs. |
| Routes/UI | Steal combat action has a 2-step confirmation fragment (shows risk/reward before committing) — unique among combat actions, all others fire immediately. |
| Routes/UI | Dashboard terminal restores last TERMINAL_HISTORY_ENTRIES (20) personal feed entries on every load so it never feels empty after full-page navigation. |
| Queue | SQLite-backed `action_queue` table — synchronous processing (write receipt, process inline, return result). No async worker needed at 10-50 player scale. Queue exists for crash recovery/audit, not true async queuing. |
| Queue | `action_queue` status starts as PROCESSING (not PENDING) since processing is synchronous and immediate. DONE rows purged after 7 days, FAILED rows permanent. |
| Queue | Startup orphan cleanup: any PROCESSING rows on startup = crash mid-action → AP refunded, in_combat cleared, status → FAILED. |
| Schema | Added combat_sessions.result column — distinguishes how a fight ended (1HP_WIN / SCORE_WIN / ESCAPE / CANCELLED). status column retains ACTIVE/RESOLVED/CANCELLED for broad state; result column gives the specific outcome needed for post-combat logic. |
| Schema | Special item sell price uses the same SELL_PRICE_PERCENT formula as regular gear — no separate constant needed. |
| Queue | APScheduler inside Flask for two scheduled jobs: midnight_reset (00:00 UTC) and ap_trickle (03:00/09:00/15:00/21:00 UTC). Single process, no separate cron setup. |


---

## 9. Flask Route Structure

### 9.1 UI Architecture
- **Left column:** status block (HP/AP/Credits), AP action buttons, nav links
- **Main terminal area:** monospace font, dark bg, color-coded text (green=good, red=damage/bad, amber=system, white=player actions, grey=opponent). Loads last `TERMINAL_HISTORY_ENTRIES` (20) personal feed entries on dashboard load. Content accumulates — never clears during session.
- **Bottom ticker:** full-width scrolling global feed, runs continuously
- **JS footprint (only 3 things):** left column status updates, feed polling every 5s, round-4 PvP countdown timer

### 9.2 Full Route Spec

**Auth & Setup**
```
GET  /login                          → login page
POST /login                          → authenticate → redirect /
POST /logout                         → clear session → redirect /login
GET  /register                       → registration page
POST /register                       → create account → redirect /character-create
GET  /character-create               → character creation (full page, one-time)
POST /character-create               → finalize → redirect /
GET  /levelup                        → stat point assignment (enforced by before_request)
POST /levelup                        → assign point → redirect back
```

**Dashboard**
```
GET  /                               → full page shell: terminal (last 20 entries) + left col + ticker
```

**Terminal Action Routes (POST → HTML fragment appended to terminal)**
```
POST /action/boss                    → random event check, boss/minion roll, PER check
                                       returns: event result fragment OR pre-combat confirmation
POST /action/boss/confirm            → confirmed fight → opening combat fragment
POST /action/pvp                     → random event check
                                       returns: event result fragment OR opponent list fragment
POST /action/pvp/fight               → initiate fight → opening combat fragment
POST /action/tavern                  → heal → result fragment (or blocked message)
```

**Combat (POST → HTML fragment)**
```
POST /combat/action                  → submit action (attack/brace/escape/observe/swap)
                                       returns: round result fragment + next action buttons
POST /combat/steal                   → returns: steal confirmation fragment
POST /combat/steal/confirm           → confirmed steal → round result fragment
POST /combat/extend                  → spend AP → fragment
POST /combat/resolve                 → score formula resolution → post-combat summary fragment
```

**Feed Polling (JSON)**
```
GET  /feed/personal/latest?since=<ts>
GET  /feed/global/latest?since=<ts>
```

**Full-Page Navigation**
```
GET  /shop                           → shop page
POST /shop/buy                       → purchase → redirect /shop
POST /shop/sell                      → sell → redirect /shop
GET  /blacksmith                     → repair page
POST /blacksmith/repair              → repairs → redirect /blacksmith
GET  /character                      → character sheet + inventory
POST /character/equip                → redirect /character
POST /character/unequip              → redirect /character
POST /character/drop                 → redirect /character
POST /character/preference           → redirect /character
GET  /scoreboards                    → all leaderboards
```

**Admin App (separate Flask process, localhost only)**
```
GET  /admin                          → status dashboard
GET  /admin/import                   → import status + upload form
POST /admin/import                   → stage Excel file
GET  /admin/players                  → player list
GET  /admin/players/<id>             → player detail
POST /admin/players/<id>/ban         → ban player
POST /admin/players/<id>/edit        → edit player
GET  /admin/config                   → view/edit settings
POST /admin/config                   → save config
POST /admin/reset/midnight           → trigger midnight reset
POST /admin/reset/full               → full game reset
GET  /admin/logs                     → error/archive logs
```

### 9.3 before_request Hooks (main app)
1. Not logged in → redirect `/login` (exempt: `/login`, `/register`)
2. `pending_levelup = TRUE` AND `in_combat = FALSE` → redirect `/levelup` (exempt: `/levelup`, `/logout`)

### 9.4 Key Decisions
- PvP opponent list appears as terminal fragment (inline selection), not a separate page
- Shop and Blacksmith are full pages (too complex for terminal fragments)
- Combat lives entirely in the terminal — no separate `/combat` page
- Steal action has a confirmation fragment before executing (AC penalty risk)
- Dashboard terminal restores last `TERMINAL_HISTORY_ENTRIES` entries on every load

---

## 10. Queue & Scheduler Design

### 10.1 `action_queue` Table

```sql
CREATE TABLE action_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    action_type TEXT NOT NULL,
    payload TEXT NOT NULL,          -- JSON blob of action parameters
    status TEXT NOT NULL DEFAULT 'PROCESSING',  -- PROCESSING / DONE / FAILED
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at DATETIME
);
```

**Retention:** DONE rows purged after 7 days (midnight reset step). FAILED rows kept permanently for debugging.

### 10.2 Action Processing Pattern

Every write action follows this pattern:

```python
def process_action(player_id, action_type, payload):
    queue_id = insert_queue_row(player_id, action_type, payload)  # status=PROCESSING
    try:
        with db.exclusive_transaction():
            result = ACTION_HANDLERS[action_type](player_id, payload)
        mark_done(queue_id)
        return result
    except Exception as e:
        mark_failed(queue_id)
        raise
```

- Synchronous — Flask writes receipt, processes inline, returns result directly. No polling delay.
- `BEGIN EXCLUSIVE` transaction wraps the actual DB writes for each action — prevents race conditions on `in_combat`, special item registry, and AP deduction.
- Read-only routes (all GETs, feed polling) bypass the queue entirely.

### 10.3 Startup Orphan Cleanup

Runs once at Flask startup before first request:

```python
def startup_cleanup():
    orphans = query("SELECT * FROM action_queue WHERE status='PROCESSING'")
    for orphan in orphans:
        refund_ap(orphan.player_id, orphan.action_type)
        clear_in_combat(orphan.player_id)
        mark_failed(orphan.id)
        log_orphan(orphan)
```

Any `PROCESSING` row on startup = server crashed mid-action. AP refunded, `in_combat` cleared, status → FAILED.

### 10.4 Scheduled Jobs (APScheduler inside Flask)

Two jobs running inside the Flask process via APScheduler:

| Job | Schedule | Description |
|---|---|---|
| `midnight_reset` | Daily at 00:00 UTC | Full reset sequence (see below) |
| `ap_trickle` | Daily at 03:00, 09:00, 15:00, 21:00 UTC | +TRICKLE_AP_AMOUNT to all players, capped at AP_CARRYOVER_CAP |

### 10.5 Midnight Reset Sequence (complete, ordered)

1. Clear all timed `status_effects` rows for all players
2. Purge `action_queue` rows where `status='DONE'` AND `created_at < NOW - 7 days`
3. If staged Excel file exists at import path: validate and apply (or reject + log error)
4. Clear `daily_feed` table (after optional archive export if LOG_DAILY_ARCHIVE enabled)
5. Calculate AP carryover per player (cap at AP_CARRYOVER_CAP)
6. Award new daily AP (BASE_DAILY_AP + floor(END/2))
7. Restore MIDNIGHT_HEAL_PERCENT of missing HP for all players
8. Trigger midnight random encounter checks for all players
9. Rotate shop: clear DAILY_ROTATION listings, populate new 10 weapons + 10 armor
10. Clear unsold special items from shop (item_type='SPECIAL'), return to loot pool (registry status → IN_POOL)
11. Populate new special item shop slots from loot pool (up to floor(player_count/2))
12. Process any pending feed entries

### 10.6 Queue-Required vs Read-Only Routes

**Queue-required (all POST routes):** `/action/*`, `/combat/*`, `/shop/buy`, `/shop/sell`, `/blacksmith/repair`, `/character/equip`, `/character/unequip`, `/character/drop`, `/character/preference`, `/levelup`

**No queue needed (all GET routes + feed polling):** everything else

---

## 11. Indexing Strategy

```sql
CREATE INDEX idx_players_username ON players(username);
CREATE INDEX idx_players_email ON players(email);
CREATE INDEX idx_players_in_combat ON players(in_combat);
CREATE INDEX idx_inventory_player ON inventory_items(player_id);
CREATE INDEX idx_inventory_type ON inventory_items(player_id, item_type);
CREATE INDEX idx_combat_sessions_status ON combat_sessions(status);
CREATE INDEX idx_combat_sessions_attacker ON combat_sessions(attacker_player_id);
CREATE INDEX idx_combat_logs_session ON combat_logs(combat_session_id);
CREATE INDEX idx_daily_feed_player ON daily_feed(player_id, occurred_at);
CREATE INDEX idx_daily_feed_global ON daily_feed(feed_scope, occurred_at);
CREATE INDEX idx_boss_instances_player ON boss_instances(player_id);
CREATE INDEX idx_minion_instances_player ON minion_instances(player_id);
CREATE INDEX idx_action_queue_status ON action_queue(status, created_at);
CREATE INDEX idx_item_history_player ON item_history(player_id);
CREATE INDEX idx_special_registry_status ON special_item_registry(status);
```

---

## 12. Remaining Decisions

### Settings Fallback
If a constant is missing from the `settings` table, the app uses hardcoded Python defaults defined in `config_defaults.py`. Missing constants are logged as warnings on startup. Prevents crashes from accidental row deletion.

### `associated_to` Auto-Population
On import, after `master` is written, the import job overwrites `associated_to` on all boss/minion-linked weapons and armor by querying `master` directly. Generic shop-only items (not referenced in `master`) are left untouched. Format: `"MovieName (Boss)"` or `"MovieName (Minion)"`.


---

## 13. Pre-Build Implementation Decisions

| Decision | Choice | Notes |
|---|---|---|
| Flask session contents | player_id + combat_session_id only | Player loaded fresh from DB on every request via context processor. combat_session_id set on combat start, cleared on end/disconnect. |
| Template player data | Context processor | Injects player object into every template automatically. Routes only pass page-specific data. |
| Error display | Terminal fragments everywhere | Even on full pages (shop, blacksmith, character sheet) those pages include a small terminal-style output panel for errors/feedback. No flash messages. |
| Import path | Hardcoded in config_defaults.py | data/pending_import.xlsx — not a game setting, not in the settings table. |
| Admin DB access | Shared database.py module | Admin app imports the same database.py as the main app — no duplication, no ORM. |

### Flask Session Structure
- player_id: int — set on login, cleared on logout
- combat_session_id: int or None — set on combat start, cleared on end/disconnect

### config_defaults.py Key Entries
- PENDING_IMPORT_PATH = data/pending_import.xlsx
- REJECTED_IMPORT_PATH = data/logs/rejected/
- TERMINAL_HISTORY_ENTRIES = 20
- All game constants (BASE_DAILY_AP, AP_COST_BOSS, etc.) defined here as fallbacks if missing from settings table
