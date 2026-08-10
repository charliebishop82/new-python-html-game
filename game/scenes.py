"""Dormant version-one engine for Excel-authored cinematic scenarios.

The feature gate remains off for players. This module deliberately owns the
selection, AP charge, attribute roll, rewards, audit history, and staged
effects so activating the interface later will not require rewriting rules.
Three-actor combat is the version-two boundary: failed choices record the
required enemy and protagonist behavior without pretending the existing
two-sided combat engine already supports an allied actor.
"""

import json
import random
from datetime import datetime

import config_defaults as cfg
from database import (execute, execute_one, execute_write, exclusive_transaction,
                      get_all_settings, get_player, get_player_equipped,
                      get_player_perk_bonuses)


ATTRIBUTES = {"STR": "str_stat", "END": "end_stat", "AGI": "agi_stat",
              "LCK": "lck_stat", "PER": "per_stat"}


def player_scenes_enabled() -> bool:
    """Return the administrator-controlled public feature gate."""
    return bool(get_all_settings().get("SCENES_PLAYER_ENABLED",
                                       cfg.SCENES_PLAYER_ENABLED))


def eligible_scenes(player_id: int) -> list[dict]:
    """Return active level-appropriate scenes with completion information."""
    player = get_player(player_id)
    if not player:
        return []
    rows = execute(
        """SELECT s.*,COUNT(sa.id) attempt_count,
          MAX(CASE WHEN sa.succeeded=1 THEN 1 ELSE 0 END) completed
          FROM scenes s LEFT JOIN scene_attempts sa
            ON sa.scene_id=s.id AND sa.player_id=?
          WHERE s.is_active=1 AND s.min_level<=?
          GROUP BY s.id ORDER BY s.movie_name,s.scene_name""",
        (player_id, player["level"]),
    )
    return rows


def choose_scene(player_id: int, scene_id: int | None = None) -> dict | None:
    """Choose a requested eligible scene or make a weighted random selection."""
    rows = eligible_scenes(player_id)
    if scene_id is not None:
        return next((row for row in rows if row["id"] == scene_id), None)
    if not rows:
        return None
    return random.choices(rows, weights=[max(1, row["weight"]) for row in rows], k=1)[0]


def scene_with_choices(scene_id: int) -> dict | None:
    """Load one active scene and its five attribute options."""
    scene = execute_one("SELECT * FROM scenes WHERE id=? AND is_active=1", (scene_id,))
    if not scene:
        return None
    scene["choices"] = execute(
        "SELECT * FROM scene_choices WHERE scene_id=? ORDER BY CASE attribute "
        "WHEN 'STR' THEN 1 WHEN 'END' THEN 2 WHEN 'AGI' THEN 3 WHEN 'LCK' THEN 4 ELSE 5 END",
        (scene_id,),
    )
    return scene


def start_scene(player_id: int, scene_id: int | None = None) -> dict:
    """Charge AP once and create a durable choice-pending attempt."""
    player = get_player(player_id)
    if not player:
        raise ValueError("Player not found.")
    if player["in_combat"]:
        raise ValueError("A scene cannot begin during combat.")
    pending = execute_one(
        "SELECT id,scene_id FROM scene_attempts WHERE player_id=? AND status='CHOICE_PENDING' ORDER BY id DESC",
        (player_id,),
    )
    if pending:
        scene = scene_with_choices(pending["scene_id"])
        return {"attempt_id": pending["id"], "scene": scene, "resumed": True}
    scene = choose_scene(player_id, scene_id)
    if not scene:
        raise ValueError("No eligible cinematic scenes are available.")
    authored_cost = scene.get("ap_cost")
    cost = max(0, int(authored_cost if authored_cost is not None else
                      get_all_settings().get("AP_COST_SCENE", cfg.AP_COST_SCENE)))
    if player["current_ap"] < cost:
        raise ValueError(f"Not enough AP to enter this scene (need {cost}).")
    with exclusive_transaction():
        execute_write("UPDATE players SET current_ap=current_ap-? WHERE id=?", (cost, player_id))
        attempt_id = execute_write(
            "INSERT INTO scene_attempts(player_id,scene_id,status) VALUES(?,?,'CHOICE_PENDING')",
            (player_id, scene["id"]),
        )
        execute_write(
            """INSERT INTO player_activity_log
               (player_id,status,category,action,message,details_json,source)
               VALUES(?,'SUCCESS','SCENE','scene_start',?,?,'GAME')""",
            (player_id, f"Entered {scene['scene_name']}",
             json.dumps({"attempt_id": attempt_id, "scene_key": scene["scene_key"],
                         "ap_cost": cost})),
        )
    return {"attempt_id": attempt_id, "scene": scene_with_choices(scene["id"]),
            "resumed": False}


def _attribute_bonus(player_id: int, attribute: str) -> int:
    """Calculate the displayed stat plus every equipped/perk bonus for one roll."""
    player = get_player(player_id)
    attr = attribute.upper()
    if attr not in ATTRIBUTES:
        raise ValueError("Unknown scene attribute.")
    bonus = int(player[ATTRIBUTES[attr]])
    field = f"{attr.lower()}_bonus"
    equipped = get_player_equipped(player)
    bonus += sum(int((item or {}).get(field, 0) or 0) for item in equipped.values())
    bonus += int(get_player_perk_bonuses(player_id).get(field, 0) or 0)
    return bonus


def resolve_choice(player_id: int, attempt_id: int, choice_id: int,
                   forced_roll: int | None = None) -> dict:
    """Resolve one choice exactly once and record rewards/effects atomically."""
    attempt = execute_one(
        """SELECT sa.*,s.scene_name,s.scene_key,s.first_completion_xp,
          s.first_completion_credits,s.enemy_type,s.enemy_name,s.protagonist_name,
          s.protagonist_behavior,s.enemy_targeting
          FROM scene_attempts sa JOIN scenes s ON s.id=sa.scene_id
          WHERE sa.id=? AND sa.player_id=?""", (attempt_id, player_id),
    )
    if not attempt or attempt["status"] != "CHOICE_PENDING":
        raise ValueError("This scene choice is no longer available.")
    choice = execute_one(
        "SELECT * FROM scene_choices WHERE id=? AND scene_id=?",
        (choice_id, attempt["scene_id"]),
    )
    if not choice:
        raise ValueError("That choice does not belong to this scene.")
    roll = max(1, min(20, int(forced_roll))) if forced_roll is not None else random.randint(1, 20)
    bonus = _attribute_bonus(player_id, choice["attribute"])
    total = roll + bonus
    succeeded = total >= int(choice["difficulty"])
    previous_completion = execute_one(
        "SELECT 1 found FROM scene_attempts WHERE player_id=? AND scene_id=? AND succeeded=1 AND id<>? LIMIT 1",
        (player_id, attempt["scene_id"], attempt_id),
    )
    first = succeeded and not previous_completion
    xp = int(choice["success_xp"] if succeeded else 0) + (int(attempt["first_completion_xp"]) if first else 0)
    credits = int(choice["success_credits"] if succeeded else 0) + (int(attempt["first_completion_credits"]) if first else 0)
    effect = choice["success_effect"] if succeeded else choice["failure_effect"]
    effect_value = choice["success_value"] if succeeded else choice["failure_value"]
    needs_combat = bool(not succeeded and choice["combat_on_failure"])
    status = "COMBAT_PENDING" if needs_combat else ("SUCCEEDED" if succeeded else "FAILED")
    outcome_text = choice["success_text"] if succeeded else choice["failure_text"]
    now = datetime.utcnow().isoformat()
    with exclusive_transaction():
        execute_write(
            """UPDATE scene_attempts SET choice_id=?,status=?,roll=?,attribute_bonus=?,
               total_roll=?,difficulty=?,succeeded=?,xp_awarded=?,credits_awarded=?,
               first_completion=?,outcome_text=?,resolved_at=? WHERE id=? AND status='CHOICE_PENDING'""",
            (choice_id, status, roll, bonus, total, choice["difficulty"], int(succeeded),
             xp, credits, int(first), outcome_text, now, attempt_id),
        )
        if xp or credits:
            execute_write("UPDATE players SET xp=xp+?,credits=credits+? WHERE id=?",
                          (xp, credits, player_id))
        if effect:
            execute_write(
                "INSERT INTO scene_effects(player_id,attempt_id,effect_type,value) VALUES(?,?,?,?)",
                (player_id, attempt_id, effect, float(effect_value or 0)),
            )
        message = (f"Scene success: {attempt['scene_name']}" if succeeded
                   else f"Scene challenge failed: {attempt['scene_name']}")
        execute_write(
            """INSERT INTO player_activity_log
               (player_id,status,category,action,message,details_json,source)
               VALUES(?,?,?,?,?,?,'GAME')""",
            (player_id, "SUCCESS" if succeeded else "FAILED", "SCENE", "scene_choice",
             message, json.dumps({"attempt_id": attempt_id, "roll": roll,
                                  "bonus": bonus, "difficulty": choice["difficulty"]})),
        )
        execute_write(
            """INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category)
               VALUES('PERSONAL',?,?, 'SCENE')""",
            (player_id, outcome_text),
        )
    if xp:
        from combat.engine import check_level_up
        refreshed = get_player(player_id)
        check_level_up(player_id, refreshed["xp"], refreshed["level"])
    return {"attempt_id": attempt_id, "scene_name": attempt["scene_name"],
            "choice": choice, "roll": roll, "bonus": bonus, "total": total,
            "succeeded": succeeded, "first_completion": first, "xp": xp,
            "credits": credits, "effect": effect, "effect_value": effect_value,
            "combat_pending": needs_combat, "enemy_type": attempt["enemy_type"],
            "enemy_name": attempt["enemy_name"], "protagonist_name": attempt["protagonist_name"],
            "outcome_text": outcome_text}


def scene_catalog() -> list[dict]:
    """Admin-facing catalog with choice and attempt counts."""
    return execute(
        """SELECT s.*,COUNT(DISTINCT sc.id) choice_count,COUNT(DISTINCT sa.id) attempt_count,
          COUNT(DISTINCT CASE WHEN sa.succeeded=1 THEN sa.id END) success_count
          FROM scenes s LEFT JOIN scene_choices sc ON sc.scene_id=s.id
          LEFT JOIN scene_attempts sa ON sa.scene_id=s.id
          GROUP BY s.id ORDER BY s.movie_name,s.scene_name"""
    )
