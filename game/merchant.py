"""Global six-hour traveling merchant selling five unique special items."""

import random
from datetime import datetime, timedelta

import config_defaults as cfg
from database import (execute, execute_one, execute_write, exclusive_transaction,
                      get_all_settings, get_player, get_player_bonus_profile)


def expire_merchant(now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    events = execute(
        "SELECT * FROM traveling_merchant_events WHERE status='ACTIVE' AND ends_at<=?", (now.isoformat(),)
    )
    for event in events:
        with exclusive_transaction():
            unsold = execute(
                "SELECT special_item_id FROM traveling_merchant_listings WHERE event_id=? AND status='AVAILABLE'",
                (event["id"],),
            )
            for item in unsold:
                execute_write(
                    "UPDATE special_item_registry SET status='IN_POOL',updated_at=datetime('now') WHERE special_item_id=? AND status='TRAVELING_MERCHANT'",
                    (item["special_item_id"],),
                )
            execute_write("UPDATE traveling_merchant_listings SET status='EXPIRED' WHERE event_id=? AND status='AVAILABLE'", (event["id"],))
            execute_write("UPDATE traveling_merchant_events SET status='EXPIRED',closed_at=? WHERE id=?", (now.isoformat(), event["id"]))
            execute_write("INSERT INTO daily_feed(feed_scope,flavor_text,event_category) VALUES('GLOBAL','The traveling merchant has vanished back into the multiverse.','MERCHANT')")
    return len(events)


def active_event() -> dict | None:
    expire_merchant()
    return execute_one("SELECT * FROM traveling_merchant_events WHERE status='ACTIVE' ORDER BY id DESC LIMIT 1")


def maybe_start_merchant(force: bool = False) -> dict | None:
    if active_event():
        return None
    settings = get_all_settings()
    chance = float(settings.get("TRAVELING_MERCHANT_CHANCE", cfg.TRAVELING_MERCHANT_CHANCE))
    if not force and random.random() >= chance:
        return None
    count = max(1, int(settings.get("TRAVELING_MERCHANT_ITEM_COUNT", cfg.TRAVELING_MERCHANT_ITEM_COUNT)))
    pool = execute(
        """SELECT s.* FROM special_items s JOIN special_item_registry r ON r.special_item_id=s.id
           WHERE s.is_active=1 AND r.status='IN_POOL' ORDER BY RANDOM() LIMIT ?""", (count,)
    )
    if not pool:
        return None
    hours = max(1, int(settings.get("TRAVELING_MERCHANT_DURATION_HOURS", cfg.TRAVELING_MERCHANT_DURATION_HOURS)))
    markup = max(0, float(settings.get("TRAVELING_MERCHANT_MARKUP", cfg.TRAVELING_MERCHANT_MARKUP)))
    now = datetime.utcnow()
    with exclusive_transaction():
        event_id = execute_write(
            "INSERT INTO traveling_merchant_events(ends_at) VALUES(?)",
            ((now + timedelta(hours=hours)).isoformat(),),
        )
        for item in pool:
            price = max(1, int(round(item["credit_cost"] * (1 + markup))))
            execute_write(
                "INSERT INTO traveling_merchant_listings(event_id,special_item_id,price) VALUES(?,?,?)",
                (event_id, item["id"], price),
            )
            execute_write(
                "UPDATE special_item_registry SET status='TRAVELING_MERCHANT',updated_at=datetime('now') WHERE special_item_id=?",
                (item["id"],),
            )
        execute_write(
            """INSERT INTO daily_feed(feed_scope,flavor_text,event_category)
               VALUES('GLOBAL',?,'MERCHANT')""",
            (f"A traveling merchant has appeared with {len(pool)} rare special items. The market closes in {hours} hours.",),
        )
    return execute_one("SELECT * FROM traveling_merchant_events WHERE id=?", (event_id,))


def listings_for_player(player_id: int) -> list[dict]:
    event = active_event()
    if not event:
        return []
    player = get_player(player_id)
    profile = get_player_bonus_profile(player_id)
    max_discount = float(get_all_settings().get("SHOP_DISCOUNT_MAX", cfg.SHOP_DISCOUNT_MAX))
    discount = min(max_discount, player["per_stat"] // 2 / 100 + float(profile.get("shop_discount", 0) or 0))
    rows = execute(
        """SELECT l.*,s.* ,l.id listing_id,l.price listed_price FROM traveling_merchant_listings l
           JOIN special_items s ON s.id=l.special_item_id
           WHERE l.event_id=? AND l.status='AVAILABLE' ORDER BY l.price DESC""", (event["id"],)
    )
    for row in rows:
        row["player_price"] = max(1, int(row["listed_price"] * (1 - discount)))
    return rows


def buy_listing(player_id: int, listing_id: int) -> dict:
    event = active_event()
    if not event:
        raise ValueError("The traveling merchant is no longer here.")
    offered = next((r for r in listings_for_player(player_id) if r["listing_id"] == listing_id), None)
    if not offered:
        raise ValueError("That item has already been sold.")
    player = get_player(player_id)
    price = offered["player_price"]
    if player["credits"] < price:
        raise ValueError(f"Not enough credits. Need {price}.")
    with exclusive_transaction():
        current = execute_one("SELECT status FROM traveling_merchant_listings WHERE id=?", (listing_id,))
        if not current or current["status"] != "AVAILABLE":
            raise ValueError("That item has already been sold.")
        inv_id = execute_write(
            """INSERT INTO inventory_items(player_id,item_type,item_id,current_durability,acquired_method)
               VALUES(?,'SPECIAL',?,100,'TRAVELING_MERCHANT')""", (player_id, offered["special_item_id"]),
        )
        execute_write("UPDATE players SET credits=credits-? WHERE id=?", (price, player_id))
        execute_write("UPDATE traveling_merchant_listings SET status='SOLD',buyer_player_id=?,sold_at=? WHERE id=?",
                      (player_id, datetime.utcnow().isoformat(), listing_id))
        execute_write(
            """UPDATE special_item_registry SET status='OWNED',current_owner_player_id=?,inventory_item_id=?,
               shop_listing_price=NULL,last_acquired_method='TRAVELING_MERCHANT',updated_at=datetime('now')
               WHERE special_item_id=?""", (player_id, inv_id, offered["special_item_id"]),
        )
        execute_write("""INSERT INTO item_history(player_id,item_type,item_id,item_name,event_type,credit_amount)
                         VALUES(?,'SPECIAL',?,?,'MERCHANT_PURCHASE',?)""",
                      (player_id, offered["special_item_id"], offered["name"], price))
        buyer = execute_one("SELECT character_name FROM players WHERE id=?", (player_id,))
        execute_write("INSERT INTO daily_feed(feed_scope,flavor_text,event_category) VALUES('GLOBAL',?,'MERCHANT')",
                      (f"{buyer['character_name']} bought {offered['name']} from the traveling merchant.",))
    return {"item": offered["name"], "price": price, "inv_id": inv_id}
