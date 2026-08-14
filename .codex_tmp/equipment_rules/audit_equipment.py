import json
import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\charl\OneDrive\Desktop\bbsgame\game\data\game.db")
OUT = Path(r"C:\Users\charl\OneDrive\Desktop\bbsgame\.codex_tmp\equipment_rules\equipment_audit.json")
CORE = ("str_bonus", "end_bonus", "agi_bonus", "lck_bonus", "per_bonus")


def item_tier(row, kind):
    if kind == "special":
        return "WORLD_BOSS" if row["association_type"] == "WorldBoss" else "ORDINARY"
    return "WORLD_BOSS" if str(row["associated_to"] or "").endswith("(WorldBoss)") else "ORDINARY"


def core_total(row):
    return sum(int(row[field] or 0) for field in CORE)


def add(results, severity, kind, row, rule, actual, limit):
    results.append({
        "severity": severity,
        "kind": kind,
        "item": row["name"],
        "association": row["associated_to"],
        "rule": rule,
        "actual": actual,
        "limit": limit,
    })


def audit():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    issues = []
    counts = {}

    for kind, table in (("weapon", "weapons"), ("armor", "armor"), ("special", "special_items")):
        rows = db.execute(f"SELECT * FROM {table} WHERE is_active=1 ORDER BY name").fetchall()
        counts[kind] = len(rows)
        for row in rows:
            tier = item_tier(row, kind)
            total = core_total(row)
            max_core = max(int(row[field] or 0) for field in CORE)

            if kind == "weapon":
                if tier == "ORDINARY":
                    if total > 8: add(issues, "VIOLATION", kind, row, "ordinary core attribute total", total, 8)
                    if max_core > 5: add(issues, "VIOLATION", kind, row, "ordinary single core attribute", max_core, 5)
                    if max_core == 5 and total > 6: add(issues, "WARNING", kind, row, "signature +5 requires reduced supporting bonuses", total, "review")
                else:
                    if not 10 <= total <= 12: add(issues, "VIOLATION", kind, row, "world-boss core attribute total", total, "10-12")
                    if max_core > 4: add(issues, "VIOLATION", kind, row, "world-boss single core attribute", max_core, 4)
                    if str(row["damage_die"]).lower() != "d12": add(issues, "VIOLATION", kind, row, "world-boss damage die", row["damage_die"], "d12")

            elif kind == "armor":
                ac = int(row["ac_bonus"] or 0)
                resistance_count = sum(bool(row[f"res_{t}"]) for t in ("blade", "blunt", "ballistic", "energy", "arcane", "explosive", "venom"))
                if tier == "ORDINARY":
                    if ac > 4: add(issues, "VIOLATION", kind, row, "ordinary direct AC", ac, 4)
                    if total > 6: add(issues, "VIOLATION", kind, row, "ordinary core attribute total", total, 6)
                    if max_core > 3: add(issues, "VIOLATION", kind, row, "ordinary single core attribute", max_core, 3)
                    if resistance_count > 3 and (ac >= 4 or total >= 5):
                        add(issues, "WARNING", kind, row, "broad resistance plus high defense/attributes", resistance_count, "review")
                else:
                    if not 5 <= ac <= 7: add(issues, "VIOLATION", kind, row, "world-boss direct AC", ac, "5-7")
                    if not 7 <= total <= 10: add(issues, "VIOLATION", kind, row, "world-boss core attribute total", total, "7-10")
                    if max_core > 3: add(issues, "VIOLATION", kind, row, "world-boss single core attribute", max_core, 3)
                    if ac == 7 and int(row["agi_bonus"] or 0) > 1:
                        add(issues, "VIOLATION", kind, row, "top AC cannot also carry high AGI", row["agi_bonus"], 1)

            else:
                def over(field, cap, label=None):
                    value = float(row[field] or 0)
                    if value > cap:
                        add(issues, "VIOLATION", kind, row, label or field, value, cap)

                if tier == "ORDINARY":
                    if total > 6: add(issues, "VIOLATION", kind, row, "ordinary core attribute total", total, 6)
                    if max_core > 4: add(issues, "VIOLATION", kind, row, "ordinary single core attribute", max_core, 4)
                    for field, cap, label in (
                        ("initiative_bonus", 3, "initiative"), ("ac_bonus", 2, "direct AC"),
                        ("bonus_damage_amount", 5, "typed bonus damage"), ("crit_chance_bonus", .05, "critical chance"),
                        ("crit_dmg_multiplier", .25, "critical damage multiplier"), ("xp_multiplier", .15, "XP multiplier"),
                        ("credit_multiplier", .10, "credit multiplier"), ("bonus_ap", 2, "bonus AP"),
                        ("hp_regen_bonus", 4, "HP regeneration"), ("durability_reduction", .15, "durability reduction"),
                        ("shop_discount", .10, "shop discount"), ("sell_bonus", .10, "sell bonus"),
                        ("encounter_bonus", .15, "encounter modifier"),
                    ): over(field, cap, label)
                else:
                    if not 8 <= total <= 11: add(issues, "VIOLATION", kind, row, "world-boss core attribute total", total, "8-11")
                    if max_core > 3: add(issues, "VIOLATION", kind, row, "world-boss single core attribute", max_core, 3)
                    for field, low, high, label in (
                        ("initiative_bonus", 2, 3, "initiative"), ("ac_bonus", 2, 3, "direct AC"),
                        ("bonus_damage_amount", 5, 7, "typed bonus damage"),
                    ):
                        value = float(row[field] or 0)
                        if not low <= value <= high: add(issues, "VIOLATION", kind, row, label, value, f"{low}-{high}")
                    for field, cap, label in (
                        ("crit_chance_bonus", .05, "critical chance"), ("crit_dmg_multiplier", .25, "critical damage multiplier"),
                        ("xp_multiplier", .10, "XP multiplier"), ("credit_multiplier", .10, "credit multiplier"),
                        ("bonus_ap", 2, "bonus AP"), ("hp_regen_bonus", 1, "HP regeneration"),
                        ("durability_reduction", .10, "durability reduction"), ("shop_discount", .05, "shop discount"),
                        ("sell_bonus", .10, "sell bonus"), ("encounter_bonus", .10, "encounter modifier"),
                    ): over(field, cap, label)
                    if row["extra_attack"]: add(issues, "VIOLATION", kind, row, "world-boss unconditional ExtraAttack", True, False)

                if row["extra_attack"] and int(row["bonus_damage_amount"] or 0) > 3:
                    add(issues, "VIOLATION", kind, row, "ExtraAttack plus typed damage", row["bonus_damage_amount"], 3)
                if row["extra_attack"] and int(row["ac_bonus"] or 0) > 1:
                    add(issues, "VIOLATION", kind, row, "ExtraAttack plus direct AC", row["ac_bonus"], 1)

    loadouts = []
    players = db.execute("SELECT * FROM players WHERE retired_at IS NULL ORDER BY character_name").fetchall()
    for player in players:
        def equipped(table, inv_id):
            if not inv_id: return None
            return db.execute(f"SELECT x.* FROM inventory_items i JOIN {table} x ON x.id=i.item_id WHERE i.id=?", (inv_id,)).fetchone()
        weapon = equipped("weapons", player["equipped_weapon_id"])
        armor = equipped("armor", player["equipped_armor_id"])
        special = equipped("special_items", player["equipped_special_id"])
        agi = int(player["agi_stat"] or 0) + sum(int(x["agi_bonus"] or 0) for x in (weapon, armor, special) if x)
        ac = 10 + agi // 2 + (int(armor["ac_bonus"] or 0) if armor else 0) + (int(special["ac_bonus"] or 0) if special else 0)
        record = {"character": player["character_name"], "level": player["level"], "ac_without_perks": ac,
                  "effective_agi_without_perks": agi, "weapon": weapon["name"] if weapon else None,
                  "armor": armor["name"] if armor else None, "special": special["name"] if special else None}
        if ac >= 25: record["review"] = "AC 25+ before perks"
        loadouts.append(record)

    report = {
        "counts": counts,
        "violations": [x for x in issues if x["severity"] == "VIOLATION"],
        "warnings": [x for x in issues if x["severity"] == "WARNING"],
        "loadouts": sorted(loadouts, key=lambda x: x["ac_without_perks"], reverse=True),
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"counts": counts, "violation_count": len(report["violations"]),
                      "warning_count": len(report["warnings"]),
                      "loadout_review_count": sum("review" in x for x in loadouts)}, indent=2))
    return report


if __name__ == "__main__":
    audit()
