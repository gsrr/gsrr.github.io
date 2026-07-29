// Phase 2A golden-master: run the REFERENCE JS battle core (battleResolve, extracted from
// index.html) over fixed-order scenarios and record winner/survivors. The Python engine
// (game/battle.py) must reproduce these exactly.  node tools/gen_battle_golden.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");

function lit(marker, open) {
  const i = html.indexOf(marker), s = html.indexOf(open, i), c = open === "{" ? "}" : "]";
  let d = 0, k = s; for (; k < html.length; k++) { if (html[k] === open) d++; else if (html[k] === c) { d--; if (!d) { k++; break; } } }
  return html.slice(s, k);
}
function fn(name) {
  const i = html.indexOf("function " + name), s = html.indexOf("{", i);
  let d = 0, k = s; for (; k < html.length; k++) { if (html[k] === "{") d++; else if (html[k] === "}") { d--; if (!d) { k++; break; } } }
  return html.slice(i, k);
}
const ctx = {};
vm.runInNewContext(
  "TROOPS = " + lit("const TROOPS = [", "[") + ";\n" +
  "const TROOP = {}; TROOPS.forEach(t => TROOP[t.id] = t);\n" +
  fn("atkBonus") + ";\n" + fn("defBonus") + ";\n" +
  "const DMG_SCALE = 12;\n" + fn("baseHit") + ";\n" + fn("troopHit") + ";\n" + fn("battleResolve") + ";\n" +
  "this.battleResolve = battleResolve;", ctx);
const battleResolve = ctx.battleResolve;

const T = (type, hp) => ({ type: type, hp: hp });
// tech {atk,def} → forge/armor (canonical +10%/level)
const forge = t => 0.10 * ((t && t.atk) || 0), armor = t => 0.10 * ((t && t.def) || 0);

// Each scenario: fixed attacker + fixed defender ORDER (no shuffle) + tech → deterministic.
const scenarios = [
  { name: "inf_vs_inf", att: [T("inf", 30)], def: [T("inf", 30)] },
  { name: "inf_vs_archer", att: [T("inf", 40)], def: [T("archer", 40)] },
  { name: "archer_vs_cav", att: [T("archer", 40)], def: [T("cav", 40)] },
  { name: "cav_vs_inf", att: [T("cav", 40)], def: [T("inf", 40)] },
  { name: "spear_vs_cav", att: [T("spear", 30)], def: [T("cav", 30)] },
  { name: "attacker_big_win", att: [T("cav", 90), T("inf", 60)], def: [T("archer", 20)] },
  { name: "defender_win", att: [T("inf", 15)], def: [T("spear", 50), T("cav", 40)] },
  { name: "undefended", att: [T("inf", 10)], def: [] },
  { name: "mixed_multi", att: [T("cav", 40), T("archer", 35), T("inf", 30), T("spear", 25)], def: [T("inf", 45), T("archer", 30), T("cav", 25)] },
  { name: "atk_tech3", att: [T("inf", 30)], def: [T("inf", 30)], atkTech: { atk: 3 } },
  { name: "def_tech3", att: [T("inf", 30)], def: [T("inf", 30)], defTech: { def: 3 } },
  { name: "both_tech", att: [T("cav", 50)], def: [T("archer", 50)], atkTech: { atk: 2, def: 1 }, defTech: { atk: 1, def: 2 } },
  { name: "round_cap_stalemate", att: [T("inf", 100)], def: [T("inf", 100)] },
];

const out = { note: "Golden master from JS battleResolve (canonical). Defender order is as given (no shuffle).", cases: [] };
scenarios.forEach(s => {
  const r = battleResolve(s.att.map(u => ({ type: u.type, hp: u.hp, max: u.hp })),
    s.def.map(u => ({ type: u.type, hp: u.hp, max: u.hp })),
    forge(s.atkTech), armor(s.atkTech), forge(s.defTech), armor(s.defTech));
  out.cases.push({
    name: s.name, att: s.att, def: s.def, atkTech: s.atkTech || {}, defTech: s.defTech || {},
    attackerWon: r.attackerWon,
    attackerSurvivors: r.att.filter(u => u.hp > 0).map(u => ({ type: u.type, hp: Math.round(u.hp) })),
    defenderSurvivors: r.def.filter(u => u.hp > 0).map(u => ({ type: u.type, hp: Math.round(u.hp) })),
    steps: r.steps.length,
  });
});
fs.mkdirSync(path.join(ROOT, "tests", "fixtures"), { recursive: true });
fs.writeFileSync(path.join(ROOT, "tests", "fixtures", "battle_golden.json"), JSON.stringify(out, null, 2) + "\n");
console.log("wrote battle_golden.json:", out.cases.length, "cases;",
  out.cases.map(c => c.name + "=" + (c.attackerWon ? "W" : "L")).join(" "));
