"""Timed player auctions for unequipped special items."""

from datetime import datetime, timedelta

from flask import Blueprint, g, redirect, render_template, request, session, url_for

import config_defaults as cfg
from database import execute, execute_one, execute_write, exclusive_transaction, get_all_settings
from queue_handler import enqueue_and_process, register_handler

bp = Blueprint("auction", __name__)


@bp.post("/auction/enter")
def enter():
    """Charge admission AP and grant access for the current login session."""
    try:
        enqueue_and_process(session["player_id"], "auction_enter", {})
        session["auction_access_granted"] = True
        return redirect(url_for("auction.index"))
    except RuntimeError as exc:
        return redirect(url_for("dashboard.index", error=str(exc)))


@register_handler("auction_enter")
def handle_enter(player_id: int, payload: dict) -> dict:
    settings = get_all_settings()
    cost = settings.get("AP_COST_AUCTION", cfg.AP_COST_AUCTION)
    player = execute_one("SELECT current_ap,in_combat FROM players WHERE id=?", (player_id,))
    if not player:
        raise ValueError("Player not found.")
    if player["in_combat"]:
        raise ValueError("The auction house is unavailable during combat.")
    if player["current_ap"] < cost:
        raise ValueError(f"Not enough AP. Need {cost}.")
    with exclusive_transaction():
        execute_write("UPDATE players SET current_ap=current_ap-? WHERE id=?", (cost, player_id))
    return {"success": True, "ap_spent": cost}


@bp.get("/auction")
def index():
    if not session.get("auction_access_granted"):
        return redirect(url_for("dashboard.index", error="Enter the auction house from the dashboard first."))
    settle_expired_auctions()
    player_id = g.player["id"]
    listings = _active_listings()
    sellable = execute(
        """SELECT ii.id AS inv_id,ii.current_durability,si.name,si.description,si.credit_cost
           FROM inventory_items ii JOIN special_items si ON si.id=ii.item_id
           WHERE ii.player_id=? AND ii.item_type='SPECIAL' AND si.is_active=1
             AND ii.id <> COALESCE((SELECT equipped_special_id FROM players WHERE id=?),-1)
             AND NOT EXISTS(SELECT 1 FROM auction_listings a
                            WHERE a.inventory_item_id=ii.id AND a.status='ACTIVE')
           ORDER BY si.name""", (player_id, player_id)
    )
    active_seller_count = execute_one(
        "SELECT COUNT(*) AS n FROM auction_listings WHERE seller_player_id=? AND status='ACTIVE'",
        (player_id,)
    )["n"]
    return render_template("auction/index.html", listings=listings, sellable=sellable,
                           active_seller_count=active_seller_count,
                           feedback=request.args.get("feedback"), error=request.args.get("error"))


@bp.post("/auction/list")
def create_listing():
    try:
        enqueue_and_process(session["player_id"], "auction_list", {
            "inv_id": request.form.get("inv_id", type=int),
            "minimum_bid": request.form.get("minimum_bid", type=int),
            "duration_hours": request.form.get("duration_hours", type=int),
        })
        return redirect(url_for("auction.index", feedback="Special item placed on auction hold."))
    except RuntimeError as exc:
        return redirect(url_for("auction.index", error=str(exc)))


@register_handler("auction_list")
def handle_list(player_id: int, payload: dict) -> dict:
    inv_id = int(payload.get("inv_id") or 0)
    minimum = int(payload.get("minimum_bid") or 0)
    hours = int(payload.get("duration_hours") or 0)
    if hours not in (24, 48):
        raise ValueError("Choose a 24- or 48-hour auction.")
    if minimum < 1:
        raise ValueError("Minimum bid must be at least 1 credit.")
    with exclusive_transaction():
        item = execute_one(
            """SELECT ii.*,si.name FROM inventory_items ii
               JOIN special_items si ON si.id=ii.item_id
               WHERE ii.id=? AND ii.player_id=? AND ii.item_type='SPECIAL' AND si.is_active=1""",
            (inv_id, player_id)
        )
        player = execute_one("SELECT equipped_special_id FROM players WHERE id=?", (player_id,))
        if not item:
            raise ValueError("That special item is not available.")
        if player["equipped_special_id"] == inv_id:
            raise ValueError("Equipped items cannot be auctioned.")
        count = execute_one(
            "SELECT COUNT(*) AS n FROM auction_listings WHERE seller_player_id=? AND status='ACTIVE'",
            (player_id,)
        )["n"]
        if count >= 2:
            raise ValueError("You may have only two active auctions.")
        if execute_one("SELECT 1 FROM auction_listings WHERE inventory_item_id=? AND status='ACTIVE'", (inv_id,)):
            raise ValueError("That item is already on auction hold.")
        ends = (datetime.utcnow() + timedelta(hours=hours)).isoformat()
        listing_id = execute_write(
            """INSERT INTO auction_listings
               (seller_player_id,inventory_item_id,minimum_bid,ends_at)
               VALUES(?,?,?,?)""", (player_id, inv_id, minimum, ends)
        )
        execute_write(
            """UPDATE special_item_registry SET status='IN_AUCTION',updated_at=datetime('now')
               WHERE inventory_item_id=?""", (inv_id,)
        )
    return {"success": True, "listing_id": listing_id, "ends_at": ends}


@bp.post("/auction/bid")
def bid():
    try:
        result = enqueue_and_process(session["player_id"], "auction_bid", {
            "listing_id": request.form.get("listing_id", type=int),
            "amount": request.form.get("amount", type=int),
        })
        return redirect(url_for("auction.index", feedback=f"Public bid of {result['amount']} credits placed."))
    except RuntimeError as exc:
        return redirect(url_for("auction.index", error=str(exc)))


@register_handler("auction_bid")
def handle_bid(player_id: int, payload: dict) -> dict:
    listing_id = int(payload.get("listing_id") or 0)
    amount = int(payload.get("amount") or 0)
    with exclusive_transaction():
        listing = execute_one(
            """SELECT * FROM auction_listings WHERE id=? AND status='ACTIVE'
               AND datetime(ends_at)>datetime('now')""", (listing_id,)
        )
        if not listing:
            raise ValueError("That auction has ended.")
        if listing["seller_player_id"] == player_id:
            raise ValueError("You cannot bid on your own item.")
        required = max(listing["minimum_bid"], (listing["current_bid"] or 0) + 1)
        if amount < required:
            raise ValueError(f"Bid must be at least {required} credits.")
        bidder = execute_one("SELECT credits,character_name FROM players WHERE id=?", (player_id,))
        available = ((bidder["credits"] if bidder else 0) +
                     ((listing["current_bid"] or 0)
                      if listing["current_bidder_id"] == player_id else 0))
        if not bidder or available < amount:
            raise ValueError(f"Not enough available credits. Need {amount}.")
        execute_write("UPDATE players SET credits=credits-? WHERE id=?", (amount, player_id))
        if listing["current_bidder_id"]:
            execute_write("UPDATE players SET credits=credits+? WHERE id=?",
                          (listing["current_bid"], listing["current_bidder_id"]))
        execute_write(
            "UPDATE auction_listings SET current_bid=?,current_bidder_id=? WHERE id=?",
            (amount, player_id, listing_id)
        )
        item = _listing_item(listing["inventory_item_id"])
        execute_write(
            """INSERT INTO daily_feed(feed_scope,flavor_text,event_category)
               VALUES('GLOBAL',?,'AUCTION')""",
            (f"{bidder['character_name']} bid {amount} credits on {item['name']}.",)
        )
    return {"success": True, "amount": amount}


def settle_expired_auctions() -> dict:
    """Settle every elapsed auction exactly once; safe for scheduler and page loads."""
    ids = [row["id"] for row in execute(
        "SELECT id FROM auction_listings WHERE status='ACTIVE' AND datetime(ends_at)<=datetime('now')"
    )]
    settled = 0
    for listing_id in ids:
        with exclusive_transaction():
            listing = execute_one(
                "SELECT * FROM auction_listings WHERE id=? AND status='ACTIVE'", (listing_id,)
            )
            if not listing:
                continue
            item = _listing_item(listing["inventory_item_id"])
            seller = execute_one("SELECT character_name FROM players WHERE id=?", (listing["seller_player_id"],))
            if listing["current_bidder_id"]:
                winner = execute_one("SELECT character_name FROM players WHERE id=?", (listing["current_bidder_id"],))
                execute_write("UPDATE inventory_items SET player_id=?,acquired_method='AUCTION_WIN' WHERE id=?",
                              (listing["current_bidder_id"], listing["inventory_item_id"]))
                execute_write("UPDATE players SET credits=credits+? WHERE id=?",
                              (listing["current_bid"], listing["seller_player_id"]))
                execute_write(
                    """UPDATE special_item_registry SET status='IN_INVENTORY',current_owner_player_id=?,
                       last_acquired_method='AUCTION_WIN',updated_at=datetime('now') WHERE inventory_item_id=?""",
                    (listing["current_bidder_id"], listing["inventory_item_id"])
                )
                message = (f"{winner['character_name']} won {item['name']} from "
                           f"{seller['character_name']} for {listing['current_bid']} credits!")
                execute_write(
                    """INSERT INTO item_history(player_id,item_type,item_id,item_name,event_type,
                       credit_amount,related_player_id) VALUES(?,'SPECIAL',?,?,'AUCTION_WON',?,?)""",
                    (listing["current_bidder_id"], item["item_id"], item["name"],
                     listing["current_bid"], listing["seller_player_id"])
                )
                execute_write(
                    """INSERT INTO item_history(player_id,item_type,item_id,item_name,event_type,
                       credit_amount,related_player_id) VALUES(?,'SPECIAL',?,?,'AUCTION_SOLD',?,?)""",
                    (listing["seller_player_id"], item["item_id"], item["name"],
                     listing["current_bid"], listing["current_bidder_id"])
                )
                execute_write("INSERT INTO daily_feed(feed_scope,flavor_text,event_category) VALUES('GLOBAL',?,'AUCTION')", (message,))
                execute_write("INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category) VALUES('PERSONAL',?,?,'AUCTION')", (listing["seller_player_id"], message))
                execute_write("INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category) VALUES('PERSONAL',?,?,'AUCTION')", (listing["current_bidder_id"], message))
                status = "SOLD"
            else:
                execute_write(
                    "UPDATE special_item_registry SET status='IN_INVENTORY',updated_at=datetime('now') WHERE inventory_item_id=?",
                    (listing["inventory_item_id"],)
                )
                message = f"Your auction for {item['name']} ended without a bid; the item is available again."
                execute_write("INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category) VALUES('PERSONAL',?,?,'AUCTION')", (listing["seller_player_id"], message))
                status = "EXPIRED"
            execute_write("UPDATE auction_listings SET status=?,settled_at=datetime('now') WHERE id=?",
                          (status, listing_id))
            settled += 1
    return {"settled": settled}


def release_player_auctions(player_id: int) -> None:
    """Release/refund auction state before an administrator removes a player."""
    sold = execute("SELECT * FROM auction_listings WHERE seller_player_id=? AND status='ACTIVE'",
                   (player_id,))
    for listing in sold:
        if listing["current_bidder_id"]:
            execute_write("UPDATE players SET credits=credits+? WHERE id=?",
                          (listing["current_bid"], listing["current_bidder_id"]))
        execute_write("UPDATE auction_listings SET status='CANCELLED',settled_at=datetime('now') WHERE id=?",
                      (listing["id"],))
    bids = execute("SELECT * FROM auction_listings WHERE current_bidder_id=? AND status='ACTIVE'",
                   (player_id,))
    for listing in bids:
        execute_write("UPDATE players SET credits=credits+? WHERE id=?",
                      (listing["current_bid"], player_id))
        execute_write("UPDATE auction_listings SET current_bid=NULL,current_bidder_id=NULL WHERE id=?",
                      (listing["id"],))


def _listing_item(inv_id: int) -> dict:
    return execute_one(
        """SELECT ii.item_id,ii.current_durability,si.name,si.description,si.credit_cost
           FROM inventory_items ii JOIN special_items si ON si.id=ii.item_id WHERE ii.id=?""",
        (inv_id,)
    )


def _active_listings() -> list[dict]:
    return execute(
        """SELECT a.*,si.name,si.description,si.credit_cost,ii.current_durability,
                  seller.character_name AS seller_name,bidder.character_name AS bidder_name
           FROM auction_listings a JOIN inventory_items ii ON ii.id=a.inventory_item_id
           JOIN special_items si ON si.id=ii.item_id
           JOIN players seller ON seller.id=a.seller_player_id
           LEFT JOIN players bidder ON bidder.id=a.current_bidder_id
           WHERE a.status='ACTIVE' ORDER BY datetime(a.ends_at),a.id"""
    )
