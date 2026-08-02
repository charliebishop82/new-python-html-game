################################################################################
# PHASE 11 CODE — Protagonist Encounter Event
# BBS-Inspired Multiplayer Dueling Game
#
# Files to patch:
#   1. schema.sql         — 4 new protagonist columns on master table
#   2. importer.py        — Validate + process protagonist columns in master
#                           Add PROTAGONIST_ENCOUNTER to VALID_EFFECT_TYPES
#                           Add Protagonist to valid AssociationTypes
#   3. routes/actions.py  — _handle_protagonist_encounter() function
#                           + elif block in _apply_random_event()
#
# How it works:
#   - PROTAGONIST_ENCOUNTER random event triggers (Rare, Good)
#   - Finds movies within ~2 levels of the player (weighted toward closest)
#   - Rolls 40% weapon / 40% armor / 20% special
#   - Special falls back to weapon if already claimed
#   - Item awarded via inventory_items, logged in item_history
#   - Special items tracked in special_item_registry (one copy in world)
#   - Global feed fires when a protagonist special enters the world
################################################################################

# =============================================================================
# PHASE 11 — Protagonist Encounter Event + Importer Updates
# =============================================================================
# Files changed:
#   1. importer.py        — Add PROTAGONIST_ENCOUNTER to VALID_EFFECT_TYPES
#                           Add 'Protagonist' to valid AssociationTypes
#                           Add ProtagonistName/Weapon/Armor/SpecialItem to master processing
#   2. routes/actions.py  — Handle PROTAGONIST_ENCOUNTER in _apply_random_event()
# =============================================================================


# =============================================================================
# FILE: importer.py  (patches)
# =============================================================================

IMPORTER_PATCH = """
# PATCH 1: Add to VALID_EFFECT_TYPES:
    \"PROTAGONIST_ENCOUNTER\",

# PATCH 2: In _validate_special_items(), update AssociationType check:
#   Change:
#       if r.get('AssociationType') not in ('Boss', 'Minion', None):
#   To:
#       if r.get('AssociationType') not in ('Boss', 'Minion', 'Protagonist', None):

# PATCH 3: In _apply_master(), extend to process protagonist columns.
# After the existing minion FK resolution block, add:

        prot_name     = get_id_by_name('players', r.get('ProtagonistName'))  # N/A — name only
        prot_weapon   = get_id('weapons',       r.get('ProtagonistWeapon'))
        prot_armor    = get_id('armor',         r.get('ProtagonistArmor'))
        prot_special  = get_id('special_items', r.get('ProtagonistSpecialItem'))

        # Update master row with protagonist FKs (add these columns to master table in schema)
        # See schema patch below.

# PATCH 4: schema.sql — add protagonist columns to master table:
#   ALTER TABLE master ADD COLUMN protagonist_name         TEXT;
#   ALTER TABLE master ADD COLUMN protagonist_weapon_id    INTEGER REFERENCES weapons(id);
#   ALTER TABLE master ADD COLUMN protagonist_armor_id     INTEGER REFERENCES armor(id);
#   ALTER TABLE master ADD COLUMN protagonist_special_item_id INTEGER REFERENCES special_items(id);

# Or simpler — run these once after adding the columns to schema.sql:
#   python3 -c \"
#   import sqlite3
#   conn = sqlite3.connect('data/game.db')
#   for sql in [
#       'ALTER TABLE master ADD COLUMN protagonist_name TEXT',
#       'ALTER TABLE master ADD COLUMN protagonist_weapon_id INTEGER REFERENCES weapons(id)',
#       'ALTER TABLE master ADD COLUMN protagonist_armor_id INTEGER REFERENCES armor(id)',
#       'ALTER TABLE master ADD COLUMN protagonist_special_item_id INTEGER REFERENCES special_items(id)',
#   ]:
#       try: conn.execute(sql)
#       except: pass
#   conn.commit(); conn.close()
#   print('Done')
#   \"

# PATCH 5: In _apply_master(), extend the INSERT/UPDATE to include protagonist columns:
#   existing INSERT:
#       INSERT INTO master (movie_name, boss_id, ..., minion_special_item_id, imported_at)
#   becomes:
#       INSERT INTO master (movie_name, boss_id, ..., minion_special_item_id,
#                           protagonist_name, protagonist_weapon_id,
#                           protagonist_armor_id, protagonist_special_item_id,
#                           imported_at)
#       VALUES (?, ?, ..., ?, ?, ?, ?, ?)

# PATCH 6: In _validate_master(), add checks for protagonist fields:
#   for field, pool in [
#       ('ProtagonistWeapon',      weapon_names),
#       ('ProtagonistArmor',       armor_names),
#       ('ProtagonistSpecialItem', special_names),
#   ]:
#       v = rd.get(field)
#       if v and v not in pool:
#           errors.append(f\"[Master] '{movie}': {field} '{v}' not found\")
"""


# =============================================================================
# FILE: routes/actions.py  (patch — add PROTAGONIST_ENCOUNTER handler)
# Add this elif block inside _apply_random_event(), after the
# SPECIAL_ITEM_FROM_POOL block.
# =============================================================================

ACTIONS_PATCH = """
        elif effect == \"PROTAGONIST_ENCOUNTER\":
            _handle_protagonist_encounter(player_id, player, settings)


def _handle_protagonist_encounter(player_id: int, player: dict, settings: dict):
    \"\"\"Find a level-appropriate protagonist, roll 40/40/20 for weapon/armor/special,
    award the item, write feed entry. If item already taken, fall back to credits.\"\"\"
    from database import execute, execute_one, execute_write, exclusive_transaction
    from datetime import datetime
    import random, math

    # Find all movies with a protagonist defined, ordered by how close
    # their boss level is to the player's current level
    movies = execute(
        \"\"\"SELECT m.id, m.movie_name,
                  m.protagonist_name,
                  m.protagonist_weapon_id,
                  m.protagonist_armor_id,
                  m.protagonist_special_item_id,
                  b.level as boss_level
           FROM master m
           JOIN bosses b ON b.id = m.boss_id
           WHERE m.protagonist_name IS NOT NULL
             AND m.is_active = 1
           ORDER BY ABS(b.level - ?) ASC\"\"\",
        (player[\"level\"],)
    )

    if not movies:
        # Fallback: award credits
        execute_write(
            \"UPDATE players SET credits = credits + 50 WHERE id = ?\", (player_id,)
        )
        execute_write(
            \"\"\"INSERT INTO daily_feed (feed_scope, player_id, flavor_text, event_category)
               VALUES ('PERSONAL', ?, ?, 'RANDOM_EVENT')\"\"\",
            (player_id,
             \"A familiar figure passes in the crowd — but vanishes before you can speak. +50 credits left behind.\")
        )
        return

    # Pick from the 3 closest level matches (weighted toward closest)
    candidates = movies[:3]
    weights    = [3, 2, 1][:len(candidates)]
    movie      = random.choices(candidates, weights=weights, k=1)[0]

    protagonist = movie[\"protagonist_name\"]
    roll        = random.random()

    if roll < 0.40:
        # Weapon
        item_type = \"WEAPON\"
        item_id   = movie[\"protagonist_weapon_id\"]
        table     = \"weapons\"
    elif roll < 0.80:
        # Armor
        item_type = \"ARMOR\"
        item_id   = movie[\"protagonist_armor_id\"]
        table     = \"armor\"
    else:
        # Special — check registry first
        item_type = \"SPECIAL\"
        item_id   = movie[\"protagonist_special_item_id\"]
        table     = \"special_items\"

    if not item_id:
        # Protagonist item not defined — fallback credits
        execute_write(
            \"UPDATE players SET credits = credits + 50 WHERE id = ?\", (player_id,)
        )
        return

    # For specials: check if already in world
    if item_type == \"SPECIAL\":
        reg = execute_one(
            \"SELECT status FROM special_item_registry WHERE special_item_id = ?\",
            (item_id,)
        )
        if reg and reg[\"status\"] != \"IN_POOL\":
            # Already taken — fall back to weapon instead
            item_type = \"WEAPON\"
            item_id   = movie[\"protagonist_weapon_id\"]
            table     = \"weapons\"

    # Get item detail for name
    item_detail = execute_one(f\"SELECT name, starting_durability FROM {table} WHERE id = ?\", (item_id,))
    if not item_detail:
        return

    item_name = item_detail[\"name\"]
    durability = item_detail.get(\"starting_durability\", 100) or 100

    with exclusive_transaction():
        inv_id = execute_write(
            \"\"\"INSERT INTO inventory_items
               (player_id, item_type, item_id, current_durability, acquired_method)
               VALUES (?, ?, ?, ?, 'RANDOM_EVENT')\"\"\",
            (player_id, item_type, item_id, durability)
        )
        execute_write(
            \"\"\"INSERT INTO item_history
               (player_id, item_type, item_id, item_name, event_type)
               VALUES (?, ?, ?, ?, 'RECEIVED_RANDOM_EVENT')\"\"\",
            (player_id, item_type, item_id, item_name)
        )
        if item_type == \"SPECIAL\":
            execute_write(
                \"\"\"UPDATE special_item_registry
                   SET status = 'IN_INVENTORY', current_owner_player_id = ?,
                       inventory_item_id = ?, last_acquired_method = 'RANDOM_EVENT',
                       updated_at = ?
                   WHERE special_item_id = ?\"\"\",
                (player_id, inv_id, datetime.utcnow().isoformat(), item_id)
            )
        # Personal feed entry
        execute_write(
            \"\"\"INSERT INTO daily_feed (feed_scope, player_id, flavor_text, event_category)
               VALUES ('PERSONAL', ?, ?, 'RANDOM_EVENT')\"\"\",
            (player_id,
             f\"{protagonist} looks you over and hands you the {item_name}. No words. Just a nod.\")
        )
        # Global feed for special items
        if item_type == \"SPECIAL\":
            execute_write(
                \"\"\"INSERT INTO daily_feed (feed_scope, player_id, flavor_text, event_category)
                   VALUES ('GLOBAL', NULL, ?, 'ITEM')\"\"\",
                (f\"The {item_name} has entered the world.\",)
            )
"""


# =============================================================================
# FILE: schema.sql  (patch — add protagonist columns to master table)
# Run these ALTER TABLE statements once on an existing DB,
# or add the columns to the CREATE TABLE master statement for fresh installs.
# =============================================================================

SCHEMA_PATCH = """
-- Run once on existing DB to add protagonist columns:
ALTER TABLE master ADD COLUMN protagonist_name              TEXT;
ALTER TABLE master ADD COLUMN protagonist_weapon_id         INTEGER REFERENCES weapons(id);
ALTER TABLE master ADD COLUMN protagonist_armor_id          INTEGER REFERENCES armor(id);
ALTER TABLE master ADD COLUMN protagonist_special_item_id   INTEGER REFERENCES special_items(id);

-- For fresh installs, add these 4 columns to the CREATE TABLE master statement
-- in schema.sql after minion_special_item_id:
--
--   protagonist_name              TEXT,
--   protagonist_weapon_id         INTEGER REFERENCES weapons(id),
--   protagonist_armor_id          INTEGER REFERENCES armor(id),
--   protagonist_special_item_id   INTEGER REFERENCES special_items(id),
"""


# =============================================================================
# FILE: importer.py  (full _apply_master replacement)
# Replace the existing _apply_master() function with this version that
# handles the 4 new protagonist columns.
# =============================================================================

APPLY_MASTER_REPLACEMENT = """
def _apply_master(master_rows: list):
    \"\"\"Process master sheet: upsert master rows, linking by name.
    Now includes protagonist FK columns.\"\"\"
    for r in master_rows:
        movie = _s(r.get('MovieName'))
        if not movie:
            continue

        def get_id(table, name):
            if not name:
                return None
            row = execute_one(f\"SELECT id FROM {table} WHERE name = ?\", (_s(name),))
            return row['id'] if row else None

        boss_id          = get_id('bosses',        r.get('BossName'))
        minion_id        = get_id('minions',       r.get('MinionName'))
        boss_weapon_id   = get_id('weapons',       r.get('BossWeapon'))
        boss_armor_id    = get_id('armor',         r.get('BossArmor'))
        boss_special_id  = get_id('special_items', r.get('BossSpecialItem'))
        min_weapon_id    = get_id('weapons',       r.get('MinionWeapon'))
        min_armor_id     = get_id('armor',         r.get('MinionArmor'))
        min_special_id   = get_id('special_items', r.get('MinionSpecialItem'))
        prot_name        = _s(r.get('ProtagonistName')) or None
        prot_weapon_id   = get_id('weapons',       r.get('ProtagonistWeapon'))
        prot_armor_id    = get_id('armor',         r.get('ProtagonistArmor'))
        prot_special_id  = get_id('special_items', r.get('ProtagonistSpecialItem'))

        if not all([boss_id, minion_id, boss_weapon_id, boss_armor_id,
                    boss_special_id, min_weapon_id, min_armor_id, min_special_id]):
            logger.warning(\"Master row '%s': could not resolve all FK references, skipping\", movie)
            continue

        now = datetime.utcnow().isoformat()
        existing = execute_one(\"SELECT id FROM master WHERE movie_name = ?\", (movie,))
        if existing:
            execute_write(
                \"\"\"UPDATE master SET
                   boss_id=?, boss_weapon_id=?, boss_armor_id=?, boss_special_item_id=?,
                   minion_id=?, minion_weapon_id=?, minion_armor_id=?, minion_special_item_id=?,
                   protagonist_name=?, protagonist_weapon_id=?, protagonist_armor_id=?,
                   protagonist_special_item_id=?, imported_at=?
                   WHERE movie_name=?\"\"\",
                (boss_id, boss_weapon_id, boss_armor_id, boss_special_id,
                 minion_id, min_weapon_id, min_armor_id, min_special_id,
                 prot_name, prot_weapon_id, prot_armor_id, prot_special_id,
                 now, movie)
            )
        else:
            execute_write(
                \"\"\"INSERT INTO master
                   (movie_name, boss_id, boss_weapon_id, boss_armor_id, boss_special_item_id,
                    minion_id, minion_weapon_id, minion_armor_id, minion_special_item_id,
                    protagonist_name, protagonist_weapon_id, protagonist_armor_id,
                    protagonist_special_item_id, imported_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\"\"\",
                (movie, boss_id, boss_weapon_id, boss_armor_id, boss_special_id,
                 minion_id, min_weapon_id, min_armor_id, min_special_id,
                 prot_name, prot_weapon_id, prot_armor_id, prot_special_id, now)
            )
"""
