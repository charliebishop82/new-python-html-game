"""Anonymous item/credit escrow bounties completed by decisive PvP defeat."""

from datetime import datetime, timedelta

from database import execute, execute_one, execute_write, exclusive_transaction
from crews import are_pvp_protected


def item_on_bounty_hold(inv_id: int) -> bool:
    return bool(execute_one(
        "SELECT 1 FROM bounties WHERE inventory_item_id=? AND status='ACTIVE'", (inv_id,)
    ))


def active_bounties() -> list[dict]:
    return execute(
        """SELECT b.*,t.character_name target_name,
          CASE b.item_type WHEN 'WEAPON' THEN w.name WHEN 'ARMOR' THEN a.name ELSE s.name END prize_name,
          CASE b.item_type WHEN 'WEAPON' THEN w.credit_cost WHEN 'ARMOR' THEN a.credit_cost
               WHEN 'SPECIAL' THEN s.credit_cost ELSE 0 END prize_value
          FROM bounties b JOIN players t ON t.id=b.target_player_id
          LEFT JOIN weapons w ON b.item_type='WEAPON' AND w.id=b.item_id
          LEFT JOIN armor a ON b.item_type='ARMOR' AND a.id=b.item_id
          LEFT JOIN special_items s ON b.item_type='SPECIAL' AND s.id=b.item_id
          WHERE b.status='ACTIVE'
          ORDER BY (COALESCE(CASE b.item_type WHEN 'WEAPON' THEN w.credit_cost
                    WHEN 'ARMOR' THEN a.credit_cost WHEN 'SPECIAL' THEN s.credit_cost
                    ELSE 0 END,0)+b.credit_prize) DESC,b.created_at"""
    )


def post_bounty(poster_id: int, target_id: int, inv_id: int | None = None,
                credit_prize: int = 0) -> dict:
    credit_prize = max(0, int(credit_prize or 0))
    inv_id = int(inv_id or 0) or None
    if not inv_id and not credit_prize:
        raise ValueError("Offer an item, credits, or both as the bounty prize.")
    if poster_id == target_id:
        raise ValueError("You cannot place a bounty on yourself.")
    if are_pvp_protected(poster_id, target_id):
        raise ValueError("Crew-protected characters cannot be bounty targets.")
    with exclusive_transaction():
        poster = execute_one("SELECT * FROM players WHERE id=?", (poster_id,))
        target = execute_one(
            "SELECT * FROM players WHERE id=? AND is_banned=0 AND retired_at IS NULL", (target_id,)
        )
        item = (execute_one(
            "SELECT * FROM inventory_items WHERE id=? AND player_id=?", (inv_id, poster_id)
        ) if inv_id else None)
        if not poster or not target or (inv_id and not item):
            raise ValueError("The target or item prize is no longer available.")
        if poster["credits"] < credit_prize:
            raise ValueError(f"You need {credit_prize} credits to fund this bounty.")
        if execute_one("SELECT 1 FROM bounties WHERE poster_player_id=? AND status='ACTIVE'", (poster_id,)):
            raise ValueError("You may post only one active bounty.")
        if item:
            equipped = {poster.get("equipped_weapon_id"), poster.get("equipped_armor_id"),
                        poster.get("equipped_special_id"), poster.get("equipped_special_2_id"),
                        poster.get("equipped_special_3_id")}
            if inv_id in equipped:
                raise ValueError("Unequip the prize before placing it in escrow.")
            if execute_one("SELECT 1 FROM auction_listings WHERE inventory_item_id=? AND status='ACTIVE'", (inv_id,)):
                raise ValueError("That item is already on auction hold.")
        bounty_id = execute_write(
            """INSERT INTO bounties
               (poster_player_id,target_player_id,inventory_item_id,item_type,item_id,credit_prize)
               VALUES(?,?,?,?,?,?)""",
            (poster_id, target_id, inv_id, item["item_type"] if item else None,
             item["item_id"] if item else None, credit_prize)
        )
        if item and item["item_type"] == "SPECIAL":
            execute_write(
                "UPDATE special_item_registry SET status='IN_BOUNTY',updated_at=datetime('now') WHERE inventory_item_id=?",
                (inv_id,),
            )
        if credit_prize:
            execute_write("UPDATE players SET credits=credits-? WHERE id=?",
                          (credit_prize, poster_id))
        name = item_name(item["item_type"], item["item_id"]) if item else None
        prize_parts = ([name] if name else []) + ([f"{credit_prize} credits"] if credit_prize else [])
        prize_text = " and ".join(prize_parts)
        execute_write(
            """INSERT INTO daily_feed(feed_scope,flavor_text,event_category)
               VALUES('GLOBAL',?,'BOUNTY')""",
            (f"An anonymous bounty has been placed on {target['character_name']}. Prize: {prize_text}.",),
        )
        execute_write(
            """INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category)
               VALUES('PERSONAL',?,?,'AGAINST_YOU')""",
            (target_id, f"A new anonymous bounty targets you. Prize offered: {prize_text}."),
        )
    return {"id": bounty_id, "target": target["character_name"], "prize": prize_text}


def cancel_bounty(poster_id: int, bounty_id: int) -> None:
    bounty = execute_one(
        "SELECT * FROM bounties WHERE id=? AND poster_player_id=? AND status='ACTIVE'",
        (bounty_id, poster_id),
    )
    if not bounty:
        raise ValueError("Active bounty not found.")
    created = datetime.fromisoformat(bounty["created_at"])
    if datetime.utcnow() < created + timedelta(hours=24):
        raise ValueError("A bounty cannot be cancelled during its first 24 hours.")
    with exclusive_transaction():
        execute_write("UPDATE bounties SET status='CANCELLED',cancelled_at=? WHERE id=?",
                      (datetime.utcnow().isoformat(), bounty_id))
        if bounty.get("credit_prize"):
            execute_write("UPDATE players SET credits=credits+? WHERE id=?",
                          (bounty["credit_prize"], poster_id))
        if bounty["item_type"] == "SPECIAL":
            execute_write(
                "UPDATE special_item_registry SET status='OWNED',updated_at=datetime('now') WHERE inventory_item_id=?",
                (bounty["inventory_item_id"],),
            )


def complete_for_pvp(target_id: int, winner_id: int) -> dict | None:
    """Transfer every escrowed prize on the target after a true 1-HP PvP victory."""
    rows = execute(
        "SELECT * FROM bounties WHERE target_player_id=? AND status='ACTIVE' ORDER BY created_at",
        (target_id,),
    )
    if not rows or winner_id == target_id or are_pvp_protected(winner_id, target_id):
        return None
    winner = execute_one("SELECT character_name FROM players WHERE id=?", (winner_id,))
    target = execute_one("SELECT character_name FROM players WHERE id=?", (target_id,))
    awarded = []
    with exclusive_transaction():
        for bounty in rows:
            item = (execute_one("SELECT * FROM inventory_items WHERE id=?",
                                (bounty["inventory_item_id"],))
                    if bounty.get("inventory_item_id") else None)
            if bounty.get("inventory_item_id") and not item:
                execute_write("UPDATE bounties SET status='CANCELLED',cancelled_at=? WHERE id=?",
                              (datetime.utcnow().isoformat(), bounty["id"]))
                if bounty.get("credit_prize"):
                    execute_write("UPDATE players SET credits=credits+? WHERE id=?",
                                  (bounty["credit_prize"], bounty["poster_player_id"]))
                continue
            name = item_name(item["item_type"], item["item_id"]) if item else None
            if item:
                execute_write(
                    "UPDATE inventory_items SET player_id=?,acquired_method='BOUNTY' WHERE id=?",
                    (winner_id, item["id"]),
                )
            if bounty.get("credit_prize"):
                execute_write("UPDATE players SET credits=credits+? WHERE id=?",
                              (bounty["credit_prize"], winner_id))
            execute_write(
                "UPDATE bounties SET status='COMPLETED',claimed_by_player_id=?,completed_at=? WHERE id=?",
                (winner_id, datetime.utcnow().isoformat(), bounty["id"]),
            )
            if item and item["item_type"] == "SPECIAL":
                execute_write(
                    """UPDATE special_item_registry SET status='OWNED',current_owner_player_id=?,
                       inventory_item_id=?,last_acquired_method='BOUNTY',updated_at=datetime('now')
                       WHERE special_item_id=?""", (winner_id, item["id"], item["item_id"]),
                )
            if item:
                execute_write(
                    """INSERT INTO item_history(player_id,item_type,item_id,item_name,event_type,related_player_id)
                       VALUES(?,?,?,?, 'BOUNTY_WON', ?)""",
                    (winner_id, item["item_type"], item["item_id"], name, target_id),
                )
                awarded.append(name)
            if bounty.get("credit_prize"):
                awarded.append(f"{bounty['credit_prize']} credits")
        if awarded:
            prizes = ", ".join(awarded)
            text = f"{winner['character_name']} collected the bounty on {target['character_name']} and received {prizes}!"
            execute_write("INSERT INTO daily_feed(feed_scope,flavor_text,event_category) VALUES('GLOBAL',?,'BOUNTY')", (text,))
            execute_write("INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category) VALUES('PERSONAL',?,?,'BOUNTY')", (winner_id, text))
            execute_write("INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category) VALUES('PERSONAL',?,?,'AGAINST_YOU')", (target_id, text))
    return ({"bounty_ids": [b["id"] for b in rows], "prize": ", ".join(awarded),
             "prizes": awarded, "target": target["character_name"]} if awarded else None)


def release_player_bounties(player_id: int) -> int:
    """Cancel active bounties posted by or targeting a retired character.

    Credit escrow returns to its sponsor and item holds are released. Call
    inside the retirement transaction before inventory cleanup.
    """
    rows = execute(
        """SELECT * FROM bounties WHERE status='ACTIVE'
           AND (poster_player_id=? OR target_player_id=?)""",
        (player_id, player_id),
    )
    now = datetime.utcnow().isoformat()
    for bounty in rows:
        if bounty.get("credit_prize"):
            execute_write("UPDATE players SET credits=credits+? WHERE id=?",
                          (bounty["credit_prize"], bounty["poster_player_id"]))
        if bounty.get("item_type") == "SPECIAL" and bounty.get("inventory_item_id"):
            execute_write(
                """UPDATE special_item_registry SET status='OWNED',updated_at=datetime('now')
                   WHERE inventory_item_id=?""", (bounty["inventory_item_id"],)
            )
        execute_write("UPDATE bounties SET status='CANCELLED',cancelled_at=? WHERE id=?",
                      (now, bounty["id"]))
    return len(rows)


def item_name(item_type: str, item_id: int) -> str:
    table = {"WEAPON": "weapons", "ARMOR": "armor", "SPECIAL": "special_items"}[item_type]
    row = execute_one(f"SELECT name FROM {table} WHERE id=?", (item_id,))
    return row["name"] if row else "Unknown prize"
