"""Shared rules used when creating player and NPC characters."""

STAT_KEYS = ("str", "end", "agi", "lck", "per")

# Each identity receives one equally sized starting bonus. Keeping this rule in
# one module prevents the player form, server validation, and NPC creator from
# drifting apart.
SEX_OPTIONS = (
    {
        "value": "Male",
        "label": "Male",
        "effect": "+1 STR — stronger in melee and able to carry more gear.",
        "bonuses": {"str": 1, "end": 0, "agi": 0, "lck": 0, "per": 0},
    },
    {
        "value": "Female",
        "label": "Female",
        "effect": "+1 AGI — quicker in combat, with better initiative and ranged skill.",
        "bonuses": {"str": 0, "end": 0, "agi": 1, "lck": 0, "per": 0},
    },
    {
        "value": "Other",
        "label": "Other",
        "effect": "+1 LCK — luckier with critical hits, events, repairs, and opposed actions.",
        "bonuses": {"str": 0, "end": 0, "agi": 0, "lck": 1, "per": 0},
    },
)

_SEX_BONUSES = {option["value"]: option["bonuses"] for option in SEX_OPTIONS}


def sex_bonuses(sex: str) -> dict:
    """Return a safe copy of the five starting bonuses for a valid identity."""
    try:
        bonuses = _SEX_BONUSES[sex]
    except KeyError as exc:
        raise ValueError("Please select a valid identity option.") from exc
    return {stat: int(bonuses.get(stat, 0)) for stat in STAT_KEYS}


def valid_sexes() -> set:
    """Return the identity values accepted by character creation."""
    return set(_SEX_BONUSES)
