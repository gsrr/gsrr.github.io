// Phase 1A frontend tests — canonical territory identity + catalog population.
// Extracts the REAL functions from index.html and the REAL catalog from world-data/.
//   node tests/territory_catalog.test.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");

function extractLiteral(src, marker, open) {
  const i = src.indexOf(marker), start = src.indexOf(open, i), close = open === "{" ? "}" : "]";
  let d = 0, k = start;
  for (; k < src.length; k++) { if (src[k] === open) d++; else if (src[k] === close) { d--; if (!d) { k++; break; } } }
  return src.slice(start, k);
}
function extractFn(src, name) {
  const i = src.indexOf("function " + name), start = src.indexOf("{", i);
  let d = 0, k = start;
  for (; k < src.length; k++) { if (src[k] === "{") d++; else if (src[k] === "}") { d--; if (!d) { k++; break; } } }
  return src.slice(i, k);
}
// contiguous catalog block: from `const TERR_CATALOG` up to (not incl) loadTerritoryCatalog
function extractBlock(src, from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  return src.slice(a, b);
}

const ctx = { console: { warn: function () {} } };
vm.runInNewContext(
  "POP_TABLE = " + extractLiteral(html, "const POP_TABLE", "{") + ";\n" +
  extractFn(html, "popForName") + ";\n" +
  extractBlock(html, "const TERR_CATALOG =", "function loadTerritoryCatalog") + "\n" +
  "this.T = { canonicalTerritoryId, territoryForPath, catalogPopulation, mapIdForSvg, popForName, TERR_CATALOG };",
  ctx
);
const T = ctx.T;

// load the REAL catalog into TERR_CATALOG (mirrors loadTerritoryCatalog without fetch)
const maps = JSON.parse(fs.readFileSync(path.join(ROOT, "world-data", "maps.json"), "utf8"));
maps.forEach(m => { T.TERR_CATALOG.maps[m.id] = m; T.TERR_CATALOG.mapIdBySvg[m.svgFile] = m.id; });
maps.forEach(m => {
  JSON.parse(fs.readFileSync(path.join(ROOT, "world-data", "territories", m.id + ".json"), "utf8"))
    .forEach(t => { T.TERR_CATALOG.terrById[t.id] = t; (t.svgPathKeys || []).forEach(pk => { T.TERR_CATALOG.terrByMapPath[t.mapId + "|" + pk] = t; }); });
});
T.TERR_CATALOG.loaded = true;

let n = 0; function test(name, fn) { fn(); n++; console.log("  ok -", name); }

test("canonical territory ID generation", () => {
  assert.strictEqual(T.canonicalTerritoryId("world", "us"), "world:us");
  assert.strictEqual(T.canonicalTerritoryId("china", "pBJ"), "china:pBJ");
});

test("path resolves to canonical territory (real catalog)", () => {
  assert.strictEqual(T.territoryForPath("china", "pBJ").id, "china:pBJ");
  assert.strictEqual(T.territoryForPath("world", "us").id, "world:us");
});

test("population comes from catalog gamePopulation, not fallback", () => {
  const t = T.territoryForPath("world", "id");                 // Indonesia
  assert.strictEqual(T.catalogPopulation("world", "id", "Indonesia"), t.gamePopulation);
  assert.ok(Number.isInteger(t.gamePopulation) && t.gamePopulation >= 0);
});

test("one logical territory may map to multiple SVG paths", () => {
  // model supports N paths per territory: inject a synthetic multi-path territory
  const terr = { id: "syn:multi", mapId: "syn", regionCode: "multi", gamePopulation: 42, svgPathKeys: ["a", "b", "c"] };
  T.TERR_CATALOG.terrById["syn:multi"] = terr;
  ["a", "b", "c"].forEach(pk => { T.TERR_CATALOG.terrByMapPath["syn|" + pk] = terr; });
  const ra = T.territoryForPath("syn", "a"), rb = T.territoryForPath("syn", "b"), rc = T.territoryForPath("syn", "c");
  assert.ok(ra === rb && rb === rc, "all components resolve to the same territory object");
  assert.strictEqual(ra.id, "syn:multi");
});

test("clicking different components -> same territory & counted once", () => {
  const clickedPaths = ["a", "b", "a", "c"];                    // 4 clicks across 3 components of one territory
  const owned = {};
  clickedPaths.forEach(pk => { const t = T.territoryForPath("syn", pk); owned[t.id] = t.gamePopulation; });
  assert.deepStrictEqual(Object.keys(owned), ["syn:multi"], "one logical territory");
  const totalPop = Object.values(owned).reduce((a, b) => a + b, 0);
  assert.strictEqual(totalPop, 42, "population counted once, not per component");
});

test("missing catalog entry uses controlled fallback (popForName)", () => {
  const got = T.catalogPopulation("world", "zzz", "Neverland");
  assert.strictEqual(got, T.popForName("Neverland"), "falls back deterministically");
});

console.log("\nAll " + n + " frontend catalog tests passed.");
