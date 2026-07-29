"""Conquest orchestration — separates battle CALCULATION (game.battle) from STATE MUTATION.

Pure-ish: callers pass current state (attacker army, defender garrison, techs) and an RNG for the
defender shuffle; this returns a BattleResult plus the intended state changes. The HTTP layer
performs persistence. Adjacency is intentionally NOT enforced here in Phase 2A (structured so a
future `are_adjacent(source,target)` gate can be added without touching battle math).
"""
from . import battle, config


def shuffle_defender(defender, rng):
    """Defender order = the ONLY battle randomness (matches JS `shuffled(defTroops)`).
    rng is a random.Random; tests may pass a pre-ordered list via rng=None to keep order."""
    d = battle._alive(defender)
    if rng is not None:
        rng.shuffle(d)
    return d


def resolve_attack(attacker_army, defender_garrison, attacker_tech, defender_tech, rng):
    """Run one attack. Returns a dict:
       { result: BattleResult, attackerWon, attackerSurvivors, defenderSurvivors }
       attacker_tech/defender_tech: {atk,def} levels. Attacker uses its (home) tech; defender its region tech."""
    ordered = shuffle_defender(defender_garrison, rng)
    res = battle.resolve_battle(
        battle._alive(attacker_army), ordered,
        config.tech_atk(attacker_tech), config.tech_def(attacker_tech),
        config.tech_atk(defender_tech), config.tech_def(defender_tech),
    )
    return {
        "result": res,
        "attackerWon": res["attackerWon"],
        "attackerSurvivors": res["attackerSurvivors"],
        "defenderSurvivors": res["defenderSurvivors"],
        "defenderOrder": ordered,   # the shuffled order used → frontend replays the SAME battle for animation
    }
