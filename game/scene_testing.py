"""Consequence-free administrator simulations for Cinematic Scenes.

The tester deliberately runs the real scene selection, reward, and isolated
three-actor combat functions against a temporary clone of a selected player.
Everything occurs inside a database savepoint that is always rolled back, so
the report reflects real rules without changing either the selected character
or the game world.
"""

import uuid

from database import execute, execute_one, get_db, get_player
from scene_combat import begin_scene_combat, take_scene_combat_turn
from scenes import resolve_choice, start_scene


TEST_STRATEGIES = {
    "ATTACK": "Attack every round",
    "OBSERVE_ATTACK": "Observe once, then attack",
    "PROTECT_ATTACK": "Protect the ally once, then attack",
    "SUPPORT": "Assist a wounded ally; otherwise attack",
}


def _clone_player(source_id: int, full_health: bool) -> int:
    """Clone a player and their perks inside the caller's rollback savepoint."""
    db = get_db()
    source = execute_one("SELECT * FROM players WHERE id=?", (source_id,))
    if not source:
        raise ValueError("Select an existing player for the simulation.")
    token = uuid.uuid4().hex
    columns = [row["name"] for row in db.execute("PRAGMA table_info(players)")
               if row["name"] != "id"]
    values = [source.get(column) for column in columns]
    for column, value in {
        "username": f"scene_test_{token}", "email": f"scene_test_{token}@invalid.local",
        "character_name": f"{source['character_name']} [SIMULATION]",
        "in_combat": 0, "in_scene_combat": 0, "pending_levelup": 0, "pending_perk": 0,
        "is_banned": 0, "retired_at": None,
    }.items():
        if column in columns:
            values[columns.index(column)] = value
    if full_health and "current_hp" in columns:
        values[columns.index("current_hp")] = get_player(source_id)["max_hp"]
    # The test should never be blocked by AP because none will be retained.
    if "current_ap" in columns:
        values[columns.index("current_ap")] = 999
    placeholders = ",".join("?" for _ in columns)
    cursor = db.execute(
        f"INSERT INTO players({','.join(columns)}) VALUES({placeholders})", tuple(values)
    )
    clone_id = cursor.lastrowid
    db.execute("INSERT INTO player_stats(player_id) VALUES(?)", (clone_id,))
    for perk in execute(
        "SELECT perk_id,level_chosen,acquired_at FROM player_perks WHERE player_id=?",
        (source_id,),
    ):
        db.execute(
            """INSERT INTO player_perks(player_id,perk_id,level_chosen,acquired_at)
               VALUES(?,?,?,?)""",
            (clone_id, perk["perk_id"], perk["level_chosen"], perk["acquired_at"]),
        )
    return clone_id


def _strategy_action(strategy: str, state: dict, turn: int) -> str:
    if strategy == "OBSERVE_ATTACK" and turn == 0:
        return "OBSERVE"
    if strategy == "PROTECT_ATTACK" and turn == 0:
        return "PROTECT"
    if strategy == "SUPPORT" and state["protagonist_hp"] < state["protagonist_max_hp"] * .55:
        return "ASSIST"
    return "ATTACK"


def simulate_scene(player_id: int, scene_id: int, choice_id: int,
                   forced_roll: int | None = None, strategy: str = "ATTACK",
                   full_health: bool = True) -> dict:
    """Run real scene code against a temporary clone and return its report."""
    if strategy not in TEST_STRATEGIES:
        raise ValueError("Unknown test strategy.")
    db = get_db()
    savepoint = f"scene_admin_test_{uuid.uuid4().hex}"
    db.execute(f"SAVEPOINT {savepoint}")
    try:
        clone_id = _clone_player(player_id, full_health)
        before = get_player(clone_id)
        attempt = start_scene(clone_id, scene_id)
        if attempt["scene"]["id"] != scene_id:
            raise ValueError("The requested scene is not eligible for that player's level.")
        choice = next((row for row in attempt["scene"]["choices"] if row["id"] == choice_id), None)
        if not choice:
            raise ValueError("Select a choice belonging to the selected scene.")
        challenge = resolve_choice(clone_id, attempt["attempt_id"], choice_id, forced_roll)
        combat = None
        actions = []
        if challenge["combat_pending"]:
            combat = begin_scene_combat(clone_id, attempt["attempt_id"])
            turn = 0
            while combat["status"] == "ACTIVE" and turn < 30:
                action = _strategy_action(strategy, combat, turn)
                actions.append(action)
                combat = take_scene_combat_turn(
                    clone_id, combat["id"], action, combat["version"]
                )
                turn += 1
        after = get_player(clone_id)
        report = {
            "source_player": get_player(player_id), "scene": attempt["scene"],
            "choice": choice, "challenge": challenge, "combat": combat,
            "actions": actions, "strategy": strategy,
            "projected": {
                "xp": after["xp"] - before["xp"],
                "credits": after["credits"] - before["credits"],
                "hp_change": after["current_hp"] - before["current_hp"],
            },
        }
        return report
    finally:
        db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        db.execute(f"RELEASE SAVEPOINT {savepoint}")
