"""Player view and purchase endpoint for the traveling merchant."""

from flask import Blueprint, g, redirect, render_template, request, url_for
from merchant import active_event, buy_listing, listings_for_player

bp = Blueprint("merchant", __name__)

@bp.get("/traveling-merchant")
def index():
    return render_template("merchant/index.html", event=active_event(),
                           listings=listings_for_player(g.player["id"]),
                           feedback=request.args.get("feedback"), error=request.args.get("error"))

@bp.post("/traveling-merchant/buy")
def buy():
    try:
        result = buy_listing(g.player["id"], request.form.get("listing_id", type=int))
        return redirect(url_for("merchant.index", feedback=f"Bought {result['item']} for {result['price']} credits."))
    except (ValueError,TypeError) as exc:
        return redirect(url_for("merchant.index", error=str(exc)))
