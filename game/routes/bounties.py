"""Player-facing anonymous bounty board."""

from flask import Blueprint, g, redirect, render_template, request, url_for

from bounties import active_bounties, cancel_bounty, post_bounty
from crews import are_pvp_protected
from database import execute, execute_one, equipped_special_ids

bp = Blueprint("bounties", __name__)


@bp.get("/bounties")
def index():
    pid = g.player["id"]
    targets = [p for p in execute(
        """SELECT id,character_name,level FROM players WHERE id!=? AND is_banned=0
           AND retired_at IS NULL AND character_name IS NOT NULL ORDER BY level DESC,character_name""", (pid,)
    ) if not are_pvp_protected(pid, p["id"])]
    equipped = {g.player.get("equipped_weapon_id"), g.player.get("equipped_armor_id"),
                *equipped_special_ids(g.player, unlocked_only=False)}
    prizes = execute(
        """SELECT ii.id inv_id,ii.item_type,
          CASE ii.item_type WHEN 'WEAPON' THEN w.name WHEN 'ARMOR' THEN a.name ELSE s.name END name
          FROM inventory_items ii
          LEFT JOIN weapons w ON ii.item_type='WEAPON' AND w.id=ii.item_id
          LEFT JOIN armor a ON ii.item_type='ARMOR' AND a.id=ii.item_id
          LEFT JOIN special_items s ON ii.item_type='SPECIAL' AND s.id=ii.item_id
          WHERE ii.player_id=?
          AND NOT EXISTS(SELECT 1 FROM auction_listings a2 WHERE a2.inventory_item_id=ii.id AND a2.status='ACTIVE')
          AND NOT EXISTS(SELECT 1 FROM bounties b WHERE b.inventory_item_id=ii.id AND b.status='ACTIVE')
          ORDER BY name""", (pid,)
    )
    prizes = [i for i in prizes if i["inv_id"] not in equipped]
    mine = execute_one("SELECT * FROM bounties WHERE poster_player_id=? AND status='ACTIVE'", (pid,))
    return render_template("bounties/index.html", bounties=active_bounties(), targets=targets,
                           prizes=prizes, mine=mine, feedback=request.args.get("feedback"),
                           error=request.args.get("error"))


@bp.post("/bounties/post")
def post():
    try:
        result = post_bounty(g.player["id"], request.form.get("target_id", type=int),
                             request.form.get("inv_id", type=int),
                             request.form.get("credit_prize", type=int) or 0)
        return redirect(url_for("bounties.index", feedback=f"Bounty posted on {result['target']}."))
    except (ValueError, TypeError) as exc:
        return redirect(url_for("bounties.index", error=str(exc)))


@bp.post("/bounties/<int:bounty_id>/cancel")
def cancel(bounty_id):
    try:
        cancel_bounty(g.player["id"], bounty_id)
        return redirect(url_for("bounties.index", feedback="Bounty cancelled; prize released."))
    except ValueError as exc:
        return redirect(url_for("bounties.index", error=str(exc)))
