"""Conquest orchestration — separates battle CALCULATION (game.battle) from STATE MUTATION.

Pure-ish: callers pass current state (attacker army, defender garrison, techs) and an RNG for the
defender shuffle; this returns a BattleResult plus the intended state changes. The HTTP layer
performs persistence. Adjacency is intentionally NOT enforced here in Phase 2A (structured so a
future `are_adjacent(source,target)` gate can be added without touching battle math).
"""
from . import army, battle, config
from .army import clampi


class AttackEligibility:
    """Structured result of can_attack(). Truthy iff the attack is allowed.
    `reason` is a stable machine string (see REASONS) or None when allowed — safe to expose to
    the frontend/UI and to assert on in tests. Never carries internal exception detail.
    `missing_qualifications` is populated only for reason == 'qualification_required'."""
    __slots__ = ("allowed", "reason", "missing_qualifications")
    REASONS = (
        "source_not_found", "target_not_found", "same_territory",
        "source_not_owned", "target_already_owned", "target_not_attackable",
        "not_adjacent", "invalid_squad", "insufficient_source_garrison",
        "qualification_required",
    )

    def __init__(self, allowed, reason=None, missing_qualifications=None):
        self.allowed = bool(allowed)
        self.reason = reason
        self.missing_qualifications = list(missing_qualifications or [])

    def __bool__(self):
        return self.allowed

    def __repr__(self):
        return "AttackEligibility(allowed=%r, reason=%r, missing=%r)" % (
            self.allowed, self.reason, self.missing_qualifications)


def _squad_need(squad):
    """Committed squad [{type,hp}] -> {type: total_hp} for valid kinds with hp>0."""
    need = {}
    for u in (squad or []):
        if isinstance(u, dict) and u.get("type") in config.TROOP_KINDS:
            hp = clampi(u.get("hp", 0))
            if hp > 0:
                need[u["type"]] = need.get(u["type"], 0) + hp
    return need


def _garrison_avail(garrison):
    """Garrison list -> {type: total_hp} of live troops."""
    avail = {}
    for u in army.alive_garrison(garrison):
        avail[u["type"]] = avail.get(u["type"], 0) + u["hp"]
    return avail


def _subtract_squad(garrison, squad):
    """Return a NEW garrison list with the committed squad removed (greedy per type).
    Assumes availability was already validated by can_attack; subtracts only what is present."""
    need = _squad_need(squad)
    out = []
    for u in army.alive_garrison(garrison):
        ty, hp = u["type"], u["hp"]
        take = min(hp, need.get(ty, 0))
        need[ty] = need.get(ty, 0) - take
        rem = hp - take
        if rem > 0:
            out.append({"type": ty, "hp": rem})
    return out


# ---- Phase 2B: territorial attack eligibility (World Domain adjacency + Game Domain ownership) ----
# `world` is any object exposing is_canonical(id), map_of(id), are_adjacent(a, b) — pass the
# territory catalog. Adjacency comes ONLY from World Domain (world-data adjacentTerritoryIds); this
# function never touches SVG geometry, map coordinates, or a duplicated adjacency table.
# Phase 3A: the Learning/qualification gate is now active (last check). It is a PLAYER-state gate:
# `player_qualifications` is the set of opaque qualification IDs the player holds; the target's
# required IDs come from World Domain (world.attack_requirements). `require_qualifications=False`
# bypasses ONLY this layer — used for AI (human learning does not apply to the AI) and any future
# non-learning-gated caller. It never bypasses ownership/adjacency/garrison. Game Domain treats the
# IDs as fully opaque (no "english" special-casing) — see the content-independence test.
def can_attack(player_id, source_id, target_id, squad, world, territories,
               player_qualifications=None, require_qualifications=True):
    """Pure eligibility rule. No HTTP, no DOM, no I/O. Returns AttackEligibility."""
    if not source_id or not world.is_canonical(source_id):
        return AttackEligibility(False, "source_not_found")
    if not target_id or not world.is_canonical(target_id):
        return AttackEligibility(False, "target_not_found")
    if source_id == target_id:
        return AttackEligibility(False, "same_territory")
    src = territories.get(source_id)
    if not (isinstance(src, dict) and src.get("owner") == player_id):
        return AttackEligibility(False, "source_not_owned")
    tgt = territories.get(target_id)
    tgt_owner = tgt.get("owner") if isinstance(tgt, dict) else None
    if tgt_owner == player_id:
        return AttackEligibility(False, "target_already_owned")
    if not tgt_owner:                                   # neutral → use the separate claim flow, not attack
        return AttackEligibility(False, "target_not_attackable")
    # World Domain adjacency (also rejects cross-map: adjacency lists are per-map canonical ids)
    if not world.are_adjacent(source_id, target_id):
        return AttackEligibility(False, "not_adjacent")
    need = _squad_need(squad)
    if not need:
        return AttackEligibility(False, "invalid_squad")
    avail = _garrison_avail(src.get("troops"))
    for ty, n in need.items():
        if avail.get(ty, 0) < n:
            return AttackEligibility(False, "insufficient_source_garrison")
    # Phase 3A: learning-qualification gate (player state). ALL required IDs must be held.
    # Missing/empty requirement list == unrestricted. Bypassed only when require_qualifications=False.
    if require_qualifications:
        try:
            required = world.attack_requirements(target_id) or []
        except Exception:
            required = []
        if required:
            held = player_qualifications or set()
            missing = [q for q in required if q not in held]
            if missing:
                return AttackEligibility(False, "qualification_required", missing)
    return AttackEligibility(True, None)


def apply_territorial_attack(source, target, squad, result, attacker, attacker_avatar):
    """Pure state transition for a territorial attack whose battle `result` is already decided.
    Returns (new_source_dict, new_target_dict). The committed squad ALWAYS leaves the source.

    WIN : source keeps (garrison − squad); target ownership -> attacker, garrison = attacker
          survivors, population preserved (buildings/tech reset — a fresh hold, matching the prior
          neutralize+claim outcome). WIN survivors do NOT return to source.
    LOSS: source = (garrison − squad) + attacker survivors (survivors RETURN to source, never the
          global pool, never vanish); target ownership unchanged, garrison = defender survivors."""
    reduced = _subtract_squad(source.get("troops"), squad)
    new_source = dict(source)
    if result["attackerWon"]:
        new_source["troops"] = reduced
        new_target = {
            "owner": attacker,
            "avatar": attacker_avatar,
            "troops": [{"type": s["type"], "hp": clampi(s["hp"])} for s in result["attackerSurvivors"]],
            "pop": clampi(target.get("pop", 0)),
        }
    else:
        for s in result["attackerSurvivors"]:           # survivors return to the source garrison
            reduced = army.merge_into_garrison(reduced, s["type"], s["hp"])
        new_source["troops"] = reduced
        new_target = dict(target)
        new_target["troops"] = [{"type": s["type"], "hp": clampi(s["hp"])} for s in result["defenderSurvivors"]]
    return new_source, new_target


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
