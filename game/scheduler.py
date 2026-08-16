"""Run UTC AP awards, feed archives, imports, recovery, and midnight maintenance."""
# Scheduled maintenance entry points.
# Scheduled AP, NPC, reset, archive, recovery, and content-maintenance jobs.

import random
import logging
import os
from datetime import datetime

from database import (execute, execute_one, execute_write, exclusive_transaction,
                      get_all_settings, get_player_equipped,
                      get_player_bonus_profile, get_player_perk_bonuses,
                      calculate_max_hp, calculate_daily_ap)
from queue_handler import purge_old_done_rows
import config_defaults as cfg

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# AP TRICKLE
# ─────────────────────────────────────────────────────────────────────────────

def ap_trickle():
    """Award TRICKLE_AP_AMOUNT to all non-banned players, capped at AP_CARRYOVER_CAP.
    The server awards it once at startup, then at the configured interval."""
    settings = get_all_settings()
    trickle  = settings.get("TRICKLE_AP_AMOUNT", cfg.TRICKLE_AP_AMOUNT)
    cap      = settings.get("AP_CARRYOVER_CAP",  cfg.AP_CARRYOVER_CAP)

    with exclusive_transaction():
        updated = execute_write(
            "UPDATE players SET current_ap = MIN(current_ap + ?, ?) WHERE is_banned = 0",
            (trickle, cap)
        )
    logger.info("ap_trickle: +%d AP to %d players at %s",
                trickle, updated, datetime.utcnow().isoformat())


# ─────────────────────────────────────────────────────────────────────────────
# MIDNIGHT RESET  (full 12-step implementation)
# ─────────────────────────────────────────────────────────────────────────────

def midnight_reset():
    """Full UTC midnight reset sequence."""
    logger.info("=== MIDNIGHT RESET START %s ===", datetime.utcnow().isoformat())

    _step0_clear_status_effects()
    purge_old_done_rows()                # step 1
    _step2_apply_import()                # step 2
    _step_world_boss_cycle()             # weekly shared event lifecycle
    _step3_archive_and_clear_feeds()     # step 3
    _step4_5_award_daily_ap()            # steps 4+5
    _step_reset_shop_vendor_credits()    # independent daily seller allowances
    _step6_restore_midnight_hp()         # step 6
    _step7_midnight_encounters()         # step 7
    _step8_9_10_shop_rotation()          # steps 8-10
    _step11_pending_feed_entries()       # step 11
    from crews import distribute_pools
    distribute_pools()
    from crews import reevaluate_npc_crews
    reevaluate_npc_crews()
    from contracts import midnight_contract_turnover
    midnight_contract_turnover()

    logger.info("=== MIDNIGHT RESET COMPLETE %s ===", datetime.utcnow().isoformat())


def _step_reset_shop_vendor_credits():
    """Restore every character's personal Shop vendor allowance."""
    from shop_budget import reset_all_vendor_credits
    allowance = reset_all_vendor_credits()
    logger.info("shop vendor credits reset to %d per player", allowance)


def _step_world_boss_cycle():
    """Close the outgoing event every Monday and activate an eligible successor."""
    from world_boss import (get_active_event, close_event, activate_next_event,
                            process_expired_rewards)
    now = datetime.utcnow()
    process_expired_rewards(now)
    active = get_active_event()
    if active and (now.weekday() == 0 or now >= datetime.fromisoformat(active["scheduled_end_at"])):
        close_event(active["id"], "WEEK_ENDED")
        active = None
    # Activation deliberately waits while any prior prize workflow is pending.
    if not active:
        activate_next_event(now)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 0 — Clear all timed status effects
# ─────────────────────────────────────────────────────────────────────────────

def _step0_clear_status_effects():
    """Run the step0 clear status effects portion of scheduled maintenance."""
    with exclusive_transaction():
        deleted = execute_write("DELETE FROM status_effects")
    logger.info("step 0: cleared %d status effects", deleted)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Apply staged Excel import
# ─────────────────────────────────────────────────────────────────────────────

def _step2_apply_import():
    """Run the step2 apply import portion of scheduled maintenance."""
    if not os.path.exists(cfg.PENDING_IMPORT_PATH):
        logger.info("step 2: no pending import")
        return
    logger.info("step 2: applying staged import from %s", cfg.PENDING_IMPORT_PATH)
    from importer import run_import
    result = run_import(cfg.PENDING_IMPORT_PATH)
    if result["success"]:
        logger.info("step 2: import successful — %s", result["summary"])
    else:
        logger.error("step 2: import REJECTED — %s", result["errors"])


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Archive and clear daily feed
# ─────────────────────────────────────────────────────────────────────────────

def _step3_archive_and_clear_feeds():
    """Run the step3 archive and clear feeds portion of scheduled maintenance."""
    # The dashboard is a one-day view, but administrators still need an
    # immutable server-side record for support and investigation.
    archive_feeds()

    with exclusive_transaction():
        deleted = execute_write("DELETE FROM daily_feed")
    logger.info("step 3: cleared %d daily feed entries", deleted)


def archive_feeds():
    """Export today's daily_feed to a timestamped text file."""
    os.makedirs(cfg.LOG_ARCHIVE_PATH, exist_ok=True)
    date_str  = datetime.utcnow().strftime("%Y_%m_%d")
    filepath  = os.path.join(cfg.LOG_ARCHIVE_PATH, f"game_log_{date_str}.txt")
    rows      = execute(
        "SELECT feed_scope, player_id, flavor_text, event_category, occurred_at "
        "FROM daily_feed ORDER BY occurred_at ASC"
    )
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"=== Daily Feed Archive — {date_str} UTC ===\n\n")
            for row in rows:
                scope = f"[{row['feed_scope']}]"
                pid   = f" player={row['player_id']}" if row["player_id"] else ""
                f.write(f"{row['occurred_at']} {scope}{pid} {row['flavor_text']}\n")
        logger.info("step 3: archived %d feed entries to %s", len(rows), filepath)
    except Exception as e:
        logger.exception("step 3: failed to archive feed: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# STEPS 4+5 — AP carryover + award daily AP
# ─────────────────────────────────────────────────────────────────────────────

def _step4_5_award_daily_ap():
    """Carryover is implicit (current_ap already holds remaining AP).
    Cap it at AP_CARRYOVER_CAP, then award new daily AP on top."""
    settings = get_all_settings()
    base_ap   = settings.get("BASE_DAILY_AP",      cfg.BASE_DAILY_AP)
    cap       = settings.get("AP_CARRYOVER_CAP",   cfg.AP_CARRYOVER_CAP)

    players = execute("SELECT * FROM players WHERE is_banned = 0")
    cursed_ids = {
        r["player_id"] for r in execute(
            "SELECT player_id FROM status_effects WHERE effect_type = 'CURSED'"
        )
    }

    with exclusive_transaction():
        execute_write("UPDATE npc_profiles SET actions_today=0")
        for p in players:
            equipped = get_player_equipped(p)
            bonuses = get_player_bonus_profile(p["id"], equipped.get("specials", []))
            effective_end = p["end_stat"] + sum(
                int((equipped.get(slot) or {}).get("end_bonus", 0) or 0)
                for slot in ("weapon", "armor")
            ) + int(bonuses.get("end_bonus", 0) or 0)
            daily_ap = calculate_daily_ap(
                effective_end, int(bonuses.get("bonus_ap", 0) or 0),
                p["id"] in cursed_ids, settings,
            )["effective"]
            # Carryover cap first, then add daily AP, then cap again
            execute_write(
                "UPDATE players SET current_ap = MIN(MIN(current_ap, ?) + ?, ?) WHERE id = ?",
                (cap, daily_ap, cap, p["id"])
            )
    logger.info("steps 4+5: awarded daily AP to %d players (base=%d, cap=%d)",
                len(players), base_ap, cap)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Restore midnight HP
# ─────────────────────────────────────────────────────────────────────────────

def _step6_restore_midnight_hp():
    """Run the step6 restore midnight hp portion of scheduled maintenance."""
    settings  = get_all_settings()
    heal_pct  = settings.get("MIDNIGHT_HEAL_PERCENT", cfg.MIDNIGHT_HEAL_PERCENT)
    players = execute("SELECT * FROM players WHERE is_banned = 0")
    with exclusive_transaction():
        for p in players:
            equipped = get_player_equipped(p)
            bonuses = get_player_bonus_profile(p["id"], equipped.get("specials", []))
            effective_end = p["end_stat"] + sum(
                int((equipped.get(slot) or {}).get("end_bonus", 0) or 0)
                for slot in ("weapon", "armor")
            ) + int(bonuses.get("end_bonus", 0) or 0)
            max_hp = calculate_max_hp(p["level"], effective_end, settings)
            missing = max_hp - p["current_hp"]
            if missing > 0:
                restore = max(1, int(missing * heal_pct))
                execute_write(
                    "UPDATE players SET current_hp = MIN(current_hp + ?, ?) WHERE id = ?",
                    (restore, max_hp, p["id"])
                )
    logger.info("step 6: restored midnight HP for %d players", len(players))


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Midnight random encounters
# ─────────────────────────────────────────────────────────────────────────────

def _step7_midnight_encounters():
    """Run a random event check for every active non-banned player."""
    from routes.actions import check_random_event
    settings = get_all_settings()
    players  = execute(
        """SELECT p.*, 0 as is_overencumbered FROM players p
           WHERE p.is_banned = 0 AND p.in_combat = 0"""
    )
    triggered = 0
    for p in players:
        equipped = get_player_equipped(p)
        effective_end = p["end_stat"] + sum(
            int((equipped.get(slot) or {}).get("end_bonus", 0) or 0)
            for slot in ("weapon", "armor", "special")
        ) + int(get_player_perk_bonuses(p["id"]).get("end_bonus", 0) or 0)
        bonuses = get_player_bonus_profile(p["id"], equipped.get("special"))
        p["max_hp"] = calculate_max_hp(p["level"], effective_end, settings)
        p["max_ap"] = calculate_daily_ap(
            effective_end, int(bonuses.get("bonus_ap", 0) or 0), False, settings
        )["effective"]
        event = check_random_event(p, settings)
        if event:
            triggered += 1
    logger.info("step 7: midnight encounters triggered for %d/%d players", triggered, len(players))


# ─────────────────────────────────────────────────────────────────────────────
# STEPS 8-10 — Shop rotation
# ─────────────────────────────────────────────────────────────────────────────

def _step8_9_10_shop_rotation():
    """Run the step8 9 10 shop rotation portion of scheduled maintenance."""
    settings      = get_all_settings()
    weapons_count = settings.get("SHOP_WEAPONS_COUNT", cfg.SHOP_WEAPONS_COUNT)
    armor_count   = settings.get("SHOP_ARMOR_COUNT",   cfg.SHOP_ARMOR_COUNT)

    with exclusive_transaction():
        # Step 8: Clear daily rotation listings
        execute_write("DELETE FROM shop_listings WHERE listing_source = 'DAILY_ROTATION'")

        # Step 9: Clear unsold special items from shop, return to loot pool
        unsold_specials = execute(
            "SELECT * FROM shop_listings WHERE item_type = 'SPECIAL'"
        )
        for s in unsold_specials:
            execute_write(
                """UPDATE special_item_registry
                   SET status = 'IN_POOL', current_owner_player_id = NULL,
                       inventory_item_id = NULL, shop_listing_price = NULL,
                       last_released_method = 'UNSOLD', updated_at = ?
                   WHERE special_item_id = ?""",
                (datetime.utcnow().isoformat(), s["item_id"])
            )
            execute_write("DELETE FROM shop_listings WHERE id = ?", (s["id"],))
            logger.info("step 9: returned special item id=%d to pool (unsold)", s["item_id"])

        # Populate new daily rotation — random selection weighted by drop_chance
        _populate_shop_rotation("weapons", weapons_count)
        _populate_shop_rotation("armor",   armor_count)

        # Step 10: Populate special item shop slots = floor(player_count / 2)
        player_count  = execute_one("SELECT COUNT(*) as cnt FROM players WHERE is_banned = 0")["cnt"]
        special_cap = int(settings.get("SHOP_SPECIAL_COUNT", cfg.SHOP_SPECIAL_COUNT))
        special_slots = min(special_cap, max(0, player_count // 2))
        if special_slots > 0:
            _populate_special_slots(special_slots)

    logger.info("steps 8-10: shop rotated (%d weapons, %d armor, %d special slots)",
                weapons_count, armor_count, special_slots if player_count else 0)


def _populate_shop_rotation(table: str, count: int):
    """Select 'count' unique items from the content table and list them in the shop."""
    items = execute(
        f"""SELECT * FROM {table} WHERE is_active=1
            AND COALESCE(associated_to,'') NOT LIKE '% (WorldBoss)'
            ORDER BY RANDOM() LIMIT ?""", (count * 3,)
    )
    # Weight by drop_chance
    weighted = []
    for item in items:
        w = max(1, int(item.get("drop_chance", 0.1) * 100))
        weighted.extend([item] * w)
    random.shuffle(weighted)
    seen   = set()
    chosen = []
    for item in weighted:
        if item["id"] not in seen:
            seen.add(item["id"])
            chosen.append(item)
        if len(chosen) >= count:
            break

    item_type = "WEAPON" if table == "weapons" else "ARMOR"
    for item in chosen:
        execute_write(
            """INSERT INTO shop_listings
               (item_type, item_id, listing_source, price)
               VALUES (?, ?, 'DAILY_ROTATION', ?)""",
            (item_type, item["id"], item["credit_cost"])
        )


def _populate_special_slots(slots: int):
    """Add up to 'slots' IN_POOL special items to the shop."""
    available = execute(
        """SELECT si.id, si.credit_cost
           FROM special_items si
           JOIN special_item_registry sir ON sir.special_item_id = si.id
           WHERE sir.status = 'IN_POOL' AND si.is_active = 1
             AND si.association_type <> 'WorldBoss'
           ORDER BY RANDOM()
           LIMIT ?""",
        (slots,)
    )
    for item in available:
        # Price special items significantly higher than their base cost
        price = int(item["credit_cost"] * 2.5)
        execute_write(
            """INSERT INTO shop_listings
               (item_type, item_id, listing_source, price)
               VALUES ('SPECIAL', ?, 'DAILY_ROTATION', ?)""",
            (item["id"], price)
        )
        execute_write(
            """UPDATE special_item_registry
               SET status = 'IN_SHOP', shop_listing_price = ?, updated_at = ?
               WHERE special_item_id = ?""",
            (price, datetime.utcnow().isoformat(), item["id"])
        )


# ─────────────────────────────────────────────────────────────────────────────
# STEP 11 — Process any pending feed entries
# ─────────────────────────────────────────────────────────────────────────────

def _step11_pending_feed_entries():
    """No deferred feed entries in current design — placeholder for future use."""
    logger.info("step 11: no pending feed entries")
