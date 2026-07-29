"""Authoritative battle engine — a FAITHFUL PORT of the frontend `battleResolve` (canonical rule).

Per-unit sequential duel: defender is in a given (shuffled) order and strikes first each
engagement; a slain attacker cannot retaliate; "closing +10%*engage" for a non-archer facing an
archer; round cap 16 then residual-HP tiebreak (attacker needs sa>sd, ties → defender holds).

Deterministic given the inputs (including defender order). The ONLY production randomness is the
defender shuffle, which the caller supplies (seeded RNG in production, fixed order in tests) — so
the same armies + tech + order produce identical winner/casualties/survivors as the JS reference.

Pure: no I/O, no globals mutated. RNG is injected by the caller.
"""
from . import config


def js_round(x):
    """Replicate JavaScript Math.round (round half toward +infinity), unlike Python's banker's rounding."""
    import math
    return math.floor(x + 0.5)


def _base_hit(a_type, d_type, extra_atk, extra_def):
    v = config.UNIT_ATK * (config.atk_bonus(a_type, d_type) + extra_atk) \
        - config.UNIT_DEF * (config.def_bonus(d_type, a_type) + extra_def)
    return max(1, js_round(v))


def _troop_hit(a_type, a_hp, d_type, extra_atk, extra_def):
    return max(1, js_round(_base_hit(a_type, d_type, extra_atk, extra_def) * a_hp / config.DMG_SCALE))


def _alive(units):
    return [{"type": u["type"], "hp": u["hp"], "max": u.get("max", u["hp"])}
            for u in (units or []) if u.get("type") in config.TROOP_KINDS and u.get("hp", 0) > 0]


def resolve_battle(attacker, defender_ordered, a_forge=0.0, a_armor=0.0, d_forge=0.0, d_armor=0.0):
    """attacker, defender_ordered: [{type,hp}] (defender already in intended order).
    a_* = attacker home tech bonuses; d_* = defender region tech bonuses (0.10 per level).
    Returns a BattleResult dict."""
    att = _alive(attacker)
    dfd = _alive(defender_ordered)

    def fa(arr, frm):
        while frm < len(arr) and arr[frm]["hp"] <= 0:
            frm += 1
        return frm

    def decide_win():
        a_alive = fa(att, 0) < len(att)
        d_alive = fa(dfd, 0) < len(dfd)
        if a_alive and not d_alive:
            return True
        if not a_alive:
            return False
        sa = sum(max(0, u["hp"]) for u in att)
        sd = sum(max(0, u["hp"]) for u in dfd)
        return sa > sd

    steps = []
    if not dfd:
        return _result(att, dfd, True, steps, undefended=True)

    rnd = 0
    last_ai = last_di = -1
    engage = 0
    while True:
        ai = fa(att, 0)
        di = fa(dfd, 0)
        # matches JS `round++ > 16`: test the pre-increment value, then increment (→ 17 bodies max)
        if ai >= len(att) or di >= len(dfd) or rnd > config.BATTLE_ROUND_CAP:
            return _result(att, dfd, decide_win(), steps, round_cap=(rnd > config.BATTLE_ROUND_CAP))
        rnd += 1
        if ai == last_ai and di == last_di:
            engage += 1
        else:
            engage = 1
            last_ai, last_di = ai, di
        a = att[ai]
        d = dfd[di]
        close_a = 0.1 * engage if (a["type"] != "archer" and d["type"] == "archer") else 0.0
        close_d = 0.1 * engage if (d["type"] != "archer" and a["type"] == "archer") else 0.0
        dmg_da = _troop_hit(d["type"], d["hp"], a["type"], close_d + d_forge, a_armor)  # defender first
        a["hp"] -= dmg_da
        atk_alive = a["hp"] > 0
        dmg_ad = 0
        if atk_alive:
            # JS computes the attacker's damage from a.hp AFTER it took the defender's hit (post-hit hp).
            dmg_ad = _troop_hit(a["type"], a["hp"], d["type"], close_a + a_forge, d_armor)
            d["hp"] -= dmg_ad
        steps.append({"ai": ai, "di": di, "aType": a["type"], "dType": d["type"],
                      "dmgDA": dmg_da, "dmgAD": dmg_ad, "atkAlive": atk_alive})


def _survivors(units):
    return [{"type": u["type"], "hp": int(js_round(u["hp"]))} for u in units if u["hp"] > 0]


def _result(att, dfd, attacker_won, steps, undefended=False, round_cap=False):
    return {
        "attackerWon": bool(attacker_won),
        "attackerSurvivors": _survivors(att),
        "defenderSurvivors": _survivors(dfd),
        "steps": steps,
        "undefended": undefended,
        "roundCap": round_cap,
    }
