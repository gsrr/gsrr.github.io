# Taipei curriculum → territory progression (Phase 4A STEP 1–2: inventory & proposal)

Inventory of the **existing** Taipei content and map at commit `b1df826`, plus a proposed progression
route. **No authoritative edit has been made** — §10 and §32 require the mapping to be reviewed first.

---

## 1. Taipei territories & adjacency (Phase 1C world-data, unchanged)

| Territory | Display | Adjacent to |
|---|---|---|
| `taipei:wenshan` | Wenshan 文山區 | daan, nangang, xinyi, zhongzheng |
| `taipei:daan` | Daan 大安區 | songshan, wenshan, xinyi, zhongshan, zhongzheng |
| `taipei:xinyi` | Xinyi 信義區 | daan, nangang, songshan, wenshan |
| `taipei:nangang` | Nangang 南港區 | neihu, songshan, wenshan, xinyi |
| `taipei:songshan` | Songshan 松山區 | daan, nangang, neihu, xinyi, zhongshan |
| `taipei:zhongzheng` | Zhongzheng 中正區 | daan, datong, wanhua, wenshan, zhongshan |
| `taipei:zhongshan` | Zhongshan 中山區 | daan, datong, neihu, shilin, songshan, zhongzheng |
| `taipei:neihu` | Neihu 內湖區 | nangang, shilin, songshan, zhongshan |
| `taipei:datong` | Datong 大同區 | shilin, wanhua, zhongshan, zhongzheng |
| `taipei:wanhua` | Wanhua 萬華區 | datong, zhongzheng |
| `taipei:shilin` | Shilin 士林區 | beitou, datong, neihu, zhongshan |
| `taipei:beitou` | Beitou 北投區 | shilin |

The graph is fully land-connected; `beitou` is a leaf behind `shilin`. **No adjacency change is
proposed** (§8).

Only existing requirement: `taipei:daan` → `english.prea1.taipei.zoo` (the Phase 3A slice).

## 2. Taipei learning content

Four Taipei lessons exist on disk, exposed through `LEVEL_ARCS["Pre-A1"]` — and their titles state
the intended order:

| # | Arc title | contentPath | Content keys | Registered today? |
|---|---|---|---|---|
| 1 | Taipei 1 · At the Zoo | `Pre-A1/taipei/zoo` | quiz3, quiz4, vocab, wh, cloze (+ dialogue) | **yes** — 6 activities |
| 2 | Taipei 2 · On the MRT | `Pre-A1/taipei/mrt` | same | **no** |
| 3 | Taipei 3 · The Night Market | `Pre-A1/taipei/market` | same | **no** |
| 4 | Taipei 4 · At the Park | `Pre-A1/taipei/park` | same | **no** |

Registered activities today (10 total; only Zoo is Taipei):

```
english.prea1.taipei.zoo.quiz3      yes_no             grants english.prea1.taipei.zoo   [PASS_GOLD]
english.prea1.taipei.zoo.quiz4      yes_no             grants —
english.prea1.taipei.zoo.wh         multiple_choice    grants —
english.prea1.taipei.zoo.cloze      multiple_choice    grants —
english.prea1.taipei.zoo.matching   matching_first_try grants —
english.prea1.taipei.zoo.read_along read_along_stt     grants —
english.a1.core.001.*               (A1/001, not Taipei) x4
```

Qualifications in existence: exactly one — `english.prea1.taipei.zoo`.
Lesson completion policies: one — `english.prea1.taipei.zoo` (Rule A, 6 activities).

**Difficulty signal (§9):** the arc numbering `Taipei 1…4` is the existing designer ordering. No
difficulty score needs inventing.

## 3. Proposed route

Start: **`taipei:wenshan`** — unchanged from the Phase 3 slice, no qualification required to hold it,
neutral-claim bootstrap untouched (§6, §31).

```
                 wenshan  (START, no gate)
                /   |   \        \
             daan  xinyi  zhongzheng   nangang (free)
              |      |        |
              +--- songshan --+          (park)
              |               |
              +-- zhongshan --+          (zoo + market)
```

Three independent branches open immediately from the start, giving real player choice (§7, §15).

## 4. Proposed mapping (§32)

| Territory | Reachable from | Qualification | Source activity | Scope | Title shown | Why here |
|---|---|---|---|---|---|---|
| `taipei:wenshan` | — (start) | *none* | — | — | — | start must be ungated |
| `taipei:daan` | wenshan | `english.prea1.taipei.zoo` **(existing, unchanged)** | `…zoo.quiz3` | activity | Taipei · At the Zoo — Yes/No | Taipei 1, the proven slice; preserved verbatim |
| `taipei:xinyi` | wenshan | `english.prea1.taipei.mrt.quiz3.pass` | `…mrt.quiz3` | activity | Taipei · On the MRT — Yes/No | Taipei 2; second branch off the start |
| `taipei:zhongzheng` | wenshan | `english.prea1.taipei.market.quiz3.pass` | `…market.quiz3` | activity | Taipei · The Night Market — Yes/No | Taipei 3; third branch off the start |
| `taipei:songshan` | daan / xinyi / nangang | `english.prea1.taipei.park.quiz3.pass` | `…park.quiz3` | activity | Taipei · At the Park — Yes/No | Taipei 4 (last/hardest arc), and not adjacent to the start — genuinely one step deeper |
| `taipei:zhongshan` | daan / zhongzheng | `english.prea1.taipei.zoo` **+** `english.prea1.taipei.market.quiz3.pass` | two activities | activity ×2 | both titles listed | the single multi-requirement gate (§16), placed where two branches converge |
| `taipei:nangang` | wenshan | *none* | — | — | — | deliberately free: gives an unblocked expansion so the player is never stuck behind study |

**Unassigned (5):** `neihu`, `datong`, `wanhua`, `shilin`, `beitou`. There are only four Taipei
lessons, and I would rather leave these open than invent gates or reuse a lesson twice (§10, §14).

## 5. Registry additions required

Additive only — no existing entry changes:

- 3 lessons: `english.prea1.taipei.mrt` / `.market` / `.park` → their existing contentPaths
- 3 activities: `<lesson>.quiz3`, `graderType: yes_no`, `rewardPolicy: "none"`
- 3 qualifications: `<lesson>.quiz3.pass`, `scope: activity`, with titles

Every new activity uses **`rewardPolicy: "none"`** so the gold-bearing set stays exactly
`{english.prea1.taipei.zoo.quiz3}` and PASS_GOLD is untouched (§18).

> Superseded by Phase 7C.2a: these three gates were deliberately given
> `rewardPolicy: "standard_activity_pass"`, making the gold-bearing set all four quiz3 activities.
> The reasoning above still describes why the *content* phase kept them inert — reward activation was
> a separate, later decision, not a side effect of registering content.

Zoo is **not** given a lesson-scope qualification: the existing activity qualification already
provides the gate, so §19's "prefer minimal changes" applies and no migration is needed (§12).

## 6. §33 STOP determination — no stop

| # | Condition | Verdict |
|---|---|---|
| 1 | Insufficient server-authoritative content | FALSE — 4 lessons, all with content the existing generic graders already handle |
| 2 | Difficulty/order must be invented | FALSE — the `Taipei 1…4` arc order is existing designer data |
| 3 | Existing qualifications can't be reused | FALSE — Zoo's id is reused verbatim |
| 4 | A territory would need an unearnable qualification | FALSE — each maps to a registered `yes_no` activity |
| 5 | Adjacency forces a dead end | FALSE — every gated territory is adjacent to the start or to a gated territory reachable from it |
| 6 | Needs lesson policies that don't exist | FALSE — all gates are activity-scope |
| 7 | Needs battle/adjacency rule changes | FALSE |
| 8 | Materially alters reward economy | FALSE — every new activity is `rewardPolicy: none` |
| 9 | Conflicts with Zoo/Daan | FALSE — that pairing is preserved unchanged |

## 7. Reachability (topology only, to be enforced by a validator)

```
own {wenshan}                        → frontier: daan, nangang, xinyi, zhongzheng
study Zoo   → daan                   → frontier += songshan, zhongshan
study MRT   → xinyi                  → frontier += songshan
study Market→ zhongzheng             → frontier += zhongshan, datong, wanhua
nangang free                          → frontier += neihu, songshan
study Park  → songshan
Zoo + Market→ zhongshan
```

No gate is unreachable, no cycle blocks entry, and the ungated `nangang` guarantees the player always
has at least one available move without studying.
