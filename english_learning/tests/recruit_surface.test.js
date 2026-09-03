// Phase 14A.3 — FORCES ▸ RECRUIT IS THE TERRITORY'S RECRUITMENT.
//
//   node tests/recruit_surface.test.js
//
// The client half of the Alpha capability blocker. openRecruitFor() used to run
//
//     const prod = BUILDINGS.filter(b => b.kind === "prod" && builds[b.id]);
//     openBuildingDetail(key, prod[0].id, reopen);
//
// BUILDINGS is ordered armory, barracks, archery, stable, so a territory holding a Barracks always
// opened the Barracks panel and offered Infantry and Spear only. A player with Barracks + Archery +
// Stable could not recruit Archers or Cavalry from Forces at all — even though the server, which
// gates each unit on that unit's own UNIT_BUILDING, would have accepted both.
//
// The server side of this is proved against a real server in tests/recruit_capability_test.py.
// This file pins the CLIENT: that it offers the union, renders it through one card, spends through
// one call, and invents no authority of its own.
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const code = html.split(/\r?\n/).filter(l => !/^\s*\/\//.test(l)).join("\n");

let passed = 0;
function assert(c, m) { if (!c) { console.error("  FAIL - " + m); process.exit(1); } }
function ok(n) { passed++; console.log("  ok -", n); }

function slice(from, to, label) {
  const a = code.indexOf(from);
  assert(a >= 0, "cannot find " + label + " start: " + from);
  const b = code.indexOf(to, a + from.length);
  assert(b > a, "cannot find " + label + " end: " + to);
  return code.slice(a, b);
}

// ===================== 1. the client's capability model mirrors the server's =====================
const producible = slice("function producibleUnits(builds) {", "\n  function ", "producibleUnits");
assert(/if \(builds\.barracks\) u = u\.concat\(\["inf", "spear"\]\);/.test(producible),
  "barracks enables Infantry and Spear");
assert(/if \(builds\.archery\) u\.push\("archer"\);/.test(producible), "archery enables Archer");
assert(/if \(builds\.stable\) u\.push\("cav"\);/.test(producible), "stable enables Cavalry");
assert(!/armory/.test(producible), "the Armory is a tech building and enables no troop type");
// the BUILDINGS catalogue must agree with it, unit for unit
assert(/\{ id: "barracks",[^}]*units: \["inf", "spear"\] \}/.test(code), "barracks catalogue entry");
assert(/\{ id: "archery",[^}]*units: \["archer"\] \}/.test(code), "archery catalogue entry");
assert(/\{ id: "stable",[^}]*units: \["cav"\] \}/.test(code), "stable catalogue entry");
assert(/\{ id: "armory",[^}]*kind: "tech" \}/.test(code), "armory is kind:tech, with no units");
ok("1. the client's producibleUnits() and BUILDINGS catalogue both mirror the server's " +
   "UNIT_BUILDING — barracks→inf+spear, archery→archer, stable→cav, armory→none");

// ===================== 2. Forces ▸ Recruit offers the UNION =====================
const recruitFor = slice("function openRecruitFor(key, reopen) {", "\n  function ", "openRecruitFor");
assert(/const units = producibleUnits\(builds\);/.test(recruitFor),
  "Recruit is driven by the territory's whole capability");
assert(/units\.map\(u => recruitCardHTML\(u, tech, st\.gold\)\)/.test(recruitFor),
  "...and renders a card for every type in it");
assert(recruitFor.indexOf("prod[0]") < 0, "no single production building is singled out");
assert(recruitFor.indexOf("openBuildingDetail") < 0,
  "Forces no longer opens one building's detail panel");
assert(!/prod\[0\]/.test(code), "nothing anywhere still picks the first production building");
ok("2. Forces ▸ Recruit renders the union of the troop types the territory's buildings enable — " +
   "the Barracks-detail coupling is gone from the whole client");

// ===================== 3. the union is a union: no duplicates, deterministic order =====================
// producibleUnits appends per building and each troop type belongs to exactly one building, so a
// type cannot appear twice. Pin both halves of that argument.
const units = ["inf", "spear", "archer", "cav"];
for (const u of units) {
  const n = (producible.match(new RegExp('"' + u + '"', "g")) || []).length;
  assert(n === 1, u + " is enabled by exactly one building (" + n + ")");
}
assert(producible.indexOf('"inf"') < producible.indexOf('"archer"') &&
       producible.indexOf('"archer"') < producible.indexOf('"cav"'),
  "the order is the catalogue's own: barracks types, then archer, then cavalry");
ok("3. every troop type is enabled by exactly one building, so the union cannot duplicate one, and " +
   "its order is the existing catalogue order");

// ===================== 4. ONE card renderer, ONE recruit call =====================
assert((code.match(/function recruitCardHTML\(u, tech, gold\)/g) || []).length === 1,
  "there is exactly one recruitable-unit card renderer");
assert((code.match(/function bindRecruitCards\(ov, key, reopen\)/g) || []).length === 1,
  "...and exactly one place that binds the recruit action");
assert((code.match(/terrRecruit\(key, btn\.dataset\.unit, RECRUIT_BATCH, reopen\)/g) || []).length === 1,
  "...so there is exactly ONE recruit call site in the client");
const bldDetail = slice("function openBuildingDetail(", "\n  function openConscriptDetail", "openBuildingDetail");
assert(/b\.units\.map\(u => recruitCardHTML\(u, tech, st\.gold\)\)/.test(bldDetail),
  "the Buildings drill-down renders through the same card");
assert(/bindRecruitCards\(ov, key, reopen\);/.test(bldDetail),
  "...and spends through the same binder");
assert(/bindRecruitCards\(ov, key, \(\) => openRecruitFor\(key, reopen\)\);/.test(recruitFor),
  "the Forces panel re-renders itself after a recruit, staying on the territory");
ok("4. both recruit surfaces share one card renderer and one recruit call — they cannot drift into " +
   "two subtly different recruitment systems");

// ===================== 5. no authority moved to the client =====================
assert(/function terrRecruit\(key, unit, qty, cb\) \{ terrPost\("\/api\/territory\/recruit", \{ file: key, unit: unit, qty: qty \}, cb\); \}/
  .test(code), "the endpoint and payload are unchanged");
assert(!/UNIT_BUILDING/.test(recruitFor) && !/has_building|hasBuilding/.test(code),
  "the client never re-implements the server's building check");
assert(!/buildings\[[^\]]+\]\s*=\s*true/.test(code), "the client never grants itself a building");
// gold only DISABLES a card; it never decides the transaction
assert(/\(gold >= cost \? "" : " disabled"\)/.test(code),
  "affordability only disables a card in the UI");
assert(/return False, cost, "not_enough_gold"/.test(
  fs.readFileSync(path.join(__dirname, "..", "game", "recruitment.py"), "utf8")),
  "...while the server still owns the gold decision");
ok("5. no authority moved client-side: same endpoint, same payload, no re-implemented building " +
   "check, and gold still decided by the server");

// ===================== 6. quantity and price are untouched =====================
assert(/const RECRUIT_BATCH = 10;/.test(code), "RECRUIT_BATCH is still 10");
assert(/const cost = RECRUIT_BATCH \* UNIT_COST\[u\];/.test(code),
  "a card still costs one batch at the catalogue price");
assert(!/at-n|aq |quick|MAX/.test(recruitFor),
  "no numeric entry, MAX or percentage row was smuggled in — that backlog stays frozen");
ok("6. quantity and price are untouched: one tap is still ×10 at the server's price, and no " +
   "quantity UX was added");

// ===================== 7. an empty capability still refuses honestly =====================
assert(/if \(!units\.length\) \{/.test(recruitFor),
  "a territory with no production building is handled explicitly");
assert(/There is no barracks, archery range or stable here yet/.test(recruitFor),
  "...and says so, naming all three");
assert(/recruitment is tied to the building, on the/.test(recruitFor),
  "...and says where the authority lives");
ok("7. a territory with no production building is refused with an honest message naming all three " +
   "buildings and the server's authority");

// ===================== 8. capability is read per territory, per open =====================
assert(/const st = manageState\(key\);/.test(recruitFor),
  "the surface reads that territory's own state");
assert(/const builds = st\.h\.buildings \|\| \{\}, tech = st\.h\.tech \|\| \{\};/.test(recruitFor),
  "...its own buildings and its own technology");
assert(!/let\s+lastRecruit|var\s+recruitCache|recruitState\s*=/.test(code),
  "no module-level recruit capability is cached, so nothing can go stale between territories");
assert(/const where = st\.home \? "🏠 Home Base" : \(regionDisplayName\(key\) \|\| key\)/.test(code),
  "the surface names the territory it is for");
ok("8. capability is recomputed from that territory's own state every time the surface opens — no " +
   "cache to leak one territory's troop types into another's");

// ===================== 9. the Empire workspace still owns this surface =====================
assert(/ov\.querySelector\("\.modal-card"\)\.classList\.add\("emp-modal"\);/.test(recruitFor),
  "the Recruit surface uses the Empire workspace width, so four cards fit without sideways scrolling");
assert(/ov\.querySelector\("#bdBack"\)\.addEventListener\("click", \(\) => \{ if \(reopen\) reopen\(\); \}\)/
  .test(recruitFor), "Back returns to whatever opened it — the Empire Forces table");
assert(/\.modal-card\.emp-modal \{ max-width: 1040px; \}/.test(html),
  "...and that workspace width is the one landed in f216549");
ok("9. Recruit reuses the existing Empire workspace primitive rather than inventing a surface");

console.log("\nAll " + passed + " recruit-surface checks passed.");
