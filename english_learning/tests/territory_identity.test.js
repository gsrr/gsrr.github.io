// Phase 1B frontend tests — one resolver; canonical identity from SVG paths.
//   node tests/territory_identity.test.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

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
function block(from, to) { const a = html.indexOf(from), b = html.indexOf(to, a); return html.slice(a, b); }

const ctx = { console: { warn: function () {} } };
vm.runInNewContext(
  "POP_TABLE = " + lit("const POP_TABLE", "{") + ";\n" +
  fn("popForName") + ";\n" +
  block("const TERR_CATALOG =", "function loadTerritoryCatalog") + "\n" +
  fn("resolveSvgPath") + ";\n" +
  fn("regionKey") + ";\n" +
  "this.T = { TERR_CATALOG, resolveSvgPath, regionKey, canonicalTerritoryId, mapIdForSvg, territoryForPath };",
  ctx
);
const T = ctx.T;

// load real catalog
const maps = JSON.parse(fs.readFileSync(path.join(ROOT, "world-data", "maps.json"), "utf8"));
maps.forEach(m => { T.TERR_CATALOG.maps[m.id] = m; T.TERR_CATALOG.mapIdBySvg[m.svgFile] = m.id; });
maps.forEach(m => JSON.parse(fs.readFileSync(path.join(ROOT, "world-data", "territories", m.id + ".json"), "utf8"))
  .forEach(t => { T.TERR_CATALOG.terrById[t.id] = t; (t.svgPathKeys || []).forEach(pk => { T.TERR_CATALOG.terrByMapPath[t.mapId + "|" + pk] = t; }); }));
T.TERR_CATALOG.loaded = true;

const fakeP = id => ({ id: id, getAttribute: () => null });
let n = 0; function test(name, f) { f(); n++; console.log("  ok -", name); }

test("resolveSvgPath: plain path -> canonical id", () => {
  assert.strictEqual(T.resolveSvgPath("world", "us"), "world:us");
  assert.strictEqual(T.resolveSvgPath("china", "pBJ"), "china:pBJ");
  assert.strictEqual(T.resolveSvgPath("taipei", "xinyi"), "taipei:xinyi");
});

test("resolveSvgPath: china multi-path suffix collapses to one territory", () => {
  assert.strictEqual(T.resolveSvgPath("china", "pLN_1"), "china:pLN");
  assert.strictEqual(T.resolveSvgPath("china", "pLN_2"), "china:pLN");
  assert.strictEqual(T.resolveSvgPath("china", "pTW_3"), "china:pTW");
});

test("regionKey returns the canonical territory id (game identity)", () => {
  const spec = { file: "maps/china.svg" };
  assert.strictEqual(T.regionKey(spec, fakeP("pLN_1")), "china:pLN");
  assert.strictEqual(T.regionKey(spec, fakeP("pLN_2")), "china:pLN");
  assert.strictEqual(T.regionKey({ file: "maps/world.svg" }, fakeP("us")), "world:us");
});

test("click/hover on different components -> same canonical key (one owner)", () => {
  const spec = { file: "maps/china.svg" };
  const keys = ["pLN_1", "pLN_2"].map(p => T.regionKey(spec, fakeP(p)));
  assert.deepStrictEqual([...new Set(keys)], ["china:pLN"], "all components share one ownership key");
});

test("offline fallback still strips china suffix when catalog lacks the entry", () => {
  // pZZ is not in the catalog -> resolver falls back to the documented suffix rule
  assert.strictEqual(T.resolveSvgPath("china", "pZZ_2"), "china:pZZ");
  assert.strictEqual(T.resolveSvgPath("world", "us"), "world:us");
});

console.log("\nAll " + n + " frontend identity tests passed.");
