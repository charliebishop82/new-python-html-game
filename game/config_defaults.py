"""Typed fallback values for gameplay settings that may be overridden in the database."""
# config_defaults.py
# Hardcoded fallback constants. database.get_setting() tries the settings DB
# table first, falls back here if the row is missing, and logs a warning.
# Deployment constants (paths, secret key) live here only — never in the DB.

import os

# ── Deployment constants (never in DB) ───────────────────────────────────────
PENDING_IMPORT_PATH      = "data/pending_import.xlsx"
REJECTED_IMPORT_PATH     = "data/logs/rejected/"
IMPORT_ERROR_LOG         = "data/logs/import_errors.log"
ORPHAN_LOG               = "data/logs/orphan_actions.log"
DB_PATH                  = "data/game.db"
TERMINAL_HISTORY_ENTRIES = 20
SECRET_KEY               = os.environ.get("GAME_SECRET_KEY", "dev-secret-change-in-production")

# ── Game constants (fallbacks if row missing from settings table) ─────────────
BASE_DAILY_AP                          = 20
AP_CARRYOVER_CAP                       = 40
AP_COST_BOSS                           = 3
AP_COST_PVP                            = 3
AP_COST_TAVERN                         = 2
AP_COST_BLACKSMITH                     = 2
AP_COST_SHOP                           = 1
AP_COST_AUCTION                        = 1
AP_COST_ESCAPE                         = 1
AP_COST_COMBAT_EXTENSION               = 1
TRICKLE_AP_AMOUNT                      = 3
TRICKLE_AP_INTERVAL_HOURS              = 6
COMBAT_EXTENSION_TIMEOUT               = 20
MIDNIGHT_BLACKOUT_MINUTES              = 10
STARTING_CREDITS                       = 50
STARTING_STAT_POINTS                   = 10
BASE_HP                                = 10
HP_PER_LEVEL                           = 5
END_HP_REGEN_DIVISOR                   = 2
TAVERN_HEAL_COST                       = 15
TAVERN_HEAL_PERCENT                    = 0.50
TAVERN_CREDITS_PER_HP                  = 2
TAVERN_MIN_COST                        = 5
BRACE_HEAL_PERCENT                     = 0.15
BRACE_AC_BONUS_PERCENT                 = 0.25
BRACE_DODGE_BONUS                      = 5
MIDNIGHT_HEAL_PERCENT                  = 0.50
REPAIR_BASE_PERCENT                    = 0.50
REPAIR_LCK_MULTIPLIER                  = 2
REPAIR_LCK_CAP                         = 0.75
REPAIR_COST_PERCENT                    = 0.25
COMBAT_ROUNDS_DEFAULT                  = 4
COMBAT_ROUNDS_EXTENSION                = 4
COMBAT_ROUNDS_HARD_CAP                 = 50
WORLD_BOSS_ROUNDS_MAX                  = 10
COMBAT_WIN_HP_WEIGHT                   = 0.40
COMBAT_WIN_DMG_WEIGHT                  = 0.60
CREDIT_STEAL_PERCENT                   = 0.10
CREDIT_STEAL_LUCK_MULTIPLIER           = 2
ZERO_CREDIT_XP_BONUS                   = 25
SUCCESSFUL_STEAL_XP                    = 10
COMBAT_DEFEAT_XP                       = 10
MINION_XP_PER_LEVEL                    = 20
BOSS_XP_PER_LEVEL                      = 35
PVP_XP_PER_LEVEL                       = 25
STEAL_ACTION_CREDIT_PERCENT            = 0.20
STEAL_BOSS_CREDIT_MULTIPLIER           = 20
STEAL_SPECIAL_BASE_CHANCE              = 0.03
ESCAPE_CREDIT_DROP_CHANCE              = 0.10
INVENTORY_LIMIT                        = 6
INVENTORY_STR_DIVISOR                  = 3
OVERENCUMBERED_AP_MULTIPLIER           = 2
OVERENCUMBERED_AC_PENALTY              = 3
OVERENCUMBERED_ATTACK_PENALTY          = 3
SWAP_GEAR_ACCURACY_PENALTY             = 0.30
SWAP_GEAR_AC_PENALTY                   = 0.30
SHOP_WEAPONS_COUNT                     = 10
SHOP_ARMOR_COUNT                       = 10
SHOP_DISCOUNT_MAX                      = 0.50
SHOP_DAILY_VENDOR_CREDITS              = 500
BOARD_FEATURE_ENABLED                  = False
RANDOM_EVENT_BASE_CHANCE               = 0.20
RANDOM_EVENT_MAX_CHANCE                = 0.60
RANDOM_EVENT_GOOD_BASE                 = 0.50
RANDOM_EVENT_GOOD_MAX                  = 0.90
RANDOM_EVENT_BAD_MIN                   = 0.10
RANDOM_EVENT_LCK_BONUS                 = 0.05
AP_PASSIVE_HP_REGEN                    = 1
CRIT_BASE_THRESHOLD                    = 20
CRIT_LCK_DIVISOR                       = 5
CRIT_MIN_THRESHOLD                     = 15
RESISTANCE_STACK_MIN_DAMAGE_PERCENT    = 0.25
SELL_PRICE_PERCENT                     = 0.50
COMBAT_PREF_BALANCED_SPLIT             = 0.50
COMBAT_PREF_OPPORTUNIST_SPLIT          = 0.50
WEALTH_TIER_POOR_MAX                   = 0.33
WEALTH_TIER_MIDDLE_MAX                 = 0.66
INACTIVE_DAYS_THRESHOLD                = 7
MINION_ENCOUNTER_CHANCE                = 0.25
MINION_HP_SCALE                        = 0.60
BOSS_HP_SCALE                          = 0.65
ENEMY_DAMAGE_SCALE                     = 0.85
NPC_UPGRADE_MIN_UNEQUIPPED             = 2
NPC_UPGRADE_MIN_IMPROVEMENT            = 0.15
NPC_OBSERVE_MAX_ATTEMPTS               = 1
NPC_RANDOM_WAKE_CHANCE                 = 0.003
PERK_EFFECT_SCALE                      = 0.65
AP_COST_WORLD_BOSS                     = 4
AP_COST_SCENE                          = 2
SCENES_PLAYER_ENABLED                  = False
SCENE_ENEMY_HP_SCALE                   = 0.70
SCENE_ENEMY_DAMAGE_SCALE               = 0.85
SCENE_COMBAT_MAX_ROUNDS                = 20
WORLD_BOSS_HP_MULTIPLIER               = 1.0
WORLD_BOSS_ATTEMPT_XP                  = 10
WORLD_BOSS_ATTEMPT_CREDITS             = 5
WORLD_BOSS_REWARD_HOURS                = 12
CURSE_AP_REDUCTION                     = 0.20
SPECIAL_ITEM_DURABILITY_LOSS_PER_ROUND = 0.02
BOSS_LEVEL_WARNING_THRESHOLD           = 3
LOG_DAILY_ARCHIVE                      = False
LOG_ARCHIVE_PATH                       = "data/logs/daily/"

# Presentation defaults. Interface style and light/dark color mode are kept
# independent so either visual system can be used in either color mode.
DEFAULT_INTERFACE_STYLE                = "CLASSIC"
DEFAULT_COLOR_MODE                     = "DARK"
ALLOW_PLAYER_INTERFACE_OVERRIDE        = True
ALLOW_PLAYER_COLOR_OVERRIDE            = True
CLASSIC_CRT_EFFECTS                    = False

XP_CURVE = {
    2: 100,   3: 250,   4: 500,   5: 900,
    6: 1400,  7: 2000,  8: 2700,  9: 3500,
    10: 4400, 11: 5500, 12: 7000, 13: 9000,
    14: 12000, 15: 16000
}

# ── Type coercion helpers used by database.get_setting() ─────────────────────
SETTING_TYPES = {
    "BASE_DAILY_AP": int, "AP_CARRYOVER_CAP": int, "AP_COST_BOSS": int,
    "AP_COST_PVP": int, "AP_COST_TAVERN": int, "AP_COST_BLACKSMITH": int,
    "AP_COST_SHOP": int, "AP_COST_AUCTION": int, "AP_COST_ESCAPE": int, "AP_COST_COMBAT_EXTENSION": int,
    "TRICKLE_AP_AMOUNT": int,
    "TRICKLE_AP_INTERVAL_HOURS": int, "COMBAT_EXTENSION_TIMEOUT": int,
    "MIDNIGHT_BLACKOUT_MINUTES": int, "STARTING_CREDITS": int,
    "STARTING_STAT_POINTS": int, "BASE_HP": int, "HP_PER_LEVEL": int,
    "END_HP_REGEN_DIVISOR": int, "TAVERN_HEAL_COST": int,
    "TAVERN_CREDITS_PER_HP": int, "TAVERN_MIN_COST": int,
    "BRACE_DODGE_BONUS": int, "REPAIR_LCK_MULTIPLIER": int,
    "COMBAT_ROUNDS_DEFAULT": int, "COMBAT_ROUNDS_EXTENSION": int,
    "COMBAT_ROUNDS_HARD_CAP": int, "WORLD_BOSS_ROUNDS_MAX": int,
    "CREDIT_STEAL_LUCK_MULTIPLIER": int, "ZERO_CREDIT_XP_BONUS": int,
    "SUCCESSFUL_STEAL_XP": int, "COMBAT_DEFEAT_XP": int,
    "MINION_XP_PER_LEVEL": int, "BOSS_XP_PER_LEVEL": int,
    "PVP_XP_PER_LEVEL": int,
    "STEAL_BOSS_CREDIT_MULTIPLIER": int, "INVENTORY_LIMIT": int,
    "INVENTORY_STR_DIVISOR": int,
    "OVERENCUMBERED_AP_MULTIPLIER": int, "OVERENCUMBERED_AC_PENALTY": int,
    "OVERENCUMBERED_ATTACK_PENALTY": int, "SHOP_WEAPONS_COUNT": int,
    "SHOP_ARMOR_COUNT": int, "SHOP_DAILY_VENDOR_CREDITS": int,
    "AP_PASSIVE_HP_REGEN": int,
    "CRIT_BASE_THRESHOLD": int, "CRIT_LCK_DIVISOR": int,
    "CRIT_MIN_THRESHOLD": int,
    "INACTIVE_DAYS_THRESHOLD": int, "BOSS_LEVEL_WARNING_THRESHOLD": int,
    "TERMINAL_HISTORY_ENTRIES": int,
    "TAVERN_HEAL_PERCENT": float, "BRACE_HEAL_PERCENT": float,
    "BRACE_AC_BONUS_PERCENT": float, "MIDNIGHT_HEAL_PERCENT": float,
    "REPAIR_BASE_PERCENT": float, "REPAIR_LCK_CAP": float,
    "REPAIR_COST_PERCENT": float, "COMBAT_WIN_HP_WEIGHT": float,
    "COMBAT_WIN_DMG_WEIGHT": float, "CREDIT_STEAL_PERCENT": float,
    "STEAL_ACTION_CREDIT_PERCENT": float, "STEAL_SPECIAL_BASE_CHANCE": float,
    "ESCAPE_CREDIT_DROP_CHANCE": float, "SWAP_GEAR_ACCURACY_PENALTY": float,
    "SWAP_GEAR_AC_PENALTY": float, "SHOP_DISCOUNT_MAX": float,
    "RANDOM_EVENT_BASE_CHANCE": float, "RANDOM_EVENT_MAX_CHANCE": float,
    "RANDOM_EVENT_GOOD_BASE": float, "RANDOM_EVENT_GOOD_MAX": float,
    "RANDOM_EVENT_BAD_MIN": float, "RANDOM_EVENT_LCK_BONUS": float,
    "RESISTANCE_STACK_MIN_DAMAGE_PERCENT": float, "SELL_PRICE_PERCENT": float,
    "COMBAT_PREF_BALANCED_SPLIT": float, "COMBAT_PREF_OPPORTUNIST_SPLIT": float,
    "WEALTH_TIER_POOR_MAX": float, "WEALTH_TIER_MIDDLE_MAX": float,
    "MINION_ENCOUNTER_CHANCE": float, "CURSE_AP_REDUCTION": float,
    "MINION_HP_SCALE": float, "BOSS_HP_SCALE": float,
    "ENEMY_DAMAGE_SCALE": float,
    "NPC_UPGRADE_MIN_UNEQUIPPED": int,
    "NPC_OBSERVE_MAX_ATTEMPTS": int,
    "NPC_RANDOM_WAKE_CHANCE": float,
    "PERK_EFFECT_SCALE": float,
    "AP_COST_WORLD_BOSS": int, "WORLD_BOSS_HP_MULTIPLIER": float,
    "AP_COST_SCENE": int, "SCENES_PLAYER_ENABLED": bool,
    "SCENE_ENEMY_HP_SCALE": float, "SCENE_ENEMY_DAMAGE_SCALE": float,
    "SCENE_COMBAT_MAX_ROUNDS": int,
    "WORLD_BOSS_ATTEMPT_XP": int, "WORLD_BOSS_ATTEMPT_CREDITS": int,
    "WORLD_BOSS_REWARD_HOURS": int,
    "NPC_UPGRADE_MIN_IMPROVEMENT": float,
    "SPECIAL_ITEM_DURABILITY_LOSS_PER_ROUND": float,
    "LOG_DAILY_ARCHIVE": bool,
    "DEFAULT_INTERFACE_STYLE": str, "DEFAULT_COLOR_MODE": str,
    "ALLOW_PLAYER_INTERFACE_OVERRIDE": bool, "ALLOW_PLAYER_COLOR_OVERRIDE": bool,
    "CLASSIC_CRT_EFFECTS": bool,
    "BOARD_FEATURE_ENABLED": bool,
}


################################################################################
