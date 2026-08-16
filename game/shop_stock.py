"""Shop stock limits shared by player and NPC selling flows.

Daily-rotation listings are controlled separately by their weapon, armor, and
special-slot settings.  This module caps only PLAYER_SOLD listings so an active
player economy cannot make the Shop page grow without bound.  Callers invoke
``enforce_player_sold_listing_cap`` while holding an exclusive transaction.
"""

from datetime import datetime
import logging

import config_defaults as cfg
from database import execute, execute_one, execute_write


logger = logging.getLogger(__name__)


def enforce_player_sold_listing_cap(settings: dict | None = None) -> list[dict]:
    """Remove the oldest player-sold listings above the configured cap.

    Ordinary weapons and armor leave circulation when they expire. Unique
    specials return to ``IN_POOL`` so their single-copy registry remains
    authoritative and they can appear later through an ordinary drop or shop
    rotation. The returned rows are useful for logs and tests.
    """
    settings = settings or {}
    cap = max(0, int(settings.get(
        "SHOP_PLAYER_SOLD_LISTING_CAP", cfg.SHOP_PLAYER_SOLD_LISTING_CAP
    )))
    count = int(execute_one(
        "SELECT COUNT(*) AS cnt FROM shop_listings WHERE listing_source='PLAYER_SOLD'"
    )["cnt"])
    excess = max(0, count - cap)
    if not excess:
        return []

    expired = execute(
        """SELECT * FROM shop_listings
           WHERE listing_source='PLAYER_SOLD'
           ORDER BY datetime(listed_at) ASC, id ASC
           LIMIT ?""",
        (excess,),
    )
    tables = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}
    removed = []
    for listing in expired:
        table = tables.get(listing["item_type"])
        item = (execute_one(f"SELECT name FROM {table} WHERE id=?", (listing["item_id"],))
                if table else None)
        item_name = item["name"] if item else "Unknown Item"
        execute_write("DELETE FROM shop_listings WHERE id=?", (listing["id"],))
        if listing["item_type"] == "SPECIAL":
            execute_write(
                """UPDATE special_item_registry
                   SET status='IN_POOL', current_owner_player_id=NULL,
                       inventory_item_id=NULL, shop_listing_price=NULL,
                       last_released_method='SHOP_CAP_EXPIRED', updated_at=?
                   WHERE special_item_id=?""",
                (datetime.utcnow().isoformat(), listing["item_id"]),
            )
        if listing.get("seller_player_id"):
            execute_write(
                """INSERT INTO item_history
                   (player_id,item_type,item_id,item_name,event_type,credit_amount)
                   VALUES(?,?,?,?, 'SHOP_EXPIRED',0)""",
                (listing["seller_player_id"], listing["item_type"],
                 listing["item_id"], item_name),
            )
        removed.append({**listing, "item_name": item_name})

    logger.info("Shop cap expired %d oldest player-sold listing(s); cap=%d",
                len(removed), cap)
    return removed
