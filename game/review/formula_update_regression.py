"""Focused non-mutating checks for the shared derived-stat update."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from database import calculate_daily_ap, calculate_max_hp, execute_one


app = create_app()
client = app.test_client()
with app.app_context():
    test_player = execute_one(
        """SELECT id FROM players WHERE pending_levelup=0 AND in_combat=0
           AND is_banned=0 ORDER BY id LIMIT 1"""
    )
with client.session_transaction() as session:
    session["player_id"] = test_player["id"]

assert client.get("/character").status_code == 200
assert client.get("/equipment").status_code in (200, 302)

settings = {
    "BASE_DAILY_AP": 30,
    "AP_CARRYOVER_CAP": 40,
    "CURSE_AP_REDUCTION": 0.20,
}
capped = calculate_daily_ap(20, 5, False, settings)
assert capped == {
    "raw": 45, "after_curse": 45, "effective": 40, "cap": 40,
    "is_capped": True, "is_cursed": False,
}
cursed = calculate_daily_ap(20, 0, True, settings)
assert cursed["raw"] == 40 and cursed["effective"] == 32
assert calculate_max_hp(3, 7, {"BASE_HP": 12, "HP_PER_LEVEL": 6}) == 37
print("formula-update-regression: PASS")
