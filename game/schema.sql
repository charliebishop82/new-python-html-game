-- schema.sql
-- Full database schema. Executed by database.init_db().
-- All tables use IF NOT EXISTS — safe to re-run on an existing DB.

-- ─────────────────────────────────────────────────────────────────────────────
-- PLAYERS & IDENTITY
-- ─────────────────────────────────────────────────────────────────────────────

-- Account identity, character statistics, resources, equipment pointers, and active-state flags.
CREATE TABLE IF NOT EXISTS players (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT    UNIQUE NOT NULL,
    password_hash       TEXT    NOT NULL,
    email               TEXT    UNIQUE NOT NULL,
    character_name      TEXT    NOT NULL,
    sex                 TEXT    NOT NULL,
    class_id            INTEGER REFERENCES classes(id),
    str_stat            INTEGER NOT NULL DEFAULT 1,
    end_stat            INTEGER NOT NULL DEFAULT 1,
    agi_stat            INTEGER NOT NULL DEFAULT 1,
    lck_stat            INTEGER NOT NULL DEFAULT 1,
    per_stat            INTEGER NOT NULL DEFAULT 1,
    level               INTEGER NOT NULL DEFAULT 1,
    xp                  INTEGER NOT NULL DEFAULT 0,
    current_hp          INTEGER NOT NULL,
    current_ap          INTEGER NOT NULL,
    credits             INTEGER NOT NULL DEFAULT 25,
    equipped_weapon_id  INTEGER REFERENCES inventory_items(id),
    equipped_armor_id   INTEGER REFERENCES inventory_items(id),
    equipped_special_id INTEGER REFERENCES inventory_items(id),
    in_combat           INTEGER NOT NULL DEFAULT 0,
    pending_levelup     INTEGER NOT NULL DEFAULT 0,
    pending_perk        INTEGER NOT NULL DEFAULT 0,
    combat_preference   TEXT    NOT NULL DEFAULT "Balanced",
    is_banned           INTEGER NOT NULL DEFAULT 0,
    retired_at          TEXT,
    last_login_at       TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Long-lived aggregate player records that do not belong on the core character row.
CREATE TABLE IF NOT EXISTS player_stats (
    player_id            INTEGER PRIMARY KEY REFERENCES players(id),
    pvp_kills            INTEGER NOT NULL DEFAULT 0,
    times_reduced_to_1hp INTEGER NOT NULL DEFAULT 0,
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Automated player characters. A profile row marks a normal player as an NPC.
-- Automation motivations and scheduling state attached to otherwise normal player characters.
CREATE TABLE IF NOT EXISTS npc_profiles (
    player_id          INTEGER PRIMARY KEY REFERENCES players(id),
    enabled            INTEGER NOT NULL DEFAULT 1,
    retired            INTEGER NOT NULL DEFAULT 0,
    player_hunter      INTEGER NOT NULL DEFAULT 0 CHECK(player_hunter BETWEEN 0 AND 100),
    boss_killer        INTEGER NOT NULL DEFAULT 0 CHECK(boss_killer BETWEEN 0 AND 100),
    world_boss_hunter  INTEGER NOT NULL DEFAULT 0 CHECK(world_boss_hunter BETWEEN 0 AND 100),
    hoarder            INTEGER NOT NULL DEFAULT 0 CHECK(hoarder BETWEEN 0 AND 100),
    thief              INTEGER NOT NULL DEFAULT 0 CHECK(thief BETWEEN 0 AND 100),
    aggression         INTEGER NOT NULL DEFAULT 50 CHECK(aggression BETWEEN 0 AND 100),
    self_preservation  INTEGER NOT NULL DEFAULT 50 CHECK(self_preservation BETWEEN 0 AND 100),
    repair_tendency    INTEGER NOT NULL DEFAULT 50 CHECK(repair_tendency BETWEEN 0 AND 100),
    actions_per_day    INTEGER NOT NULL DEFAULT 4 CHECK(actions_per_day BETWEEN 1 AND 24),
    actions_today      INTEGER NOT NULL DEFAULT 0,
    wake_actions       INTEGER NOT NULL DEFAULT 0,
    last_action_at     TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Administrator-readable explanations of automated NPC decisions and outcomes.
CREATE TABLE IF NOT EXISTS npc_action_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    decision    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    result      TEXT NOT NULL,
    details_json TEXT,
    occurred_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_npc_profiles_active ON npc_profiles(enabled, retired);
CREATE INDEX IF NOT EXISTS idx_npc_action_log_player ON npc_action_log(player_id, occurred_at);

-- Permanent record of each level-up stat point assigned to a character.
CREATE TABLE IF NOT EXISTS level_up_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id      INTEGER NOT NULL REFERENCES players(id),
    level_reached  INTEGER NOT NULL,
    stat_increased TEXT    NOT NULL,
    timestamp      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Permanent perk selections earned at levels 3, 6, 9, 12, and 15.
CREATE TABLE IF NOT EXISTS player_perks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    perk_id     INTEGER NOT NULL REFERENCES perks(id),
    level_chosen INTEGER NOT NULL,
    acquired_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(player_id, perk_id),
    UNIQUE(player_id, level_chosen)
);

-- Temporary character modifiers, normally cleared by the UTC reset.
CREATE TABLE IF NOT EXISTS status_effects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    effect_type TEXT    NOT NULL,
    value       REAL    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Round-scoped or combat-scoped modifiers applied to one combat side.
CREATE TABLE IF NOT EXISTS combat_buffs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    combat_session_id INTEGER NOT NULL REFERENCES combat_sessions(id),
    side              TEXT    NOT NULL,
    buff_type         TEXT    NOT NULL,
    damage_type       TEXT,
    value             REAL    NOT NULL,
    expires_on        TEXT    NOT NULL,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- COMBAT
-- ─────────────────────────────────────────────────────────────────────────────

-- Authoritative lifecycle and summary state for PvP, boss, and minion fights.
CREATE TABLE IF NOT EXISTS combat_sessions (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    combat_type                 TEXT    NOT NULL,
    attacker_player_id          INTEGER NOT NULL REFERENCES players(id),
    defender_player_id          INTEGER REFERENCES players(id),
    boss_instance_id            INTEGER REFERENCES boss_instances(id),
    minion_instance_id          INTEGER REFERENCES minion_instances(id),
    world_boss_event_id         INTEGER REFERENCES world_boss_events(id),
    special_attack_used         INTEGER NOT NULL DEFAULT 0,
    special_buff_used           INTEGER NOT NULL DEFAULT 0,
    current_phase               INTEGER NOT NULL DEFAULT 1,
    status                      TEXT    NOT NULL DEFAULT "ACTIVE",
    result                      TEXT,
    current_round               INTEGER NOT NULL DEFAULT 1,
    rounds_extended             INTEGER NOT NULL DEFAULT 0,
    attacker_hp_start           INTEGER NOT NULL,
    defender_hp_start           INTEGER,
    attacker_total_damage_dealt INTEGER NOT NULL DEFAULT 0,
    defender_total_damage_dealt INTEGER NOT NULL DEFAULT 0,
    attacker_observed           INTEGER NOT NULL DEFAULT 0,
    defender_observed           INTEGER NOT NULL DEFAULT 0,
    started_at                  TEXT    NOT NULL DEFAULT (datetime('now')),
    resolved_at                 TEXT
);

-- Per-player persistent discovery, HP, phase, and kill state for bosses.
CREATE TABLE IF NOT EXISTS boss_instances (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id           INTEGER NOT NULL REFERENCES players(id),
    boss_id             INTEGER NOT NULL REFERENCES bosses(id),
    current_hp          INTEGER NOT NULL,
    encounter_max_hp    INTEGER,
    special_attack_used INTEGER NOT NULL DEFAULT 0,
    special_buff_used   INTEGER NOT NULL DEFAULT 0,
    current_phase       INTEGER NOT NULL DEFAULT 1,
    discovered_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    kill_count          INTEGER NOT NULL DEFAULT 0,
    UNIQUE(player_id, boss_id)
);

-- Per-player persistent discovery, HP, and kill state for minions.
CREATE TABLE IF NOT EXISTS minion_instances (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id     INTEGER NOT NULL REFERENCES players(id),
    minion_id     INTEGER NOT NULL REFERENCES minions(id),
    current_hp    INTEGER NOT NULL,
    encounter_max_hp INTEGER,
    discovered_at TEXT    NOT NULL DEFAULT (datetime('now')),
    kill_count    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(player_id, minion_id)
);

-- Permanent record that a player has learned a boss’s combat information.
CREATE TABLE IF NOT EXISTS boss_intel (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id  INTEGER NOT NULL REFERENCES players(id),
    boss_id    INTEGER NOT NULL REFERENCES bosses(id),
    learned_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(player_id, boss_id)
);

-- Detailed round-by-round audit records for combat actions and outcomes.
CREATE TABLE IF NOT EXISTS combat_logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    combat_session_id INTEGER NOT NULL REFERENCES combat_sessions(id),
    round_number      INTEGER NOT NULL,
    actor             TEXT    NOT NULL,
    action_type       TEXT    NOT NULL,
    roll_detail       TEXT    NOT NULL,
    outcome_detail    TEXT    NOT NULL,
    hp_after_attacker INTEGER,
    hp_after_defender INTEGER,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- INVENTORY & ITEMS
-- ─────────────────────────────────────────────────────────────────────────────

-- Physical item copies owned by players, including durability and acquisition method.
CREATE TABLE IF NOT EXISTS inventory_items (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id          INTEGER NOT NULL REFERENCES players(id),
    item_type          TEXT    NOT NULL,
    item_id            INTEGER NOT NULL,
    current_durability INTEGER NOT NULL DEFAULT 100,
    acquired_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    acquired_method    TEXT    NOT NULL
);

-- Permanent acquisition, sale, theft, drop, grant, and loss history.
CREATE TABLE IF NOT EXISTS item_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id         INTEGER NOT NULL REFERENCES players(id),
    item_type         TEXT    NOT NULL,
    item_id           INTEGER NOT NULL,
    item_name         TEXT    NOT NULL,
    event_type        TEXT    NOT NULL,
    credit_amount     INTEGER,
    related_player_id INTEGER REFERENCES players(id),
    occurred_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Single-source ownership and location state for globally unique special items.
CREATE TABLE IF NOT EXISTS special_item_registry (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    special_item_id         INTEGER NOT NULL UNIQUE REFERENCES special_items(id),
    status                  TEXT    NOT NULL DEFAULT "IN_POOL",
    current_owner_player_id INTEGER REFERENCES players(id),
    inventory_item_id       INTEGER REFERENCES inventory_items(id),
    shop_listing_price      INTEGER,
    last_acquired_method    TEXT,
    last_released_method    TEXT,
    updated_at              TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- ECONOMY
-- ─────────────────────────────────────────────────────────────────────────────

-- Items currently offered by the system or a player through the Shop.
CREATE TABLE IF NOT EXISTS shop_listings (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type             TEXT    NOT NULL,
    item_id               INTEGER NOT NULL,
    listing_source        TEXT    NOT NULL,
    seller_player_id      INTEGER REFERENCES players(id),
    durability_at_listing INTEGER,
    price                 INTEGER NOT NULL,
    listed_at             TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Player-run, timed sales. The inventory copy remains owned by the seller but
-- is locked by this row until settlement or cancellation.
CREATE TABLE IF NOT EXISTS auction_listings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_player_id  INTEGER NOT NULL REFERENCES players(id),
    inventory_item_id INTEGER NOT NULL REFERENCES inventory_items(id),
    minimum_bid       INTEGER NOT NULL CHECK(minimum_bid >= 1),
    current_bid       INTEGER,
    current_bidder_id INTEGER REFERENCES players(id),
    status            TEXT NOT NULL DEFAULT 'ACTIVE',
    listed_at         TEXT NOT NULL DEFAULT (datetime('now')),
    ends_at           TEXT NOT NULL,
    settled_at        TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_auction_item_active
    ON auction_listings(inventory_item_id) WHERE status='ACTIVE';
CREATE INDEX IF NOT EXISTS idx_auction_active_end ON auction_listings(status, ends_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- FEEDS
-- ─────────────────────────────────────────────────────────────────────────────

-- Time-ordered personal and global messages displayed in the terminal interface.
CREATE TABLE IF NOT EXISTS daily_feed (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_scope        TEXT    NOT NULL,
    player_id         INTEGER REFERENCES players(id),
    flavor_text       TEXT    NOT NULL,
    event_category    TEXT    NOT NULL,
    combat_session_id INTEGER REFERENCES combat_sessions(id),
    occurred_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- QUEUE
-- ─────────────────────────────────────────────────────────────────────────────

-- Auditable receipts for every shared state-changing player or NPC action.
CREATE TABLE IF NOT EXISTS action_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id    INTEGER NOT NULL REFERENCES players(id),
    action_type  TEXT    NOT NULL,
    payload      TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT "PROCESSING",
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT
);

-- One activity temporarily displaced by a roaming-minion encounter.
CREATE TABLE IF NOT EXISTS pending_interrupted_actions (
    player_id    INTEGER PRIMARY KEY REFERENCES players(id),
    action_type  TEXT NOT NULL CHECK(action_type IN ('BOSS','PVP','WORLD_BOSS','SHOP')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Unified per-character success, failure, diagnostic, and action history.
CREATE TABLE IF NOT EXISTS player_activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    category    TEXT NOT NULL,
    action      TEXT NOT NULL,
    status      TEXT NOT NULL,
    message     TEXT NOT NULL,
    details_json TEXT,
    queue_id    INTEGER REFERENCES action_queue(id),
    source      TEXT NOT NULL DEFAULT 'GAME',
    seen_at     TEXT,
    occurred_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Permanent reasons and before/after details for significant administrator changes.
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id   INTEGER,
    reason      TEXT,
    details_json TEXT,
    occurred_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Start, completion, failure, and result summaries for background jobs.
CREATE TABLE IF NOT EXISTS scheduler_run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name    TEXT NOT NULL,
    status      TEXT NOT NULL,
    result_summary TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT
);

-- ─────────────────────────────────────────────────────────────────────────────
-- CONTENT TABLES (Excel-imported)
-- ─────────────────────────────────────────────────────────────────────────────

-- Excel-imported class definitions and permanent creation bonuses.
CREATE TABLE IF NOT EXISTS classes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    UNIQUE NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    str_bonus   INTEGER NOT NULL DEFAULT 0,
    end_bonus   INTEGER NOT NULL DEFAULT 0,
    agi_bonus   INTEGER NOT NULL DEFAULT 0,
    lck_bonus   INTEGER NOT NULL DEFAULT 0,
    per_bonus   INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    imported_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Excel-imported boss statistics, phases, attacks, rewards, and narrative definitions.
CREATE TABLE IF NOT EXISTS bosses (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    name                        TEXT    UNIQUE NOT NULL,
    is_active                   INTEGER NOT NULL DEFAULT 1,
    level                       INTEGER NOT NULL,
    str_stat                    INTEGER NOT NULL,
    end_stat                    INTEGER NOT NULL,
    agi_stat                    INTEGER NOT NULL,
    lck_stat                    INTEGER NOT NULL,
    per_stat                    INTEGER NOT NULL,
    max_hp                      INTEGER NOT NULL,
    phase2_hp_percent           INTEGER NOT NULL,
    phase3_hp_percent           INTEGER NOT NULL,
    special_attack_name         TEXT    NOT NULL,
    special_attack_die          TEXT    NOT NULL,
    special_attack_damage_type  TEXT    NOT NULL,
    special_attack_flavor       TEXT    NOT NULL,
    special_buff_name           TEXT    NOT NULL,
    special_buff_type           TEXT    NOT NULL,
    special_buff_value          REAL    NOT NULL,
    special_buff_damage_type    TEXT,
    special_buff_flavor         TEXT    NOT NULL,
    res_blade     INTEGER NOT NULL DEFAULT 0,
    res_blunt     INTEGER NOT NULL DEFAULT 0,
    res_ballistic INTEGER NOT NULL DEFAULT 0,
    res_energy    INTEGER NOT NULL DEFAULT 0,
    res_arcane    INTEGER NOT NULL DEFAULT 0,
    res_explosive INTEGER NOT NULL DEFAULT 0,
    res_venom     INTEGER NOT NULL DEFAULT 0,
    weak_blade    INTEGER NOT NULL DEFAULT 0,
    weak_blunt    INTEGER NOT NULL DEFAULT 0,
    weak_ballistic INTEGER NOT NULL DEFAULT 0,
    weak_energy   INTEGER NOT NULL DEFAULT 0,
    weak_arcane   INTEGER NOT NULL DEFAULT 0,
    weak_explosive INTEGER NOT NULL DEFAULT 0,
    weak_venom    INTEGER NOT NULL DEFAULT 0,
    drop_weapon_chance       REAL    NOT NULL,
    drop_armor_chance        REAL    NOT NULL,
    drop_special_item_chance REAL    NOT NULL,
    drop_credit_min          INTEGER NOT NULL,
    drop_credit_max          INTEGER NOT NULL,
    flavor_text              TEXT    NOT NULL,
    description              TEXT    NOT NULL DEFAULT '',
    imported_at              TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Shared-event boss definitions. Encounter state and rewards will be layered
-- on separately once the multiplayer event rules are finalized.
CREATE TABLE IF NOT EXISTS world_bosses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    level INTEGER NOT NULL,
    str_stat INTEGER NOT NULL,
    end_stat INTEGER NOT NULL,
    agi_stat INTEGER NOT NULL,
    lck_stat INTEGER NOT NULL,
    per_stat INTEGER NOT NULL,
    max_hp INTEGER NOT NULL,
    phase2_hp_percent INTEGER NOT NULL,
    phase3_hp_percent INTEGER NOT NULL,
    special_attack_name TEXT NOT NULL,
    special_attack_die TEXT NOT NULL,
    special_attack_damage_type TEXT NOT NULL,
    special_attack_flavor TEXT NOT NULL,
    special_buff_name TEXT NOT NULL,
    special_buff_type TEXT NOT NULL,
    special_buff_value REAL NOT NULL,
    special_buff_damage_type TEXT,
    special_buff_flavor TEXT NOT NULL,
    res_blade INTEGER NOT NULL DEFAULT 0, res_blunt INTEGER NOT NULL DEFAULT 0,
    res_ballistic INTEGER NOT NULL DEFAULT 0, res_energy INTEGER NOT NULL DEFAULT 0,
    res_arcane INTEGER NOT NULL DEFAULT 0, res_explosive INTEGER NOT NULL DEFAULT 0,
    res_venom INTEGER NOT NULL DEFAULT 0,
    weak_blade INTEGER NOT NULL DEFAULT 0, weak_blunt INTEGER NOT NULL DEFAULT 0,
    weak_ballistic INTEGER NOT NULL DEFAULT 0, weak_energy INTEGER NOT NULL DEFAULT 0,
    weak_arcane INTEGER NOT NULL DEFAULT 0, weak_explosive INTEGER NOT NULL DEFAULT 0,
    weak_venom INTEGER NOT NULL DEFAULT 0,
    drop_weapon_chance REAL NOT NULL, drop_armor_chance REAL NOT NULL,
    drop_special_item_chance REAL NOT NULL,
    drop_credit_min INTEGER NOT NULL, drop_credit_max INTEGER NOT NULL,
    flavor_text TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Excel-imported minion statistics and combat definitions.
CREATE TABLE IF NOT EXISTS minions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    UNIQUE NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    level         INTEGER NOT NULL,
    str_stat      INTEGER NOT NULL,
    end_stat      INTEGER NOT NULL,
    agi_stat      INTEGER NOT NULL,
    lck_stat      INTEGER NOT NULL,
    per_stat      INTEGER NOT NULL,
    max_hp        INTEGER NOT NULL,
    drop_weapon_chance       REAL    NOT NULL,
    drop_armor_chance        REAL    NOT NULL,
    drop_special_item_chance REAL    NOT NULL,
    drop_credit_min          INTEGER NOT NULL,
    drop_credit_max          INTEGER NOT NULL,
    flavor_text   TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    imported_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Weapon balance definitions shared by all inventory copies.
CREATE TABLE IF NOT EXISTS weapons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    UNIQUE NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    level           INTEGER NOT NULL,
    weapon_type     TEXT    NOT NULL,
    damage_die      TEXT    NOT NULL,
    damage_type     TEXT    NOT NULL,
    str_bonus       INTEGER NOT NULL DEFAULT 0,
    end_bonus       INTEGER NOT NULL DEFAULT 0,
    agi_bonus       INTEGER NOT NULL DEFAULT 0,
    lck_bonus       INTEGER NOT NULL DEFAULT 0,
    per_bonus       INTEGER NOT NULL DEFAULT 0,
    associated_to   TEXT,
    description     TEXT NOT NULL DEFAULT '',
    credit_cost     INTEGER NOT NULL,
    drop_chance     REAL    NOT NULL,
    starting_durability INTEGER NOT NULL DEFAULT 100,
    imported_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Armor class, resistance, stat, economy, and durability definitions.
CREATE TABLE IF NOT EXISTS armor (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    UNIQUE NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    level           INTEGER NOT NULL,
    ac_bonus        INTEGER NOT NULL DEFAULT 0,
    res_blade       INTEGER NOT NULL DEFAULT 0,
    res_blunt       INTEGER NOT NULL DEFAULT 0,
    res_ballistic   INTEGER NOT NULL DEFAULT 0,
    res_energy      INTEGER NOT NULL DEFAULT 0,
    res_arcane      INTEGER NOT NULL DEFAULT 0,
    res_explosive   INTEGER NOT NULL DEFAULT 0,
    res_venom       INTEGER NOT NULL DEFAULT 0,
    str_bonus       INTEGER NOT NULL DEFAULT 0,
    end_bonus       INTEGER NOT NULL DEFAULT 0,
    agi_bonus       INTEGER NOT NULL DEFAULT 0,
    lck_bonus       INTEGER NOT NULL DEFAULT 0,
    per_bonus       INTEGER NOT NULL DEFAULT 0,
    associated_to   TEXT,
    description     TEXT NOT NULL DEFAULT '',
    credit_cost     INTEGER NOT NULL,
    drop_chance     REAL    NOT NULL,
    starting_durability INTEGER NOT NULL DEFAULT 100,
    imported_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Unique special-item modifiers, associations, economy values, and durability definitions.
CREATE TABLE IF NOT EXISTS special_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    UNIQUE NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    associated_to   TEXT    NOT NULL,
    association_type TEXT   NOT NULL,
    description      TEXT   NOT NULL DEFAULT '',
    str_bonus       INTEGER NOT NULL DEFAULT 0,
    end_bonus       INTEGER NOT NULL DEFAULT 0,
    agi_bonus       INTEGER NOT NULL DEFAULT 0,
    lck_bonus       INTEGER NOT NULL DEFAULT 0,
    per_bonus       INTEGER NOT NULL DEFAULT 0,
    initiative_bonus    INTEGER NOT NULL DEFAULT 0,
    extra_attack        INTEGER NOT NULL DEFAULT 0,
    crit_chance_bonus   REAL    NOT NULL DEFAULT 0,
    crit_dmg_multiplier REAL    NOT NULL DEFAULT 0,
    ac_bonus            INTEGER NOT NULL DEFAULT 0,
    res_blade       INTEGER NOT NULL DEFAULT 0,
    res_blunt       INTEGER NOT NULL DEFAULT 0,
    res_ballistic   INTEGER NOT NULL DEFAULT 0,
    res_energy      INTEGER NOT NULL DEFAULT 0,
    res_arcane      INTEGER NOT NULL DEFAULT 0,
    res_explosive   INTEGER NOT NULL DEFAULT 0,
    res_venom       INTEGER NOT NULL DEFAULT 0,
    bonus_damage_type   TEXT,
    bonus_damage_amount INTEGER NOT NULL DEFAULT 0,
    xp_multiplier       REAL    NOT NULL DEFAULT 0,
    credit_multiplier   REAL    NOT NULL DEFAULT 0,
    steal_bonus         REAL    NOT NULL DEFAULT 0,
    bonus_ap            INTEGER NOT NULL DEFAULT 0,
    hp_regen_bonus      INTEGER NOT NULL DEFAULT 0,
    durability_reduction REAL   NOT NULL DEFAULT 0,
    shop_discount       REAL    NOT NULL DEFAULT 0,
    sell_bonus          REAL    NOT NULL DEFAULT 0,
    encounter_bonus     REAL    NOT NULL DEFAULT 0,
    credit_cost         INTEGER NOT NULL,
    drop_chance         REAL    NOT NULL,
    starting_durability INTEGER NOT NULL DEFAULT 100,
    imported_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Permanent level-up perks use the same bonus vocabulary as special items.
CREATE TABLE IF NOT EXISTS perks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    level INTEGER NOT NULL,
    str_bonus INTEGER NOT NULL DEFAULT 0, end_bonus INTEGER NOT NULL DEFAULT 0,
    agi_bonus INTEGER NOT NULL DEFAULT 0, lck_bonus INTEGER NOT NULL DEFAULT 0,
    per_bonus INTEGER NOT NULL DEFAULT 0,
    initiative_bonus INTEGER NOT NULL DEFAULT 0, extra_attack INTEGER NOT NULL DEFAULT 0,
    crit_chance_bonus REAL NOT NULL DEFAULT 0, crit_dmg_multiplier REAL NOT NULL DEFAULT 0,
    ac_bonus INTEGER NOT NULL DEFAULT 0,
    res_blade INTEGER NOT NULL DEFAULT 0, res_blunt INTEGER NOT NULL DEFAULT 0,
    res_ballistic INTEGER NOT NULL DEFAULT 0, res_energy INTEGER NOT NULL DEFAULT 0,
    res_arcane INTEGER NOT NULL DEFAULT 0, res_explosive INTEGER NOT NULL DEFAULT 0,
    res_venom INTEGER NOT NULL DEFAULT 0,
    bonus_damage_type TEXT, bonus_damage_amount INTEGER NOT NULL DEFAULT 0,
    xp_multiplier REAL NOT NULL DEFAULT 0, credit_multiplier REAL NOT NULL DEFAULT 0,
    steal_bonus REAL NOT NULL DEFAULT 0, bonus_ap INTEGER NOT NULL DEFAULT 0,
    hp_regen_bonus INTEGER NOT NULL DEFAULT 0, durability_reduction REAL NOT NULL DEFAULT 0,
    shop_discount REAL NOT NULL DEFAULT 0, sell_bonus REAL NOT NULL DEFAULT 0,
    encounter_bonus REAL NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Imported relationship between a world boss and its three exclusive prizes.
CREATE TABLE IF NOT EXISTS world_boss_loot (
    world_boss_id INTEGER PRIMARY KEY REFERENCES world_bosses(id),
    weapon_id INTEGER NOT NULL REFERENCES weapons(id),
    armor_id INTEGER NOT NULL REFERENCES armor(id),
    special_item_id INTEGER NOT NULL REFERENCES special_items(id)
);

-- One non-repeating weekly shared encounter and its authoritative HP pool.
CREATE TABLE IF NOT EXISTS world_boss_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    world_boss_id INTEGER NOT NULL REFERENCES world_bosses(id),
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    starting_hp INTEGER NOT NULL,
    current_hp INTEGER NOT NULL,
    hp_multiplier REAL NOT NULL DEFAULT 1.0,
    started_at TEXT NOT NULL,
    scheduled_end_at TEXT NOT NULL,
    ended_at TEXT,
    end_reason TEXT,
    defeated_by_player_id INTEGER REFERENCES players(id),
    rewards_completed_at TEXT
);

CREATE TABLE IF NOT EXISTS world_boss_contributions (
    event_id INTEGER NOT NULL REFERENCES world_boss_events(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    damage INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    xp_earned INTEGER NOT NULL DEFAULT 0,
    credits_earned INTEGER NOT NULL DEFAULT 0,
    first_damage_at TEXT,
    last_damage_at TEXT,
    PRIMARY KEY(event_id,player_id)
);

CREATE TABLE IF NOT EXISTS world_boss_event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES world_boss_events(id),
    player_id INTEGER REFERENCES players(id),
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT,
    occurred_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS world_boss_rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES world_boss_events(id),
    place INTEGER NOT NULL CHECK(place BETWEEN 1 AND 3),
    player_id INTEGER NOT NULL REFERENCES players(id),
    status TEXT NOT NULL DEFAULT 'PENDING',
    item_type TEXT,
    item_id INTEGER,
    selection_deadline TEXT NOT NULL,
    awarded_at TEXT,
    UNIQUE(event_id,place), UNIQUE(event_id,player_id)
);

-- Weighted good and bad encounters plus their mechanical effects.
CREATE TABLE IF NOT EXISTS random_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    UNIQUE NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    event_type    TEXT    NOT NULL,
    rarity        TEXT    NOT NULL,
    flavor_text   TEXT    NOT NULL,
    effect_type   TEXT    NOT NULL,
    effect_amount INTEGER NOT NULL,
    duration      TEXT    NOT NULL,
    imported_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Movie-level relationships connecting bosses, minions, protagonists, and their equipment.
CREATE TABLE IF NOT EXISTS master (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_name              TEXT    UNIQUE NOT NULL,
    is_active               INTEGER NOT NULL DEFAULT 1,
    boss_id                 INTEGER NOT NULL REFERENCES bosses(id),
    boss_weapon_id          INTEGER NOT NULL REFERENCES weapons(id),
    boss_armor_id           INTEGER NOT NULL REFERENCES armor(id),
    boss_special_item_id    INTEGER NOT NULL REFERENCES special_items(id),
    minion_id               INTEGER NOT NULL REFERENCES minions(id),
    minion_weapon_id        INTEGER NOT NULL REFERENCES weapons(id),
    minion_armor_id         INTEGER NOT NULL REFERENCES armor(id),
    minion_special_item_id  INTEGER NOT NULL REFERENCES special_items(id),
    protagonist_name        TEXT,
    protagonist_description TEXT,
    protagonist_weapon_id   INTEGER REFERENCES weapons(id),
    protagonist_armor_id    INTEGER REFERENCES armor(id),
    protagonist_special_item_id INTEGER REFERENCES special_items(id),
    imported_at             TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Database overrides for typed gameplay defaults in config_defaults.py.
CREATE TABLE IF NOT EXISTS settings (
    constant_name TEXT PRIMARY KEY,
    value         TEXT NOT NULL,
    description   TEXT,
    imported_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_players_username        ON players(username);
CREATE INDEX IF NOT EXISTS idx_players_email           ON players(email);
CREATE INDEX IF NOT EXISTS idx_players_in_combat       ON players(in_combat);
CREATE INDEX IF NOT EXISTS idx_inventory_player        ON inventory_items(player_id);
CREATE INDEX IF NOT EXISTS idx_inventory_type          ON inventory_items(player_id, item_type);
CREATE INDEX IF NOT EXISTS idx_combat_sessions_status  ON combat_sessions(status);
CREATE INDEX IF NOT EXISTS idx_combat_sessions_attacker ON combat_sessions(attacker_player_id);
CREATE INDEX IF NOT EXISTS idx_combat_logs_session     ON combat_logs(combat_session_id);
CREATE INDEX IF NOT EXISTS idx_daily_feed_player       ON daily_feed(player_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_daily_feed_global       ON daily_feed(feed_scope, occurred_at);
CREATE INDEX IF NOT EXISTS idx_boss_instances_player   ON boss_instances(player_id);
CREATE INDEX IF NOT EXISTS idx_minion_instances_player ON minion_instances(player_id);
CREATE INDEX IF NOT EXISTS idx_player_perks_player ON player_perks(player_id);
CREATE INDEX IF NOT EXISTS idx_world_boss_events_status ON world_boss_events(status);
CREATE INDEX IF NOT EXISTS idx_world_boss_log_event ON world_boss_event_log(event_id,id);
CREATE INDEX IF NOT EXISTS idx_action_queue_status     ON action_queue(status, created_at);
CREATE INDEX IF NOT EXISTS idx_player_activity_date    ON player_activity_log(player_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_player_activity_status  ON player_activity_log(status, occurred_at);
CREATE INDEX IF NOT EXISTS idx_admin_audit_date        ON admin_audit_log(occurred_at);
CREATE INDEX IF NOT EXISTS idx_scheduler_run_date      ON scheduler_run_log(job_name, started_at);
CREATE INDEX IF NOT EXISTS idx_item_history_player     ON item_history(player_id);
CREATE INDEX IF NOT EXISTS idx_special_registry_status ON special_item_registry(status);
