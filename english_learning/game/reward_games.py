"""Learning reward games — the ONE economic authority for what a reward game can pay.

Phase 14A.10B. A qualifying study result no longer hands over gold directly; it earns the player one
REWARD GAME, and this module owns both halves of what the server decides on their behalf:

    which mini-game they are given   -- presentation only, four equally likely
    which prize the game pays        -- economic, four equally likely

Both are decided HERE and nowhere else. The four mini-games are four different ways to reveal the
same prize table: a wheel, three chests, a shot and a die. If a prize table ever appeared beside a
mini-game, the game would become a second economy, so there is exactly one table and the mini-game
type never reaches it.

Deliberately neutral, exactly like the rest of game/: this module knows gold and troop kinds, and
knows nothing whatever about study, content, or what a player did to earn a game.

ALPHA RULES (deliberate, and stated so they are not mistaken for placeholders):
  * every game wins -- there is no empty chest, no miss, no blank wheel segment, no bad roll;
  * both draws are uniform (25% each). Skill, streaks, rarity and weighting are later decisions;
  * the prize table is fixed. The client never names, sizes or influences a prize.
"""
import random as _random

from . import config

# The four ways a prize is revealed. Presentation only -- the prize table below is shared.
GAMES = ("lucky_wheel", "treasure_chests", "target_shot", "dice_roll")

# THE prize table. `kind` is what the caller must move: "gold" -> the gold pool, "troops" -> the
# player's Home Base troop pool (game.army / the economy record), never a map garrison.
#
# The troop sizes are chosen against the UNIT_COST this module already owns, so their rough gold
# value is legible: 670 infantry ~ 4020, 420 archers ~ 5040, 400 cavalry = 6000. Those equivalences
# are INFORMATIONAL -- a troop prize is never converted to gold, and gold is never converted to
# troops.
PRIZES = (
    {"id": "gold_3000", "kind": "gold", "amount": 3000,
     "label": "3,000 Gold", "icon": "\U0001FA99"},
    {"id": "infantry_670", "kind": "troops", "unit": "inf", "count": 670,
     "label": "670 Infantry", "icon": "\U0001F6E1️"},
    {"id": "archer_420", "kind": "troops", "unit": "archer", "count": 420,
     "label": "420 Archers", "icon": "\U0001F3F9"},
    {"id": "cavalry_400", "kind": "troops", "unit": "cav", "count": 400,
     "label": "400 Cavalry", "icon": "\U0001F40E"},
)
PRIZE_BY_ID = {p["id"]: p for p in PRIZES}


def is_game(game_id):
    return game_id in GAMES


def assign_game(rng=None):
    """Which mini-game this entitlement is played as. Uniform over GAMES."""
    return (rng or _random).choice(GAMES)


def draw_prize(rng=None):
    """Which prize this entitlement pays. Uniform over PRIZES. Returns a COPY."""
    return dict((rng or _random).choice(PRIZES))


def prize(prize_id):
    """A resolved prize by id, or None. Used to re-read an already-resolved entitlement so a repeat
    request reveals the SAME prize instead of drawing again."""
    p = PRIZE_BY_ID.get(prize_id)
    return dict(p) if p else None


def gold_value(prize_id):
    """Informational only: what a prize is worth at the unchanged UNIT_COST. Never used to pay."""
    p = PRIZE_BY_ID.get(prize_id)
    if not p:
        return 0
    if p["kind"] == "gold":
        return int(p["amount"])
    return int(p["count"]) * int(config.UNIT_COST[p["unit"]])


def public_table():
    """What the client may render on a wheel/chest/target/die. Presentation data, not authority."""
    return [{"id": p["id"], "kind": p["kind"], "label": p["label"], "icon": p["icon"],
             "amount": p.get("amount"), "unit": p.get("unit"), "count": p.get("count")}
            for p in PRIZES]
