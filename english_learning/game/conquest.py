"""Conquest orchestration — separates battle CALCULATION (game.battle) from STATE MUTATION.

Pure-ish: callers pass current state (attacker army, defender garrison, techs) and an RNG for the
defender shuffle; this returns a BattleResult plus the intended state changes. The HTTP layer
performs persistence. Adjacency is intentionally NOT enforced here in Phase 2A (structured so a
future `are_adjacent(source,target)` gate can be added without touching battle math).
"""
import hashlib
import random as _random

from . import army, battle, config
from .army import clampi


class AttackEligibility:
    """Structured result of can_attack(). Truthy iff the attack is allowed.
    `reason` is a stable machine string (see REASONS) or None when allowed — safe to expose to
    the frontend/UI and to assert on in tests. Never carries internal exception detail.
    Phase 10A.3R retired `qualification_required`: Learning and Game are separate systems, so no
    learning achievement is a Conquest prerequisite. `missing_qualifications` is retained as an
    always-empty field purely so existing callers/serialisers keep working."""
    __slots__ = ("allowed", "reason", "missing_qualifications")
    REASONS = (
        "source_not_found", "target_not_found", "same_territory",
        "source_not_owned", "target_already_owned", "target_not_attackable",
        # "not_adjacent" is retained in this reason set but is UNREACHABLE from Phase 14A on:
        # the Alpha rule allows conquest regardless of geography. It is kept rather than deleted so
        # a stricter post-Alpha rule can re-use the same documented reason string.
        "not_adjacent", "invalid_squad", "insufficient_source_garrison",
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
# Phase 3A added a Learning/qualification gate here; Phase 10A.3R RETIRED it. Eligibility is decided
# by GAME state alone. `player_qualifications` and `require_qualifications` remain in the signature as
# accepted-and-ignored parameters so every existing call site (including the AI's explicit bypass)
# still works, and `missing_qualifications()` below survives as a pure REPORTING resolver with no
# caller in the authority path. Game Domain still treats requirement IDs as FULLY OPAQUE strings: it
# never parses, splits or classifies them, and nothing in game/ knows what any of them certify or how
# one is earned — see the content-independence regression test.
def missing_qualifications(world, territory_id, player_qualifications):
    """Required qualification IDs the player does NOT hold, for ONE territory. Never raises.

    REPORTING ONLY since Phase 10A.3R. This answers "what does this territory still ask of me?" for
    Learning-side reporting; it decides nothing. It used to be THE single rule for taking a
    territory (inline in can_attack() from Phase 3A, lifted out in Phase 7D-0 so neutral CLAIM ran the
    identical rule), and neither can_attack() nor the claim route calls it any more. It is kept, and
    kept tested, because the requirement metadata it reads is still authored in world-data.

    ALL semantics (no OR groups): every required ID must be held. Junk entries (non-string/empty) are
    ignored rather than treated as unmeetable gates, and a duplicated requirement is reported once —
    the returned list is what the UI renders, so it must be clean and order-stable. An empty or
    missing requirement list means unrestricted.

    The IDs stay FULLY OPAQUE here: nothing in game/ parses, splits or classifies them, and nothing
    knows what any of them certify or how one is earned (content-independence regression).
    """
    try:
        required = world.attack_requirements(territory_id) or []
    except Exception:
        required = []
    held = player_qualifications or set()
    missing, seen = [], set()
    for q in required:
        if isinstance(q, str) and q and q not in seen:
            seen.add(q)
            if q not in held:
                missing.append(q)
    return missing


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
    # ===== Phase 14A (v0.1 PLAYABLE ALPHA): geography is INFORMATION, not conquest authority =====
    # This is where `world.are_adjacent(source_id, target_id)` used to reject a non-adjacent attack
    # with "not_adjacent". For the Alpha the player is building a WORLD empire, so OWNERSHIP decides
    # what may be attacked and adjacency decides nothing. Every other condition is unchanged and
    # still checked -- identity, canonical ids, self-attack, source ownership, target ownership,
    # squad validity and source garrison, all above and below this comment.
    #
    # Deliberately NOT removed: cross-map protection. Adjacency lists are per-map canonical ids, so
    # are_adjacent() also happened to reject a cross-map pair. That protection now comes from the
    # caller's own `territory_on_active_map()` checks on BOTH ends (server.py), which is where it
    # belongs -- one playable surface, checked explicitly, rather than as a side effect of geography.
    #
    # This is an ALPHA rule, adopted to get the game in front of players. It may become stricter
    # again once real play tells us whether unrestricted global conquest is any fun.
    need = _squad_need(squad)
    if not need:
        return AttackEligibility(False, "invalid_squad")
    avail = _garrison_avail(src.get("troops"))
    for ty, n in need.items():
        if avail.get(ty, 0) < n:
            return AttackEligibility(False, "insufficient_source_garrison")
    # Phase 10A.3R: the learning-qualification gate that used to sit here is GONE. Attack eligibility
    # is decided by GAME state only — identity, ownership, adjacency, garrison and squad. No
    # learning achievement, credential or reward makes a territory reachable or unreachable.
    # `player_qualifications` / `require_qualifications` are kept as accepted-and-ignored parameters
    # so existing call sites (including the AI's explicit bypass) need no change.
    return AttackEligibility(True, None)


# ===== Phase 14A.9: HOME BASE IS A VALID ATTACK SOURCE =====
# A player who holds no World territory could recruit an army and then do nothing with it: attacking
# demands an owned World source, so the very first attack was impossible. For the Playable Alpha the
# player's Home Base is a first-class attack SOURCE.
#
# Home Base is NOT a territory and this rule does not make it one. It has no catalogue id, no map
# identity and no adjacency, so the identity/ownership checks that only mean something for a holding
# are simply not applicable to it -- there is nothing to canonicalise and nothing to own. Everything
# that is about the TARGET is the same rule as can_attack(), checked here in the same order and
# returning the same reason strings, and the squad is checked against the Home Base troop POOL the
# caller passes in ({type: hp}) instead of a garrison list.
#
# Home Base can therefore SEND an army; it can never RECEIVE one. As a target it is not canonical,
# so can_attack()/can_attack_from_home() both answer `target_not_found` for it.
def can_attack_from_home(player_id, target_id, squad, world, territories, home_pool):
    """Eligibility for an attack launched from the player's Home Base. Pure. Same target rules as
    can_attack(); the source is the authoritative Home Base troop pool."""
    if not target_id or not world.is_canonical(target_id):
        return AttackEligibility(False, "target_not_found")
    tgt = territories.get(target_id)
    tgt_owner = tgt.get("owner") if isinstance(tgt, dict) else None
    if tgt_owner == player_id:
        return AttackEligibility(False, "target_already_owned")
    if not tgt_owner:                                   # neutral -> Occupy, exactly as before
        return AttackEligibility(False, "target_not_attackable")
    need = _squad_need(squad)
    if not need:
        return AttackEligibility(False, "invalid_squad")
    for ty, n in need.items():
        if clampi((home_pool or {}).get(ty, 0)) < n:
            return AttackEligibility(False, "insufficient_source_garrison")
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


# ================================ Phase 10B: zero-territory re-entry ================================
# A player who holds nothing on a fully-claimed map cannot act: claiming answers `held`, and attacking
# demands an owned source. Re-entry is the ONE bounded exception, and it is decided here so the rule is
# testable without HTTP. Everything about it is derived from GAME state that is passed in; this
# function reads no player progress of any kind, and it never mutates.
class ReentryState:
    """Structured result of reentry_state(). Truthy iff the player may establish a foothold.

    `reason` is a stable machine string (see REASONS) or None when available. `candidates` is the
    ONLY set of territory ids the server will accept as a foothold target; it is empty unless
    available."""
    __slots__ = ("available", "reason", "candidates")
    REASONS = (
        "owns_territory",      # holds at least one playable territory -> ordinary rules apply
        "neutral_available",   # an unowned playable territory exists -> ordinary claim is the way back
        "no_candidates",       # nothing eligible to land on (e.g. an empty or single-player board)
    )

    def __init__(self, available, reason=None, candidates=None):
        self.available = bool(available)
        self.reason = reason
        self.candidates = list(candidates or [])

    def __bool__(self):
        return self.available

    def __repr__(self):
        return "ReentryState(available=%r, reason=%r, candidates=%r)" % (
            self.available, self.reason, self.candidates)


def _garrison_strength(holding):
    return sum(clampi(u.get("hp", 0)) for u in ((holding or {}).get("troops") or [])
               if isinstance(u, dict))


def reentry_state(player_id, playable_ids, territories, seed="", limit=None,
                  degree_of=None, fair_pool=None):
    """Which footholds, if any, a zero-territory player may take. PURE — never raises, never mutates.

    `playable_ids` is the caller's full set of ids on the active map, so this stays map-agnostic:
    a territory absent from `territories` is UNOWNED, which is exactly why the neutral check cannot
    be done from the store alone.

    Availability requires ALL of: the player owns zero playable territories, no playable territory is
    unowned, and at least one enemy-held playable territory exists. Owning even one, or any neutral
    being claimable, makes re-entry unavailable — re-entry must never be a shortcut past the ordinary
    rules.

    Candidate policy (fairness): rank eligible enemy holdings by defensive burden (garrison first,
    then population), keep the weakest `fair_pool` share as a pool, and take a bounded sample of it.
    The sample is seeded from (seed, player, pool) so it is STABLE for a given board and player --
    an offer can therefore be re-derived and validated on submit without storing session state -- yet
    differs per player and moves as the board moves, so it cannot be scouted or farmed the way a
    strict "weakest N" rule could. CONNECTED holdings are preferred: a zero-adjacency island is a
    foothold you can never attack out of, so it is offered only when nothing connected is available.
    """
    limit = config.REENTRY_CANDIDATES if limit is None else limit
    fair_pool = config.REENTRY_FAIR_POOL if fair_pool is None else fair_pool
    owned, neutral, enemy = [], [], []
    for tid in (playable_ids or []):
        h = territories.get(tid) if isinstance(territories, dict) else None
        owner = h.get("owner") if isinstance(h, dict) else None
        if not owner:
            neutral.append(tid)
        elif owner == player_id:
            owned.append(tid)
        else:
            enemy.append(tid)
    if owned:
        return ReentryState(False, "owns_territory")
    if neutral:
        return ReentryState(False, "neutral_available")
    if not enemy:
        return ReentryState(False, "no_candidates")

    def _degree(tid):
        if degree_of is None:
            return 1                                  # unknown connectivity -> treat as connected
        try:
            return clampi(degree_of(tid))
        except Exception:
            return 0

    connected = [t for t in enemy if _degree(t) > 0]
    source = connected or enemy                       # islands only when nothing connected exists
    ranked = sorted(source, key=lambda t: (_garrison_strength(territories.get(t)),
                                           clampi((territories.get(t) or {}).get("pop", 0)), t))
    want = max(limit * 3, int(len(ranked) * fair_pool))
    pool = ranked[:max(1, min(len(ranked), want))]
    key = "|".join([str(seed), str(player_id)] + sorted(pool))
    rng = _random.Random(hashlib.sha256(key.encode("utf-8")).hexdigest())
    take = min(limit, len(pool))
    return ReentryState(True, None, sorted(rng.sample(pool, take)))


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
