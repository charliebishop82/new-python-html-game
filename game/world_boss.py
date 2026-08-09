"""Weekly shared world-boss lifecycle, standings, logs, and prize awards."""

import hashlib
import json
import random
import math
from datetime import datetime, timedelta, timezone

import config_defaults as cfg
from database import (execute, execute_one, execute_write, exclusive_transaction,
                      get_all_settings)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _next_monday(now):
    days = (7 - now.weekday()) % 7
    if days == 0:
        days = 7
    return (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)


def get_active_event():
    """Return the active shared encounter with its imported boss definition."""
    return execute_one(
        """SELECT e.*,w.name,w.level,w.str_stat,w.end_stat,w.agi_stat,w.lck_stat,
                  w.per_stat,w.phase2_hp_percent,w.phase3_hp_percent,w.flavor_text,
                  w.description,w.special_attack_name,w.special_attack_die,
                  w.special_attack_damage_type,w.special_attack_flavor,
                  w.special_buff_name,w.special_buff_type,w.special_buff_value,
                  w.special_buff_damage_type,w.special_buff_flavor,
                  w.res_blade,w.res_blunt,w.res_ballistic,w.res_energy,w.res_arcane,
                  w.res_explosive,w.res_venom,w.weak_blade,w.weak_blunt,
                  w.weak_ballistic,w.weak_energy,w.weak_arcane,w.weak_explosive,w.weak_venom
           FROM world_boss_events e JOIN world_bosses w ON w.id=e.world_boss_id
           WHERE e.status='ACTIVE' ORDER BY e.id DESC LIMIT 1"""
    )


def activate_next_event(now=None, forced_boss_id=None):
    """Activate one unused boss; completed bosses never return in this game."""
    now = now or _utcnow()
    if get_active_event() or execute_one(
        "SELECT 1 FROM world_boss_events WHERE status='REWARDS_PENDING' LIMIT 1"
    ):
        return None
    params = ()
    forced = ""
    if forced_boss_id:
        forced, params = "AND w.id=?", (forced_boss_id,)
    choices = execute(
        f"""SELECT w.* FROM world_bosses w WHERE w.is_active=1 {forced}
            AND NOT EXISTS(SELECT 1 FROM world_boss_events e WHERE e.world_boss_id=w.id)
            ORDER BY RANDOM()""", params
    )
    if not choices:
        return None
    boss = choices[0]
    scale = float(get_all_settings().get("WORLD_BOSS_HP_MULTIPLIER", 1.0))
    hp = max(1, int(boss["max_hp"] * scale))
    with exclusive_transaction():
        event_id = execute_write(
            """INSERT INTO world_boss_events
               (world_boss_id,status,starting_hp,current_hp,hp_multiplier,started_at,scheduled_end_at)
               VALUES(?,'ACTIVE',?,?,?,?,?)""",
            (boss["id"], hp, hp, scale, now.isoformat(), _next_monday(now).isoformat())
        )
        _log(event_id, None, "ACTIVATED", f"{boss['name']} has entered the Movie Multiverse.")
    return get_active_event()


def rescale_active_event(multiplier):
    """Adjust an active pool while preserving every point of damage already dealt."""
    multiplier = float(multiplier)
    if not math.isfinite(multiplier):
        raise ValueError("HP multiplier must be a finite number.")
    multiplier = max(0.05, min(5.0, multiplier))
    event = get_active_event()
    if not event:
        raise ValueError("No active world boss can be rescaled.")
    imported = execute_one("SELECT max_hp FROM world_bosses WHERE id=?",
                           (event["world_boss_id"],))
    new_starting = max(1, round(imported["max_hp"] * multiplier))
    damage_already_dealt = max(0, event["starting_hp"] - event["current_hp"])
    new_current = max(0, new_starting - damage_already_dealt)
    with exclusive_transaction():
        execute_write(
            """UPDATE world_boss_events SET starting_hp=?,current_hp=?,hp_multiplier=?
               WHERE id=? AND status='ACTIVE'""",
            (new_starting, new_current, multiplier, event["id"])
        )
        _log(event["id"], None, "ADMIN_BALANCE",
             f"World-boss HP scale changed to {multiplier:.0%}; {new_current} HP remains.",
             {"old_starting_hp": event["starting_hp"], "new_starting_hp": new_starting,
              "preserved_damage": damage_already_dealt})
    if new_current <= 0:
        close_event(event["id"], "ADMIN_SCALE_DEFEAT")
    return execute_one("SELECT * FROM world_boss_events WHERE id=?", (event["id"],))


def standings(event_id):
    """Return damage standings with deterministic audited coin-flip tie order."""
    rows = execute(
        """SELECT c.*,p.character_name,np.player_id IS NOT NULL AS is_npc
           FROM world_boss_contributions c JOIN players p ON p.id=c.player_id
           LEFT JOIN npc_profiles np ON np.player_id=p.id
           WHERE c.event_id=? AND c.attempts>0""", (event_id,)
    )
    def tie_key(row):
        digest = hashlib.sha256(f"{event_id}:{row['player_id']}".encode()).hexdigest()
        return digest
    return sorted(rows, key=lambda row: (-row["damage"], tie_key(row)))


def pending_event_for_player(player_id):
    """Return the newest event on which this player still has a prize action."""
    return execute_one(
        """SELECT e.*,w.name,w.flavor_text,w.description,r.place,r.status AS reward_status,
                  r.selection_deadline,r.id AS reward_id
           FROM world_boss_rewards r JOIN world_boss_events e ON e.id=r.event_id
           JOIN world_bosses w ON w.id=e.world_boss_id
           WHERE r.player_id=? AND r.status='PENDING' ORDER BY e.id DESC LIMIT 1""",
        (player_id,)
    )


def prize_options(event_id, place):
    """List the unclaimed imported weapon, outfit, and special for a placing."""
    event = execute_one("SELECT world_boss_id FROM world_boss_events WHERE id=?", (event_id,))
    if not event:
        return []
    loot = execute_one("SELECT * FROM world_boss_loot WHERE world_boss_id=?",
                       (event["world_boss_id"],))
    if not loot:
        return []
    awarded = {(row["item_type"], row["item_id"]) for row in execute(
        "SELECT item_type,item_id FROM world_boss_rewards WHERE event_id=? AND status='AWARDED'",
        (event_id,)
    )}
    options = []
    for item_type, key, table in (("WEAPON", "weapon_id", "weapons"),
                                  ("ARMOR", "armor_id", "armor"),
                                  ("SPECIAL", "special_item_id", "special_items")):
        item = execute_one(f"SELECT * FROM {table} WHERE id=?", (loot[key],))
        if item and (item_type, item["id"]) not in awarded:
            options.append({**item, "item_type": item_type})
    return options


def claim_prize(player_id, event_id, item_type, item_id, automatic=False):
    """Award the next placing's exclusive item and independent free level."""
    reward = execute_one(
        """SELECT * FROM world_boss_rewards WHERE event_id=? AND player_id=?
           AND status='PENDING'""", (event_id, player_id)
    )
    if not reward:
        raise ValueError("No pending world-boss prize was found.")
    prior = execute_one(
        """SELECT 1 FROM world_boss_rewards WHERE event_id=? AND place<?
           AND status!='AWARDED' LIMIT 1""", (event_id, reward["place"])
    )
    if prior:
        raise ValueError("The player ahead of you must choose first.")
    valid = {(row["item_type"], row["id"]): row
             for row in prize_options(event_id, reward["place"])}
    chosen = valid.get((item_type.upper(), int(item_id)))
    if not chosen:
        raise ValueError("That prize is no longer available.")
    current = execute_one("SELECT * FROM players WHERE id=?", (player_id,))
    new_level = current["level"] + 1
    max_hp = 10 + current["end_stat"] + (5 * new_level)
    with exclusive_transaction():
        inv_id = execute_write(
            """INSERT INTO inventory_items
               (player_id,item_type,item_id,current_durability,acquired_method)
               VALUES(?,?,?,?, 'WORLD_BOSS_REWARD')""",
            (player_id, item_type.upper(), int(item_id),
             int(chosen.get("starting_durability", 100) or 100))
        )
        execute_write(
            """UPDATE world_boss_rewards SET status='AWARDED',item_type=?,item_id=?,awarded_at=?
               WHERE id=?""", (item_type.upper(), int(item_id), _utcnow().isoformat(), reward["id"])
        )
        execute_write(
            """UPDATE players SET level=?,current_hp=?,pending_levelup=pending_levelup+1,
               pending_perk=pending_perk+? WHERE id=?""",
            (new_level, max_hp, 1 if new_level % 3 == 0 else 0, player_id)
        )
        message = (f"World Boss #{reward['place']} reward: {chosen['name']}, plus a free "
                   f"level to Level {new_level}{' (auto-selected)' if automatic else ''}.")
        execute_write(
            """INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category)
               VALUES('PERSONAL',?,?,'WORLD_BOSS_REWARD')""", (player_id, message)
        )
        _log(event_id, player_id, "REWARD", message,
             {"place": reward["place"], "item_type": item_type.upper(),
              "item_id": int(item_id), "inventory_id": inv_id})
        remaining = execute_one(
            "SELECT COUNT(*) AS count FROM world_boss_rewards WHERE event_id=? AND status='PENDING'",
            (event_id,)
        )["count"]
        if remaining == 0:
            execute_write(
                """UPDATE world_boss_events SET status='COMPLETED',rewards_completed_at=? WHERE id=?""",
                (_utcnow().isoformat(), event_id)
            )
    return chosen


def process_expired_rewards(now=None):
    """Auto-select the highest-credit remaining prize when a deadline passes."""
    now = now or _utcnow()
    awarded = []
    for reward in execute(
        """SELECT * FROM world_boss_rewards WHERE status='PENDING'
           AND selection_deadline<=? ORDER BY event_id,place""", (now.isoformat(),)
    ):
        options = prize_options(reward["event_id"], reward["place"])
        if options:
            chosen = max(options, key=lambda item: (item.get("credit_cost", 0), item["name"]))
            claim_prize(reward["player_id"], reward["event_id"],
                        chosen["item_type"], chosen["id"], automatic=True)
            awarded.append(reward["id"])
    return awarded


def record_damage(event_id, player_id, damage):
    """Atomically apply post-resistance damage to the shared pool and ledger."""
    now = _utcnow().isoformat()
    with exclusive_transaction():
        event = execute_one("SELECT * FROM world_boss_events WHERE id=? AND status='ACTIVE'", (event_id,))
        if not event:
            return {"applied": 0, "defeated": True}
        applied = min(max(0, int(damage)), event["current_hp"])
        execute_write("UPDATE world_boss_events SET current_hp=current_hp-? WHERE id=?", (applied, event_id))
        execute_write(
            """INSERT INTO world_boss_contributions
               (event_id,player_id,damage,first_damage_at,last_damage_at)
               VALUES(?,?,?,?,?) ON CONFLICT(event_id,player_id) DO UPDATE SET
               damage=damage+excluded.damage,
               first_damage_at=COALESCE(first_damage_at,excluded.first_damage_at),
               last_damage_at=excluded.last_damage_at""",
            (event_id, player_id, applied, now if applied else None, now)
        )
        player = execute_one("SELECT character_name FROM players WHERE id=?", (player_id,))
        remaining = event["current_hp"] - applied
        _log(event_id, player_id, "DAMAGE",
             f"{player['character_name']} dealt {applied} damage. {remaining} HP remains.",
             {"damage": applied, "remaining_hp": remaining})
        defeated = remaining <= 0
    if defeated:
        close_event(event_id, "DEFEATED", player_id)
    return {"applied": applied, "remaining_hp": max(0, remaining), "defeated": defeated}


def close_event(event_id, reason="WEEK_ENDED", defeated_by=None):
    """Freeze standings and open the sequential 12-hour reward workflow."""
    if not execute_one("SELECT 1 FROM world_boss_events WHERE id=? AND status='ACTIVE'", (event_id,)):
        return
    ranked = standings(event_id)[:3]
    now = _utcnow()
    hours = int(get_all_settings().get("WORLD_BOSS_REWARD_HOURS", 12))
    with exclusive_transaction():
        execute_write(
            """UPDATE world_boss_events SET status='REWARDS_PENDING',ended_at=?,end_reason=?,
               defeated_by_player_id=? WHERE id=?""", (now.isoformat(), reason, defeated_by, event_id)
        )
        for place, row in enumerate(ranked, 1):
            execute_write(
                """INSERT INTO world_boss_rewards(event_id,place,player_id,selection_deadline)
                   VALUES(?,?,?,?)""", (event_id, place, row["player_id"],
                                         (now + timedelta(hours=hours * place)).isoformat())
            )
        if not ranked:
            execute_write(
                """UPDATE world_boss_events SET status='COMPLETED',rewards_completed_at=?
                   WHERE id=?""", (now.isoformat(), event_id)
            )
        tied_damage = sorted({row["damage"] for row in ranked
                              if sum(other["damage"] == row["damage"] for other in ranked) > 1})
        for damage in tied_damage:
            tied = [row for row in ranked if row["damage"] == damage]
            _log(event_id, None, "TIE_BREAK",
                 f"A deterministic audited coin flip ordered a {damage}-damage tie: "
                 + ", ".join(row["character_name"] for row in tied),
                 {"damage": damage, "ordered_player_ids": [row["player_id"] for row in tied]})
        # A shared kill immediately releases everybody who was still viewing
        # an individual attempt. Their accumulated damage remains authoritative.
        active_attempts = execute(
            """SELECT id,attacker_player_id FROM combat_sessions
               WHERE world_boss_event_id=? AND status='ACTIVE'""", (event_id,)
        )
        killer = execute_one("SELECT character_name FROM players WHERE id=?", (defeated_by,)) if defeated_by else None
        end_message = ((killer["character_name"] + " delivered the final blow. The shared fight is over.")
                       if killer else "The weekly battle has ended; final standings are locked.")
        settings = get_all_settings()
        attempt_xp = int(settings.get("WORLD_BOSS_ATTEMPT_XP", cfg.WORLD_BOSS_ATTEMPT_XP))
        attempt_credits = int(settings.get("WORLD_BOSS_ATTEMPT_CREDITS", cfg.WORLD_BOSS_ATTEMPT_CREDITS))
        for attempt in active_attempts:
            execute_write(
                """UPDATE combat_sessions SET status='RESOLVED',result='WORLD_BOSS_ENDED',
                   resolved_at=? WHERE id=?""", (now.isoformat(), attempt["id"])
            )
            execute_write("UPDATE players SET in_combat=0 WHERE id=?",
                          (attempt["attacker_player_id"],))
            # The final hitter's current request performs its own normal
            # attempt finalization; interrupted peers are paid here exactly once.
            if attempt["attacker_player_id"] != defeated_by:
                execute_write("UPDATE players SET xp=xp+?,credits=credits+? WHERE id=?",
                              (attempt_xp, attempt_credits, attempt["attacker_player_id"]))
                execute_write(
                    """UPDATE world_boss_contributions SET xp_earned=xp_earned+?,
                       credits_earned=credits_earned+? WHERE event_id=? AND player_id=?""",
                    (attempt_xp, attempt_credits, event_id, attempt["attacker_player_id"])
                )
            execute_write(
                """INSERT INTO daily_feed
                   (feed_scope,player_id,flavor_text,event_category,combat_session_id)
                   VALUES('PERSONAL',?,?,'WORLD_BOSS',?)""",
                (attempt["attacker_player_id"], end_message, attempt["id"])
            )
        _log(event_id, defeated_by, "ENDED",
             "The world-boss event has ended. Final standings and prize selection are now locked.")


def _log(event_id, player_id, category, message, details=None):
    execute_write(
        """INSERT INTO world_boss_event_log(event_id,player_id,category,message,details_json)
           VALUES(?,?,?,?,?)""", (event_id, player_id, category, message,
                                   json.dumps(details) if details else None)
    )
