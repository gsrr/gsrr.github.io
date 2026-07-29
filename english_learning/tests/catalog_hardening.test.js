// Phase 1A.5 — generator hardening tests (modes + merge-safety).
//   node tests/catalog_hardening.test.js
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const assert = require("assert");

const ROOT = path.join(__dirname, "..");
const GEN = path.join(ROOT, "tools", "gen_territory_catalog.js");
const gen = require(GEN);   // exported pure fns

function run(mode, dir) {
  return cp.execFileSync(process.execPath, [GEN, mode],
    { env: Object.assign({}, process.env, { TERR_CATALOG_DIR: dir }), encoding: "utf8" });
}
function readT(dir, map) { return JSON.parse(fs.readFileSync(path.join(dir, "territories", map + ".json"), "utf8")); }
function writeT(dir, map, arr) { fs.writeFileSync(path.join(dir, "territories", map + ".json"), JSON.stringify(arr, null, 2)); }
function hashDir(dir) {
  const parts = [];
  function walk(d) { fs.readdirSync(d).sort().forEach(f => { const p = path.join(d, f); const s = fs.statSync(p); if (s.isDirectory()) walk(p); else parts.push(f + ":" + fs.readFileSync(p, "utf8")); }); }
  walk(dir); return parts.join("\n");
}

let n = 0; function test(name, fn) { fn(); n++; console.log("  ok -", name); }

// ---- pure backfill: designer fields survive, missing fields added, _meta preserved ----
test("backfill preserves designer fields and back-fills missing ones", () => {
  const disc = { id: "china:pBJ", mapId: "china", regionCode: "pBJ", displayName: "GEN NAME",
    localizedNames: { en: "GenName" }, svgPathKeys: ["pBJ"], administrativeCode: null,
    gamePopulation: 999, metadata: {} };
  const existing = { id: "china:pBJ", mapId: "china", regionCode: "pBJ",
    displayName: "Designer Name", localizedNames: { en: "Designer" }, svgPathKeys: ["pBJ"],
    gamePopulation: 123, terrainType: "mountain",              // designer edits
    _meta: { schemaVersion: 1, catalogVersion: 1, generatedBy: "x", generatedAt: "T0",
             generatorVersion: "0.9", lastDesignerEdit: "2026-01-01" } };
  gen.backfill(existing, disc, "NOW");
  assert.strictEqual(existing.displayName, "Designer Name", "displayName not overwritten");
  assert.strictEqual(existing.gamePopulation, 123, "gamePopulation not overwritten");
  assert.strictEqual(existing.terrainType, "mountain", "terrain preserved");
  assert.strictEqual(existing.economy, null, "missing placeholder back-filled");
  assert.deepStrictEqual(existing.quests, [], "missing placeholder back-filled");
  assert.strictEqual(existing._meta.generatedAt, "T0", "generatedAt preserved");
  assert.strictEqual(existing._meta.lastDesignerEdit, "2026-01-01", "lastDesignerEdit preserved");
  assert.strictEqual(existing._meta.generatorVersion, gen.GENERATOR_VERSION, "generatorVersion refreshed");
});

// ---- CLI modes on a temp catalog dir ----
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "wd-"));
fs.mkdirSync(path.join(tmp, "territories"), { recursive: true });

test("init creates missing files with _meta + placeholders", () => {
  run("--init", tmp);
  assert.ok(fs.existsSync(path.join(tmp, "catalog.json")));
  const china = readT(tmp, "china");
  assert.ok(china.length > 0);
  const t = china[0];
  assert.ok(t._meta && t._meta.schemaVersion === gen.SCHEMA_VERSION, "_meta present");
  assert.ok("economy" in t && "quests" in t && "ai" in t && "events" in t, "placeholders present");
});

test("init does NOT overwrite an existing file (designer edit survives)", () => {
  const china = readT(tmp, "china");
  china[0].gamePopulation = 4242; china[0].terrainType = "desert";
  china[0]._meta.lastDesignerEdit = "2026-02-02";
  writeT(tmp, "china", china);
  run("--init", tmp);                                     // should skip (file exists)
  const after = readT(tmp, "china");
  assert.strictEqual(after[0].gamePopulation, 4242, "init left designer value untouched");
  assert.strictEqual(after[0].terrainType, "desert");
  assert.strictEqual(after[0]._meta.lastDesignerEdit, "2026-02-02");
});

test("merge preserves designer edits and re-adds a removed placeholder", () => {
  const china = readT(tmp, "china");
  delete china[0].economy;                                // simulate schema drift / missing field
  writeT(tmp, "china", china);
  run("--merge", tmp);
  const after = readT(tmp, "china");
  assert.strictEqual(after[0].gamePopulation, 4242, "merge preserved designer population");
  assert.strictEqual(after[0].terrainType, "desert", "merge preserved terrain");
  assert.strictEqual(after[0]._meta.lastDesignerEdit, "2026-02-02", "merge preserved lastDesignerEdit");
  assert.strictEqual(after[0].economy, null, "merge re-added missing placeholder");
});

test("check is read-only (no file modifications)", () => {
  const before = hashDir(tmp);
  try { run("--check", tmp); } catch (e) { /* non-zero exit on drift is allowed; we only assert no writes */ }
  const after = hashDir(tmp);
  assert.strictEqual(before, after, "check must not modify any file");
});

console.log("\nAll " + n + " hardening tests passed.");
