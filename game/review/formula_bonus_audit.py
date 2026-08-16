"""Read-only audit of the active bonus vocabulary and imported combat statistics."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "game.db"
OUTPUT = ROOT / "review" / "formula_bonus_audit_results.json"

BONUS_FIELDS = (
    "str_bonus", "end_bonus", "agi_bonus", "lck_bonus", "per_bonus",
    "initiative_bonus", "extra_attack", "crit_chance_bonus",
    "crit_dmg_multiplier", "ac_bonus", "res_blade", "res_blunt",
    "res_ballistic", "res_energy", "res_arcane", "res_explosive",
    "res_venom", "bonus_damage_amount", "xp_multiplier",
    "credit_multiplier", "steal_bonus", "bonus_ap", "hp_regen_bonus",
    "durability_reduction", "shop_discount", "sell_bonus", "encounter_bonus",
)
DAMAGE_TYPES = {"Blade", "Blunt", "Ballistic", "Energy", "Arcane", "Explosive", "Venom"}


def query(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def column_exists(conn, table, column):
    return column in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def main():
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    report = {"database": str(DB), "bonus_fields": {}, "content": {}, "integrity": {}}

    gameplay_files = [
        p for p in ROOT.rglob("*.py")
        if "__pycache__" not in p.parts and p.name not in {"importer.py", "admin.py"}
        and "review" not in p.parts
    ]
    source = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in gameplay_files)
    for field in BONUS_FIELDS:
        storage = {}
        for table in ("special_items", "perks"):
            if column_exists(conn, table, field):
                row = query(conn, f"SELECT COUNT(*) rows, SUM(CASE WHEN {field}<>0 THEN 1 ELSE 0 END) nonzero, MIN({field}) minimum, MAX({field}) maximum FROM {table}")[0]
                storage[table] = row
        report["bonus_fields"][field] = {
            "storage": storage,
            "gameplay_source_mentions": len(re.findall(rf"\b{re.escape(field)}\b", source)),
        }

    for table, level, fields in (
        ("weapons", "level", ("damage_die", "damage_type", "str_bonus", "end_bonus", "agi_bonus", "lck_bonus", "per_bonus")),
        ("armor", "level", ("ac_bonus", "res_blade", "res_blunt", "res_ballistic", "res_energy", "res_arcane", "res_explosive", "res_venom", "str_bonus", "end_bonus", "agi_bonus", "lck_bonus", "per_bonus")),
        ("bosses", "level", ("max_hp", "str_stat", "end_stat", "agi_stat", "lck_stat", "per_stat", "res_blade", "res_blunt", "res_ballistic", "res_energy", "res_arcane", "res_explosive", "res_venom")),
        ("minions", "level", ("max_hp", "str_stat", "end_stat", "agi_stat", "lck_stat", "per_stat", "res_blade", "res_blunt", "res_ballistic", "res_energy", "res_arcane", "res_explosive", "res_venom")),
        ("world_bosses", "level", ("max_hp", "str_stat", "end_stat", "agi_stat", "lck_stat", "per_stat", "res_blade", "res_blunt", "res_ballistic", "res_energy", "res_arcane", "res_explosive", "res_venom")),
    ):
        summary = {"rows": query(conn, f"SELECT COUNT(*) count FROM {table} WHERE is_active=1")[0]["count"]}
        for field in fields:
            if column_exists(conn, table, field):
                summary[field] = query(conn, f"SELECT MIN({field}) minimum, MAX({field}) maximum, AVG({field}) average FROM {table} WHERE is_active=1")[0]
        report["content"][table] = summary

    report["integrity"]["invalid_weapon_dice"] = query(conn, "SELECT id,name,damage_die FROM weapons WHERE is_active=1 AND damage_die NOT GLOB '*d[0-9]*'")
    placeholders = ",".join("?" for _ in DAMAGE_TYPES)
    report["integrity"]["invalid_weapon_damage_types"] = query(conn, f"SELECT id,name,damage_type FROM weapons WHERE is_active=1 AND damage_type NOT IN ({placeholders})", tuple(DAMAGE_TYPES))
    report["integrity"]["invalid_special_damage_types"] = query(conn, f"SELECT id,name,bonus_damage_type FROM special_items WHERE is_active=1 AND COALESCE(bonus_damage_amount,0)<>0 AND bonus_damage_type NOT IN ({placeholders})", tuple(DAMAGE_TYPES))
    report["integrity"]["typed_specials_missing_amount"] = query(conn, "SELECT id,name,bonus_damage_type,bonus_damage_amount FROM special_items WHERE is_active=1 AND bonus_damage_type IS NOT NULL AND COALESCE(bonus_damage_amount,0)=0")
    report["integrity"]["orphan_equipment"] = query(conn, """
        SELECT p.id,p.character_name,slot,inv_id FROM (
          SELECT id,character_name,'weapon' slot,equipped_weapon_id inv_id FROM players
          UNION ALL SELECT id,character_name,'armor',equipped_armor_id FROM players
          UNION ALL SELECT id,character_name,'special',equipped_special_id FROM players
        ) p LEFT JOIN inventory_items ii ON ii.id=p.inv_id AND ii.player_id=p.id
        WHERE p.inv_id IS NOT NULL AND ii.id IS NULL
    """)
    report["integrity"]["hp_above_effective_cap"] = query(conn, """
        SELECT p.id,p.character_name,p.current_hp,
               10+p.end_stat+5*p.level+
               COALESCE(w.end_bonus,0)+COALESCE(a.end_bonus,0)+COALESCE(s.end_bonus,0)+
               COALESCE((SELECT SUM(pk.end_bonus) FROM player_perks pp JOIN perks pk ON pk.id=pp.perk_id WHERE pp.player_id=p.id),0) calculated_cap
        FROM players p
        LEFT JOIN inventory_items iw ON iw.id=p.equipped_weapon_id LEFT JOIN weapons w ON w.id=iw.item_id
        LEFT JOIN inventory_items ia ON ia.id=p.equipped_armor_id LEFT JOIN armor a ON a.id=ia.item_id
        LEFT JOIN inventory_items isp ON isp.id=p.equipped_special_id LEFT JOIN special_items s ON s.id=isp.item_id
        WHERE p.current_hp > 10+p.end_stat+5*p.level+COALESCE(w.end_bonus,0)+COALESCE(a.end_bonus,0)+COALESCE(s.end_bonus,0)+COALESCE((SELECT SUM(pk.end_bonus) FROM player_perks pp JOIN perks pk ON pk.id=pp.perk_id WHERE pp.player_id=p.id),0)
    """)

    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
