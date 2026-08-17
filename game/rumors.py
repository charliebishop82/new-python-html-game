"""Tavern rumors that permanently expand a character's War Room intelligence."""

import random
from datetime import datetime

from database import execute, execute_one, execute_write, exclusive_transaction


def _wealth_band(credits: int) -> str:
    if credits < 50:
        return "Nearly broke"
    if credits < 200:
        return "Modest means"
    if credits < 500:
        return "Comfortable"
    if credits < 1000:
        return "Wealthy"
    return "Loaded"


def _enemy_rumor(player_id: int) -> dict | None:
    choices = []
    for kind, table, intel_table, id_col in (
        ("BOSS", "bosses", "boss_intel", "boss_id"),
        ("MINION", "minions", "minion_intel", "minion_id"),
    ):
        rows = execute(
            f"""SELECT e.* FROM {table} e WHERE e.is_active=1 AND NOT EXISTS(
                  SELECT 1 FROM {intel_table} i WHERE i.player_id=? AND i.{id_col}=e.id)
                ORDER BY e.level,e.id""", (player_id,)
        )
        choices.extend((kind, row, intel_table, id_col) for row in rows)
    if not choices:
        return None
    kind, enemy, intel_table, id_col = random.choice(choices)
    weaknesses = [d.title() for d in
        ("blade", "blunt", "ballistic", "energy", "arcane", "explosive", "venom")
        if enemy.get(f"weak_{d}")]
    resistances = [d.title() for d in
        ("blade", "blunt", "ballistic", "energy", "arcane", "explosive", "venom")
        if enemy.get(f"res_{d}")]
    with exclusive_transaction():
        execute_write(
            f"INSERT OR IGNORE INTO {intel_table}(player_id,{id_col}) VALUES(?,?)",
            (player_id, enemy["id"]),
        )
        if kind == "BOSS":
            execute_write(
                """INSERT OR IGNORE INTO boss_instances(player_id,boss_id,current_hp,encounter_max_hp)
                   VALUES(?,?,?,?)""",
                (player_id, enemy["id"], enemy["max_hp"], enemy["max_hp"]),
            )
        else:
            execute_write(
                """INSERT OR IGNORE INTO minion_instances(player_id,minion_id,current_hp,encounter_max_hp)
                   VALUES(?,?,?,?)""",
                (player_id, enemy["id"], enemy["max_hp"], enemy["max_hp"]),
            )
    facts = []
    if weaknesses:
        facts.append("weak to " + ", ".join(weaknesses))
    if resistances:
        facts.append("resistant to " + ", ".join(resistances))
    detail = "; ".join(facts) if facts else "no confirmed weakness or resistance"
    return {"kind": "ENEMY", "text": f"A reliable source says {enemy['name']} is {detail}.",
            "subject": enemy["name"]}


def _wealth_rumor(player_id: int) -> dict | None:
    targets = execute(
        """SELECT id,character_name,credits FROM players
           WHERE id!=? AND is_banned=0 AND retired_at IS NULL AND character_name IS NOT NULL
           ORDER BY COALESCE(last_login_at,created_at) DESC""", (player_id,)
    )
    if not targets:
        return None
    target = random.choice(targets)
    band = _wealth_band(int(target["credits"]))
    with exclusive_transaction():
        execute_write(
            """INSERT INTO player_wealth_intel
               (observer_player_id,target_player_id,wealth_band,credits_snapshot,learned_at)
               VALUES(?,?,?,?,?) ON CONFLICT(observer_player_id,target_player_id) DO UPDATE SET
               wealth_band=excluded.wealth_band,credits_snapshot=excluded.credits_snapshot,
               learned_at=excluded.learned_at""",
            (player_id, target["id"], band, target["credits"], datetime.utcnow().isoformat()),
        )
    return {"kind": "WEALTH", "text": f"Word around the bar: {target['character_name']} is {band.lower()}.",
            "subject": target["character_name"]}


def grant_tavern_rumor(player_id: int) -> dict:
    """Grant one useful rumor, preferring undiscovered enemy intelligence."""
    wealth_available = execute_one(
        "SELECT 1 FROM players WHERE id!=? AND is_banned=0 AND retired_at IS NULL LIMIT 1",
        (player_id,),
    )
    if wealth_available and random.random() < 0.35:
        rumor = _wealth_rumor(player_id) or _enemy_rumor(player_id)
    else:
        rumor = _enemy_rumor(player_id) or _wealth_rumor(player_id)
    rumor = rumor or {"kind": "NONE", "text": "The regulars have nothing new tonight.", "subject": None}
    with exclusive_transaction():
        execute_write(
            """INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category)
               VALUES('PERSONAL',?,?,'RUMOR')""", (player_id, rumor["text"]),
        )
    return rumor
