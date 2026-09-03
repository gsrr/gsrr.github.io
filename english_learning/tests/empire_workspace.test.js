// Phase 14A.1 addendum B — MY EMPIRE IS A MANAGEMENT WORKSPACE.
//
//   node tests/empire_workspace.test.js
//
// An Alpha player could not reach Recruit without dragging the Empire panel sideways. Empire renders
// a seven-column table plus a per-row action inside the GENERIC 360px `.modal-card`, so the table was
// 486px wide in a 324px box and the Recruit column sat off the right edge. Measured before the fix,
// at every viewport from 1440x900 down to 390x844:
//
//     forces      .emp-scroll  324 / 486     buildings  324 / 479
//     technology  .emp-scroll  324 / 764     card width 360px everywhere
//     Recruit button at 390x844: x = 424 .. 512, in a 390px viewport
//
// The fix is a width that belongs to Empire alone, plus a table that STACKS instead of scrolling
// once the widest table can no longer fit. This file pins that, and pins the two things that would
// silently undo it: widening the generic modal instead, or hiding the overflow.
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

// ===================== 1. Empire has its own width, and only Empire =====================
assert(/\.modal-card\.emp-modal \{ max-width: 1040px; \}/.test(html),
  "Empire declares a workspace width");
assert(/\.modal-card \{[^}]*max-width: 360px;/.test(html),
  "the GENERIC dialog is still 360px — the fix must not widen every modal");
assert(/\.modal-card\.act-modal \{ max-width: 620px; \}/.test(html),
  "the 14A.1 action modal is still 620px");
const wide = (html.match(/\.modal-card\.[a-z-]+ \{ max-width: \d+px; \}/g) || []);
assert(wide.length === 2, "exactly two modal variants declare their own width: " + JSON.stringify(wide));
ok("1. Empire is the only surface widened — the generic 360px dialog and the 620px action modal are " +
   "untouched");

// ===================== 2. the Empire modal actually claims that class =====================
const empModal = slice("function renderEmpireModal() {", "function empireOverview(", "renderEmpireModal");
assert(/ov\.querySelector\("\.modal-card"\)\.classList\.add\("emp-modal"\);/.test(empModal),
  "renderEmpireModal marks its card as the Empire workspace");
// Phase 14A.3 widened this from "exactly one place" to "only Empire's own surfaces". Forces ▸
// Recruit became a territory recruitment panel that belongs to the Empire workspace — it is opened
// from the Forces table and its Back returns there — so it legitimately carries the same width. The
// rule this assertion exists for is unchanged and is still checked above: only Empire declares a
// width, and no GENERIC modal gets one. What is pinned now is which surfaces may claim it.
const recruitFor = slice("function openRecruitFor(key, reopen) {", "\n  function ", "openRecruitFor");
assert((code.match(/classList\.add\("emp-modal"\)/g) || []).length === 2,
  "...applied by exactly two surfaces, both Empire's");
assert(/ov\.querySelector\("\.modal-card"\)\.classList\.add\("emp-modal"\);/.test(recruitFor),
  "the second is the Empire Recruit panel, opened from the Forces table");
assert(empModal.indexOf("openModal(html)") < empModal.indexOf('classList.add("emp-modal")'),
  "the class is applied to the card this render just opened");
ok("2. the Empire panel and its Forces Recruit panel are the workspace — applied to their own " +
   "cards, and to nothing generic");

// ===================== 3. the overflow is fixed, not hidden =====================
assert(/\.emp-scroll \{ overflow-x: auto; \}/.test(html),
  "the horizontal safety valve is still `auto` — never `hidden`, which would clip the controls " +
  "instead of making them reachable");
assert(!/\.emp-scroll \{[^}]*overflow-x: hidden/.test(html), "...and it is not clipped");
assert(!/\.emp-tbl \{[^}]*overflow-x: hidden/.test(html), "...nor is the table");
ok("3. the overflow is removed by fitting the content, not by clipping it");

// ===================== 4. a territory name can never force the table wider =====================
assert(/\.emp-tbl th:first-child, \.emp-tbl td:first-child \{ white-space: normal; min-width: [\d.]+em; \}/
  .test(html), "the territory-name column wraps");
assert(/\.emp-tbl th, \.emp-tbl td \{[^}]*white-space: nowrap;/.test(html),
  "...while the numeric columns stay on one line");
ok("4. long territory names wrap instead of widening the table — one long name cannot bring the " +
   "sideways scroll back");

// ===================== 5. below the fitting width the table stacks =====================
const stack = slice("@media (max-width: 860px) {", "\n  .ev-list", "the stacked layout") ||
              slice("@media (max-width: 860px) {", "}\n", "the stacked layout");
assert(/\.emp-scroll \{ overflow-x: visible; \}/.test(stack),
  "the stacked layout removes the scroll container's need to scroll");
assert(/\.emp-tbl thead \{ display: none; \}/.test(stack), "the header row is dropped when stacked");
assert(/\.emp-tbl tbody tr, \.emp-tbl tfoot tr \{[\s\S]{0,200}display: grid;/.test(stack),
  "each row becomes its own card");
assert(/\.emp-tbl td:last-child \.emp-act \{ width: 100%;/.test(stack),
  "the row's action becomes a full-width button — the control the player could not reach");
assert(/\.emp-tbl td\[data-l\]::before \{ content: attr\(data-l\);/.test(stack),
  "the values are labelled from the cell itself, since the header is gone");
ok("5. below the width where the widest table fits, rows stack into labelled cards and the action " +
   "becomes a full-width button");

// ===================== 6. every stacked cell has a label to show =====================
const forces = slice("function empireForces(", "function openRecruitFor(", "empireForces");
assert(/'<td data-l="' \+ t\.en \+ '"><b>' \+ \(pool\[t\.id\] \|\| 0\)/.test(forces),
  "the Home Base row labels its troop cells");
assert(/'<td data-l="' \+ t\.en \+ '"><b>' \+ \(g\[t\.id\] \|\| 0\)/.test(forces),
  "each territory row labels its troop cells");
assert((forces.match(/data-l="Total"/g) || []).length === 3,
  "the Total column is labelled on the home row, the territory rows and the footer");
const builds = slice("function empireBuildings(", "function empireTechnology(", "empireBuildings");
assert(/data-l="' \+ escapeHtml\(b\.name\) \+ '"/.test(builds), "Buildings labels its cells by building name");
const tech = slice("function empireTechnology(", "function openConscript", "empireTechnology") ||
             slice("function empireTechnology(", "\n  function ", "empireTechnology");
assert(/data-l="Forging"/.test(tech) && /data-l="Armour"/.test(tech) && /data-l="Armory"/.test(tech),
  "Technology labels its three data cells");
ok("6. Forces, Buildings and Technology all carry the labels the stacked layout reads — no tab " +
   "loses its meaning on a phone");

// ===================== 7. Recruit stays in Forces =====================
assert(/data-rec="' \+ HOME_KEY \+ '">Recruit/.test(forces),
  "the Home Base row still offers Recruit");
assert(/data-rec="' \+ escapeHtml\(m\.key\) \+ '">Recruit/.test(forces),
  "every territory row still offers Recruit");
assert(/body\.querySelectorAll\("\[data-rec\]"\)\.forEach\(b => b\.addEventListener\("click", \(\) => \{\s*openRecruitFor\(b\.dataset\.rec, reopen\);/
  .test(forces), "Recruit is launched from the Forces table itself, not from somewhere else");
assert(!/emp-scroll[\s\S]{0,80}display: none/.test(html),
  "no column was hidden to make the table fit — the fix is width, not amputation");
ok("7. Recruit is still offered directly on every Forces row, home base included");

// ===================== 8. the four Empire areas are unchanged =====================
assert(/const TABS = \[\["overview", "\u{1F5FA}️ Overview"\], \["forces", "⚔️ Forces"\],/u.test(code),
  "the tab set is unchanged");
assert(/\["buildings", "\u{1F3DB}️ Buildings"\], \["tech", "\u{1F3ED} Technology"\]\]/u.test(code),
  "...all four of them");
assert(/if \(empTab === "overview"\) empireOverview\(body, rows\);/.test(code) &&
       /else if \(empTab === "forces"\) empireForces\(body, rows, reopen\);/.test(code) &&
       /else if \(empTab === "buildings"\) empireBuildings\(body, rows, reopen\);/.test(code) &&
       /else empireTechnology\(body, rows, reopen\);/.test(code),
  "each area still paints through its own renderer");
ok("8. Overview / Forces / Buildings / Technology are the same four areas, same renderers — this is " +
   "a layout fix, not a redesign");

// ===================== 9. no server or authority change =====================
assert(/function terrRecruit\(key, unit, qty, cb\) \{ terrPost\("\/api\/territory\/recruit", \{ file: key, unit: unit, qty: qty \}, cb\); \}/
  .test(code), "the recruit endpoint and payload are unchanged");
assert(/terrRecruit\(key, btn\.dataset\.unit, RECRUIT_BATCH, reopen\)/.test(code),
  "and the recruit call site is unchanged (see the quantity finding in the report)");
ok("9. no endpoint, payload or authority moved — Empire only changed shape");

console.log("\nAll " + passed + " Empire-workspace checks passed.");
