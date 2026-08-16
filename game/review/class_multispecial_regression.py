"""Read-only regression checks for class passives and multi-special aggregation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from database import (execute, get_player, get_player_bonus_profile,
                      unlocked_special_slots, SPECIAL_SLOT_COLUMNS)


app = create_app()
with app.app_context():
    expected = {
        "Action Hero": ("bonus_damage_amount", 1),
        "Gunslinger": ("initiative_bonus", 2),
        "Hunter": ("observe_bonus", 2),
        "Juggernaut": ("ac_bonus", 1),
        "Scoundrel": ("steal_bonus", 0.10),
    }
    for row in execute("SELECT * FROM classes WHERE is_active=1"):
        field, value = expected[row["name"]]
        assert abs(float(row[field]) - value) < 0.0001, (row["name"], field, row[field])

    assert [unlocked_special_slots(level) for level in (1, 7, 8, 15, 16, 99)] == [1, 1, 2, 2, 3, 3]
    assert len(SPECIAL_SLOT_COLUMNS) == 3

    specials = execute("SELECT * FROM special_items WHERE is_active=1 LIMIT 2")
    player = execute("SELECT * FROM players WHERE class_id IS NOT NULL LIMIT 1")[0]
    if len(specials) == 2:
        baseline = get_player_bonus_profile(player["id"], [])
        profile = get_player_bonus_profile(player["id"], specials)
        for field in ("str_bonus", "end_bonus", "initiative_bonus", "ac_bonus"):
            expected_sum = (float(baseline.get(field, 0) or 0) +
                            sum(float(item.get(field, 0) or 0) for item in specials))
            assert abs(float(profile.get(field, 0)) - expected_sum) < 0.0001, field

print("class-multispecial-regression: PASS")
