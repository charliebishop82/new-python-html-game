"""Behavior-derived public titles and private reputation progress."""

from database import execute_one


def reputation_profile(player_id: int) -> dict:
    """Calculate titles from permanent records so reputation never becomes stale."""
    row = execute_one(
        """SELECT p.level,COALESCE(ps.pvp_kills,0) pvp,
          COALESCE((SELECT SUM(kill_count) FROM boss_instances WHERE player_id=p.id),0) bosses,
          COALESCE((SELECT SUM(kill_count) FROM minion_instances WHERE player_id=p.id),0) minions,
          COALESCE((SELECT SUM(damage) FROM world_boss_contributions WHERE player_id=p.id),0) world_damage,
          COALESCE((SELECT COUNT(*) FROM item_history WHERE player_id=p.id AND event_type='STOLEN_BY_ME'),0) thefts,
          COALESCE((SELECT COUNT(*) FROM inventory_items WHERE player_id=p.id AND item_type='SPECIAL'),0) specials,
          COALESCE((SELECT COUNT(*) FROM combat_sessions WHERE status='RESOLVED' AND
            (attacker_player_id=p.id OR defender_player_id=p.id)),0) combats
          FROM players p LEFT JOIN player_stats ps ON ps.player_id=p.id WHERE p.id=?""", (player_id,)
    ) or {}
    earned = []
    checks = [
        ("Worldbreaker", row.get("world_damage", 0) >= 250, "Deal 250 damage to world bosses"),
        ("Boss Slayer", row.get("bosses", 0) >= 5, "Defeat 5 bosses"),
        ("Duelist", row.get("pvp", 0) >= 3, "Win 3 PvP battles"),
        ("Minion Hunter", row.get("minions", 0) >= 10, "Defeat 10 minions"),
        ("Master Thief", row.get("thefts", 0) >= 3, "Steal 3 items"),
        ("Collector", row.get("specials", 0) >= 4, "Own 4 special items"),
        ("Veteran", row.get("combats", 0) >= 20, "Complete 20 battles"),
    ]
    for name, met, requirement in checks:
        if met:
            earned.append({"name": name, "requirement": requirement})
    return {"primary": earned[0]["name"] if earned else "Unproven", "earned": earned,
            "counters": row, "milestones": checks}
