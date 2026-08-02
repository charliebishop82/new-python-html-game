-- Updated CREATE TABLE master in schema.sql (add protagonist columns):

CREATE TABLE IF NOT EXISTS master (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_name                  TEXT    UNIQUE NOT NULL,
    is_active                   INTEGER NOT NULL DEFAULT 1,
    boss_id                     INTEGER NOT NULL REFERENCES bosses(id),
    boss_weapon_id              INTEGER NOT NULL REFERENCES weapons(id),
    boss_armor_id               INTEGER NOT NULL REFERENCES armor(id),
    boss_special_item_id        INTEGER NOT NULL REFERENCES special_items(id),
    minion_id                   INTEGER NOT NULL REFERENCES minions(id),
    minion_weapon_id            INTEGER NOT NULL REFERENCES weapons(id),
    minion_armor_id             INTEGER NOT NULL REFERENCES armor(id),
    minion_special_item_id      INTEGER NOT NULL REFERENCES special_items(id),
    protagonist_name            TEXT,
    protagonist_weapon_id       INTEGER REFERENCES weapons(id),
    protagonist_armor_id        INTEGER REFERENCES armor(id),
    protagonist_special_item_id INTEGER REFERENCES special_items(id),
    imported_at                 TEXT    NOT NULL DEFAULT (datetime("now"))
);

-- For existing DBs run once:
-- ALTER TABLE master ADD COLUMN protagonist_name              TEXT;
-- ALTER TABLE master ADD COLUMN protagonist_weapon_id         INTEGER REFERENCES weapons(id);
-- ALTER TABLE master ADD COLUMN protagonist_armor_id          INTEGER REFERENCES armor(id);
-- ALTER TABLE master ADD COLUMN protagonist_special_item_id   INTEGER REFERENCES special_items(id);
