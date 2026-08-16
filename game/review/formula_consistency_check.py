"""Read-only cross-check between UI-derived and combat-derived character values."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from combat import actions, engine
from database import execute, get_all_settings, get_player, get_player_equipped
from routes.character import _calc_derived_stats
import config_defaults as cfg
from flask import Flask


def main():
    app = Flask(__name__)
    results = {"players": [], "pure_formula_checks": {}}
    with app.app_context():
        settings = get_all_settings()
        for row in execute("SELECT id,character_name FROM players ORDER BY id"):
            player = get_player(row["id"])
            equipped = get_player_equipped(player)
            ui = _calc_derived_stats(player, equipped, settings)
            combat_equipped = actions._load_equipped(player)
            combat = actions.apply_equipped_stat_bonuses(player, combat_equipped)
            combat_ac = engine.calc_ac(combat, combat_equipped.get("armor"))
            checks = {
            "str": [ui["str"], combat["str_stat"]],
            "end": [ui["end"], combat["end_stat"]],
            "agi": [ui["agi"], combat["agi_stat"]],
            "lck": [ui["lck"], combat["lck_stat"]],
            "per": [ui["per"], combat["per_stat"]],
            "max_hp": [ui["max_hp"], combat["max_hp"]],
            "ac": [ui["ac"], combat_ac],
            "daily_ap_cap_aware": [min(ui["daily_ap"], settings.get("AP_CARRYOVER_CAP", cfg.AP_CARRYOVER_CAP)), player["max_ap"]],
            "passive_regen": [ui["passive_regen"], player["passive_regen"]],
            }
            mismatches = {key: value for key, value in checks.items() if value[0] != value[1]}
            results["players"].append({"id": row["id"], "name": row["character_name"], "checks": checks, "mismatches": mismatches})

        results["pure_formula_checks"] = {
            "stat_mod_odd": engine.stat_mod(7) == 3,
            "proficiency_levels": [engine.proficiency_bonus(n) for n in (1, 4, 5, 8, 9, 13, 17)],
            "weapon_tiers": [engine.weapon_tier_damage_bonus({"level": n}) for n in range(1, 19)],
            "armor_tiers": [engine.armor_tier_ac_bonus({"level": n}) for n in range(1, 19)],
            "natural_20_hits_ac_99": engine.hits_ac(1, 99, 20),
            "natural_1_misses_ac_1": not engine.hits_ac(99, 1, 1),
            "single_resistance": engine.resolve_resistance(20, "Blade", {"res_blade": 1}, None)[0],
            "stacked_resistance": engine.resolve_resistance(20, "Blade", {"res_blade": 1}, {"res_blade": 1})[0],
            "weakness": engine.resolve_weakness(20, "Blade", {"weak_blade": 1})[0],
        }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
