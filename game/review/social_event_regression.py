"""Isolated regression for Tavern rumors, bounty escrow, and traveling merchant."""

import os
import shutil
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import config_defaults as cfg

handle, temp_path = tempfile.mkstemp(suffix=".db")
os.close(handle)
shutil.copy2(cfg.DB_PATH, temp_path)
cfg.DB_PATH = temp_path

try:
    from app import create_app
    from bounties import post_bounty, complete_for_pvp
    from database import execute, execute_one, execute_write, exclusive_transaction
    from merchant import maybe_start_merchant, listings_for_player, buy_listing
    from rumors import grant_tavern_rumor
    from routes.actions import handle_tavern_heal

    app = create_app()
    with app.app_context():
        class_id = execute_one("SELECT id FROM classes WHERE is_active=1 LIMIT 1")["id"]
        weapon = execute_one("SELECT id FROM weapons WHERE is_active=1 LIMIT 1")
        assert weapon, "Regression requires imported weapon content"
        with exclusive_transaction():
            ids = []
            for suffix in ("poster", "target", "hunter"):
                ids.append(execute_write(
                    """INSERT INTO players(username,password_hash,email,character_name,sex,class_id,level,
                       current_hp,current_ap,credits) VALUES(?,?,?,?,?,?,3,30,20,100000)""",
                    (f"reg_{suffix}", "x", f"reg_{suffix}@example.invalid",
                     f"Regression {suffix.title()}", "Other", class_id),
                ))
            prize_inv = execute_write(
                """INSERT INTO inventory_items(player_id,item_type,item_id,current_durability,acquired_method)
                   VALUES(?,'WEAPON',?,100,'REGRESSION')""", (ids[0], weapon["id"]),
            )
        posted = post_bounty(ids[0], ids[1], prize_inv)
        assert posted["id"]
        reward = complete_for_pvp(ids[1], ids[2])
        assert reward and reward["prize"]
        assert execute_one("SELECT player_id FROM inventory_items WHERE id=?", (prize_inv,))["player_id"] == ids[2]

        rumor = grant_tavern_rumor(ids[0])
        assert rumor["kind"] in ("ENEMY", "WEALTH", "NONE")
        tavern = handle_tavern_heal(ids[0], {"cost_ap": 2})
        assert tavern["rumor"]["kind"] in ("ENEMY", "WEALTH", "NONE")

        event = maybe_start_merchant(force=True)
        if event:
            offers = listings_for_player(ids[2])
            assert 1 <= len(offers) <= 5
            bought = buy_listing(ids[2], offers[0]["listing_id"])
            assert bought["item"]

        client = app.test_client()
        cm = client.session_transaction(); sess = cm.__enter__(); sess["player_id"] = ids[2]; cm.__exit__(None,None,None)
        assert client.get("/bounties").status_code == 200
        assert client.get("/traveling-merchant").status_code == 200
        assert client.get("/war-room").status_code == 200
    print("social-event-regression: PASS")
finally:
    try:
        os.remove(temp_path)
    except OSError:
        pass
