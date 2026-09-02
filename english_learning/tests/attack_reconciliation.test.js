// Phase 14A.1 ADDENDUM — ATTACK-WIN OWNERSHIP RECONCILIATION (client side).
//
//   node tests/attack_reconciliation.test.js
//
// An Alpha player won a territory and the World map did not turn it into their colour. Two separate
// defects produced that one symptom, and this file pins both fixes plus the rules they must not
// break.
//
// DEFECT 1 — THE OWNERSHIP FILL LOST THE CASCADE.
//   Every owner's colour is painted by colorize() as an important INLINE fill, EXCEPT that the
//   player's own territories used to rely on the `.geo-mine` class. `.geo-mine` and the continent
//   tints `.geo-cont-*` are both single-class `!important` fills and the tints are declared later in
//   the stylesheet, so the tint won: a conquered territory rendered in its continent's neutral tint,
//   pixel-identical to unowned land beside it. Fix: one fill path for every owner.
//
// DEFECT 2 — RECONCILIATION HUNG OFF ONE BUTTON.
//   The battle window is a replay of an already-settled server result, but only its result button
//   called back into the reconciliation. Dismissing the window with the X, with a backdrop click, or
//   part-way through the animation left a client that still believed the defender held the ground.
//   Fix: one settle() path, reached by every exit.
//
// What this file may NOT do is accept a fix that invents ownership on the client, polls, reloads, or
// paints one SVG path directly — so those are pinned as prohibitions.
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
// `.` does not match \r, and this file is CRLF — split explicitly before stripping comments.
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

const colorize = slice("function colorize() {", "function paintStrategic()", "colorize");
const runBattle = slice("function runBattle(", "\n  async function selectArticle", "runBattle");
const launch = slice("function launchAttack(", "\n  function selectLevel", "launchAttack");

// ===================== 1. one ownership fill path =====================
const ownBranch = colorize.slice(colorize.indexOf("if (h && h.owner) {"),
                                 colorize.indexOf("} else {"));
assert(ownBranch.length > 200, "found the owned branch of colorize()");
assert(/r\.p\.style\.setProperty\("fill", col, "important"\)/.test(ownBranch),
  "an owned territory's fill is an important INLINE declaration");
assert(!/else \{ r\.p\.style\.setProperty\("fill", col, "important"\)/.test(ownBranch),
  "...and it is NOT inside an else that skips the player's own territories");
// the fill must be reached whether or not the territory is mine: exactly one setProperty, not one
// per branch, and no `isMine ?` guarding it
const fillSets = (ownBranch.match(/setProperty\("fill"/g) || []).length;
assert(fillSets === 1, "there is exactly ONE fill assignment for an owned territory (found " + fillSets + ")");
assert(!/isMine[\s\S]{0,40}setProperty\("fill"/.test(ownBranch),
  "the fill assignment is not conditional on who the owner is");
ok("1. colorize() paints every owner's colour through one important inline fill — the player is no " +
   "longer a special case that only sets a class");

// ===================== 2. the class cascade cannot silently return =====================
assert(/\.geo-mine\s+\{ fill: #16a34a !important; \}/.test(html),
  "the .geo-mine rule still exists");
assert(/if \(me && low === me\) return "#16a34a"/.test(code),
  "ownerColor() gives the player #16a34a");
// the hazard that caused the bug: a later, equal-specificity !important fill on the same element
const contTints = (html.match(/\.geo-cont-[a-z]+ \{ fill: #[0-9a-f]{6} !important; \}/g) || []);
assert(contTints.length >= 6, "the continent tints are still declared (" + contTints.length + ")");
assert(html.indexOf(".geo-mine") < html.indexOf(".geo-cont-as"),
  "the continent tints are still declared AFTER .geo-mine — which is exactly why a class-only " +
  "ownership fill loses, and why the fill must be inline");
ok("2. the stylesheet's own green matches ownerColor()'s, so the class and the inline paint cannot " +
   "disagree, and the later continent tints stay documented as the cascade hazard");

// ===================== 3. ownership colour comes from canonical state =====================
assert(/const holders = \(territory && territory\.holders\) \|\| \{\};/.test(colorize),
  "colorize() reads ownership from territory.holders");
assert(/const cmap = ownerColorMap\(present, me\);/.test(colorize),
  "...and the colour from the one owner-colour map");
assert((code.match(/if \(j && j\.holders\) territory = j;/g) || []).length === 1,
  "territory state is replaced in exactly one place (loadTerritory)");
ok("3. the map colour is derived from the same canonical holders map the inspector and Empire read " +
   "— no second ownership cache");

// ===================== 4. one settle path in the battle window =====================
assert((runBattle.match(/function settle\(w\) \{/g) || []).length === 1,
  "runBattle declares exactly one settle()");
assert(/let settled = false;[\s\S]{0,220}if \(settled\) return;\s*settled = true;/.test(runBattle),
  "settle() is idempotent — it runs at most once per battle");
const onResultCalls = (runBattle.match(/onResult\(/g) || []).length;
assert(onResultCalls === 1, "onResult is invoked from exactly one place (found " + onResultCalls + ")");
assert(/if \(onResult\) onResult\(w, survivors\);/.test(runBattle.slice(runBattle.indexOf("function settle(w)"))),
  "...and that place is settle()");
ok("4. the battle window settles through ONE function, called at most once");

// ===================== 5. every exit route settles =====================
const settleCalls = (runBattle.match(/settle\(/g) || []).length - 1;   // minus the declaration
assert(settleCalls >= 5, "settle() is called from every exit route (found " + settleCalls + ")");
assert(/bx\.addEventListener\("click", \(\) => settle\(decideWin\(\)\)\)/.test(runBattle),
  "the battle window's X settles");
assert(/ov\.addEventListener\("click", e => \{ if \(e\.target === ov\) settle\(decideWin\(\)\); \}\)/.test(runBattle),
  "a backdrop click settles");
assert(/if \(!ov\.isConnected\) \{ settle\(decideWin\(\)\); return; \}/.test(runBattle),
  "a dismissal part-way through the animation settles instead of going quiet");
assert((runBattle.match(/if \(!ov\.isConnected\) \{ settle\(decideWin\(\)\); return; \}/g) || []).length === 2,
  "...both in the round loop and in the strike-animation callback");
assert(/querySelector\("#btDone"\)\.addEventListener\("click", \(\) => settle\(w\)\)/.test(runBattle),
  "the result button settles with the outcome the replay reached");
ok("5. the X, the backdrop, a mid-animation dismissal and the result button all reconcile — no exit " +
   "leaves the client believing the defender still holds the territory");

// ===================== 6. the reconciliation is the EXISTING authoritative path =====================
assert(/loadEconomy\(function \(\) \{ loadTerritory\(function \(\) \{ renderEmpire\(\); refreshMap\(\); \}\); \}\);/
  .test(launch), "settlement reconciles through loadEconomy -> loadTerritory -> renderEmpire + refreshMap");
assert((launch.match(/loadTerritory\(function \(\) \{ renderEmpire\(\); refreshMap\(\); \}\)/g) || []).length === 2,
  "both the success and the failure branch reconcile the same way");
assert(/function refreshMap\(\) \{ if \(curDrawArgs\)/.test(code),
  "refreshMap is the existing board-repaint entry point, not a new renderer");
ok("6. reconciliation reuses the existing authoritative refresh and the existing ownership " +
   "rendering path — on success and on refusal alike");

// ===================== 7. the client never invents ownership =====================
assert(!/holders\[[^\]]+\]\s*=/.test(launch) && !/\.owner\s*=/.test(launch),
  "launchAttack never writes an owner or a holders entry");
assert(!/\.owner\s*=/.test(runBattle) && !/holders\[/.test(runBattle),
  "runBattle never writes ownership either — it only replays");
assert(/attackerWon/.test(launch) && !/if \(res\.attackerWon\)[\s\S]{0,120}(owner|fill)/.test(launch),
  "attackerWon is used for the event log, never to repaint ownership");
assert(!/style\.(fill|setProperty\("fill")/.test(launch) && !/style\.fill/.test(runBattle),
  "neither the attack path nor the battle window paints an SVG fill directly");
ok("7. the client repaints from server state only — no optimistic owner, no one-off SVG fill");

// ===================== 8. no reload, no polling, no artificial delay =====================
assert(!/location\.reload|location\.href\s*=|window\.location\s*=/.test(launch + runBattle),
  "no page or route reload is used to make ownership appear");
assert(!/setInterval/.test(launch + runBattle), "no polling loop was introduced");
const settleFn = runBattle.slice(runBattle.indexOf("function settle(w)"),
                                 runBattle.indexOf("const bx = ov.querySelector"));
assert(!/setTimeout/.test(settleFn), "settle() introduces no artificial delay");
assert(!/setTimeout/.test(launch), "the attack path introduces no artificial delay either");
ok("8. no reload, no route reload, no new polling and no artificial delay");

// ===================== 9. teardown order is honest =====================
assert(settleFn.indexOf("closeModal()") < settleFn.indexOf("onResult"),
  "settle() closes the battle window before reconciling, so no stale result modal can survive it");
assert(/const survivors = att\.filter\(u => u\.hp > 0\)/.test(settleFn),
  "settle() still reports the survivors the replay ended with");
// the 14A.1 planner teardown must be untouched: it is what clears the source/target markers
assert(/function closeTray\(\) \{\s*trayMode = null; traySrc = null; trayAmt = \{\};\s*closeModal\(\);\s*markMap\(\);/
  .test(code), "closeTray() is still the one planner teardown that clears the planning markers");
assert(/closeTray\(\);\s*launchAttack\(/.test(code),
  "...and an attack still closes the planner before it is launched");
ok("9. the battle window is gone before reconciliation runs, and the 14A.1 planner teardown that " +
   "clears the source/target markers is unchanged");

// ===================== 10. Phase 14A authority is untouched =====================
assert(/return h && h\.owner && \(h\.owner \+ ""\)\.toLowerCase\(\) === me && sumHp\(h\.troops\) > 0;/
  .test(code), "a valid attack source is still any owned, garrisoned territory — ownership, not distance");
assert(!/are_adjacent|adjacentTerritoryIds[\s\S]{0,60}validAttackSources/.test(
  slice("function validAttackSources(", "function launchAttack(", "validAttackSources")),
  "source eligibility reads no adjacency");
assert(/sourceTerritoryId: source, targetTerritoryId: targetKey, squad: squad/.test(launch),
  "the attack payload is unchanged");
ok("10. the Alpha rule and the attack payload are unchanged — this addendum is a rendering and " +
   "reconciliation fix only");

console.log("\nAll " + passed + " attack-reconciliation checks passed.");
