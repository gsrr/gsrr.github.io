// Territory catalog tool — Phase 1A.5 (merge-safe).
//
//   node tools/gen_territory_catalog.js --check   (default; read-only report)
//   node tools/gen_territory_catalog.js --init     (bootstrap: create only missing files)
//   node tools/gen_territory_catalog.js --merge     (structural sync: add new / repair svg refs / backfill;
//                                                    NEVER overwrites designer-authored metadata)
//
// world-data/ is AUTHORITATIVE production content. This tool discovers territories from
// maps/*.svg and freezes initial population/names, but it must never clobber designer edits
// (gamePopulation, localizedNames, terrain, settlement, features, adjacency, economy, quests,
// ai, events, or _meta.lastDesignerEdit). See docs/world-data.md.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.join(__dirname, "..");
// world-data location (override with TERR_CATALOG_DIR for tests; production is the repo dir)
const OUT = process.env.TERR_CATALOG_DIR ? path.resolve(process.env.TERR_CATALOG_DIR) : path.join(ROOT, "world-data");
const SCHEMA_VERSION = 1;
const CATALOG_VERSION = 1;
const GENERATOR_VERSION = "1.0.0";
const GENERATED_BY = "tools/gen_territory_catalog.js";
// generator-owned (structural) vs designer-owned fields:
const DESIGNER_FIELDS = ["displayName", "localizedNames", "gamePopulation", "populationSource",
  "terrainType", "settlementType", "features", "adjacentTerritoryIds", "economy", "quests", "ai", "events",
  "requirements"];   // Phase 3A: designer-owned learning gate (requirements.attackQualificationIds) — never clobbered

// ---------- shared SVG discovery (mirrors index.html render rules; freezes population) ----------
function loadAppData() {
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  const lit = (marker, open) => {
    const i = html.indexOf(marker), start = html.indexOf(open, i), close = open === "{" ? "}" : "]";
    let d = 0, k = start; for (; k < html.length; k++) { if (html[k] === open) d++; else if (html[k] === close) { d--; if (!d) { k++; break; } } }
    return html.slice(start, k);
  };
  const fn = name => { const i = html.indexOf("function " + name), s = html.indexOf("{", i); let d = 0, k = s; for (; k < html.length; k++) { if (html[k] === "{") d++; else if (html[k] === "}") { d--; if (!d) { k++; break; } } } return html.slice(i, k); };
  const sb = {};
  // Phase 10A.3R.1: China province labels come from world-data, the curated source, NOT from
  // index.html. This used to slice the client from `html.indexOf('"A1":')` to reach the `names:`
  // table that lived inside the old GAME_MAPS["A1"] china spec. That anchor was never about China —
  // it was a CEFR course key — so when Single-World consolidation removed the china spec the search
  // silently landed on BOSS_ARMY_BY_LEVEL's "A1" and produced un-evaluable JS. Catalog generation
  // must not depend on Learning course names or on any client map table.
  const chinaNames = (() => {
    const out = {};
    try {
      const rows = JSON.parse(fs.readFileSync(
        path.join(OUT, "territories", "china.json"), "utf8"));
      rows.forEach(t => { if (t.regionCode && t.displayName) out[t.regionCode] = t.displayName; });
    } catch (e) { /* first-ever generation: labels fall back to the svg path id */ }
    return out;
  })();
  vm.runInNewContext(
    "POP_TABLE = " + lit("const POP_TABLE", "{") + ";\n" +
    "WORLD_CONTINENTS = " + lit("const WORLD_CONTINENTS", "[") + ";\n" +
    fn("popForName") + ";\n" +
    "this.POP_TABLE=POP_TABLE;this.WORLD_CONTINENTS=WORLD_CONTINENTS;this.popForName=popForName;", sb);
  const codeCont = {}; sb.WORLD_CONTINENTS.forEach(c => c.codes.split(/\s+/).forEach(cd => { codeCont[cd] = c.key; }));
  return { POP_TABLE: sb.POP_TABLE, CHINA_NAMES: chinaNames, popForName: sb.popForName, codeCont };
}
const APP = loadAppData();
const splitName = s => { const m = s.match(/[一-鿿].*$/); return { en: (s.replace(/[一-鿿].*$/, "").trim()) || s, zh: m ? m[0].trim() : null }; };
const svgPaths = file => (fs.readFileSync(path.join(ROOT, file), "utf8").match(/<path\b[\s\S]*?>/g) || [])
  .map(t => ({ id: (t.match(/id="([^"]*)"/) || [])[1] || "", label: (t.match(/aria-label="([^"]*)"/) || [])[1] || "" }));

const MAPS = [
  { id: "taiwan", svgFile: "maps/taiwan.svg", name: "Taiwan 台灣" },
  { id: "taipei", svgFile: "maps/taiwan-taipei.svg", name: "Taipei 台北" },
  { id: "china", svgFile: "maps/china.svg", name: "China 中國" },
  { id: "world", svgFile: "maps/world.svg", name: "World 世界" }
];

// Canonical regionCode for an SVG path id. THE ONE PLACE the china multi-path suffix
// rule lives: china provinces are drawn as pXX or pXX_<n> (e.g. pLN_1, pTW_3) — group them
// by the pXX prefix so pLN_1/pLN_2 -> china:pLN. Other maps use the path id verbatim.
function regionCodeFor(mapId, pathId) {
  if (mapId === "china") { const m = pathId.match(/^(p[A-Z]{2})(_.*)?$/); return m ? m[1] : null; }
  if (mapId === "world") { return /^[a-z]{2}$/i.test(pathId) ? pathId : null; }
  return pathId || null;   // taiwan / taipei: aria-labelled slug ids
}

// discovered (generator-owned) shape for one map — one entry per LOGICAL territory
function discover(map) {
  const groups = {};   // regionCode -> {label, pathIds:[], count}
  svgPaths(map.svgFile).forEach(p => {
    let label;
    if (map.id === "china") label = APP.CHINA_NAMES[(p.id.match(/^(p[A-Z]{2})/) || [])[1]] || p.id;
    else label = p.label;
    if (map.id !== "china" && map.id !== "world" && !p.label) return;   // taiwan/taipei need aria-label
    const code = regionCodeFor(map.id, p.id);
    if (!code) return;
    const g = groups[code] || (groups[code] = { label, pathIds: [], count: 0 });
    g.pathIds.push(p.id); g.count++;
  });
  return Object.keys(groups).map(code => {
    const nm = splitName(groups[code].label), loc = { en: nm.en };
    if (nm.zh) loc["zh-TW"] = nm.zh;
    const meta = {};
    if (map.id === "world" && APP.codeCont[code.toLowerCase()]) meta.continent = APP.codeCont[code.toLowerCase()];
    return {
      id: map.id + ":" + code, mapId: map.id, regionCode: code,
      displayName: groups[code].label, localizedNames: loc,
      svgPathKeys: groups[code].pathIds.slice(),   // ALL svg paths of this logical territory
      administrativeCode: map.id === "world" ? code.toUpperCase() : null,
      gamePopulation: APP.popForName(groups[code].label),
      metadata: meta, _componentCount: groups[code].count
    };
  });
}

function newTerritory(disc, now) {
  return {
    id: disc.id, mapId: disc.mapId, regionCode: disc.regionCode,
    displayName: disc.displayName, localizedNames: disc.localizedNames,
    svgPathKeys: disc.svgPathKeys, administrativeCode: disc.administrativeCode,
    gamePopulation: disc.gamePopulation,
    populationSource: { value: null, year: null, sourceName: null, sourceUrl: null },
    metadata: disc.metadata,
    terrainType: null, settlementType: null, features: [], adjacentTerritoryIds: [],
    economy: null, quests: [], ai: null, events: [],       // reserved placeholders (do not populate)
    _meta: { schemaVersion: SCHEMA_VERSION, catalogVersion: CATALOG_VERSION, generatedBy: GENERATED_BY,
             generatedAt: now, generatorVersion: GENERATOR_VERSION, lastDesignerEdit: null }
  };
}

// merge one discovered territory into an existing one WITHOUT overwriting designer fields
function backfill(existing, disc, now) {
  const tmpl = newTerritory(disc, now);
  Object.keys(tmpl).forEach(k => { if (!(k in existing)) existing[k] = tmpl[k]; });   // add only missing fields
  existing.svgPathKeys = disc.svgPathKeys;                                            // structural: repair svg mapping
  existing.regionCode = disc.regionCode; existing.mapId = disc.mapId;
  if (existing.administrativeCode == null) existing.administrativeCode = disc.administrativeCode;
  const m = existing._meta || {};
  existing._meta = {
    schemaVersion: SCHEMA_VERSION, catalogVersion: CATALOG_VERSION, generatedBy: GENERATED_BY,
    generatedAt: m.generatedAt || now, generatorVersion: GENERATOR_VERSION,
    lastDesignerEdit: (m.lastDesignerEdit !== undefined ? m.lastDesignerEdit : null)
  };
  return existing;
}

function readJson(p, def) { try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch (e) { return def; } }
function writeJson(p, obj) { fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, JSON.stringify(obj, null, 2) + "\n"); }
function terrFile(mapId) { return path.join(OUT, "territories", mapId + ".json"); }

function writeCatalogMeta(now, total, mode) {
  const p = path.join(OUT, "catalog.json");
  const prev = readJson(p, null);
  writeJson(p, {
    catalogVersion: CATALOG_VERSION, schemaVersion: SCHEMA_VERSION, generatorVersion: GENERATOR_VERSION,
    createdAt: (prev && prev.createdAt) || now, updatedAt: now,
    maps: MAPS.length, territories: total
  });
}

// ---------------------------- modes ----------------------------
function runCheck() {
  let issues = 0, total = 0;
  MAPS.forEach(m => {
    const disc = discover(m), discIds = new Set(disc.map(d => d.id));
    const existing = readJson(terrFile(m.id), null);
    if (existing === null) { console.log("  [" + m.id + "] MISSING territory file"); issues++; return; }
    total += existing.length;
    const exIds = new Set(existing.map(t => t.id));
    disc.forEach(d => { if (!exIds.has(d.id)) { console.log("  [" + m.id + "] missing territory: " + d.id); issues++; } });
    existing.forEach(t => { if (!discIds.has(t.id)) { console.log("  [" + m.id + "] unknown/obsolete territory: " + t.id); issues++; } });
    const seenPaths = {};
    existing.forEach(t => (t.svgPathKeys || []).forEach(pk => {
      const dk = discIds.has(t.id) ? disc.find(d => d.id === t.id).svgPathKeys : [];
      if (dk.indexOf(pk) < 0) { console.log("  [" + m.id + "] obsolete svg ref " + t.id + " -> " + pk); issues++; }
      const key = m.id + "|" + pk; if (seenPaths[key]) { console.log("  [" + m.id + "] duplicate svg mapping " + pk); issues++; } seenPaths[key] = 1;
    }));
  });
  console.log("check: " + total + " territories, " + issues + " issue(s)");
  return issues === 0 ? 0 : 1;
}

function runInit(now) {
  let created = 0, skipped = 0, total = 0;
  if (!fs.existsSync(path.join(OUT, "maps.json"))) writeJson(path.join(OUT, "maps.json"), MAPS);
  MAPS.forEach(m => {
    const f = terrFile(m.id);
    if (fs.existsSync(f)) { const ex = readJson(f, []); total += ex.length; skipped++; console.log("  [" + m.id + "] exists — skipped (init never overwrites)"); return; }
    const disc = discover(m).map(d => newTerritory(d, now));
    writeJson(f, disc); created++; total += disc.length; console.log("  [" + m.id + "] created " + disc.length + " territories");
  });
  writeCatalogMeta(now, total, "init");
  console.log("init: created " + created + " file(s), skipped " + skipped + ", total " + total);
  return 0;
}

function runMerge(now) {
  let added = 0, backfilled = 0, obsolete = 0, total = 0;
  if (!fs.existsSync(path.join(OUT, "maps.json"))) writeJson(path.join(OUT, "maps.json"), MAPS);
  MAPS.forEach(m => {
    const disc = discover(m), byId = {}; disc.forEach(d => { byId[d.id] = d; });
    let existing = readJson(terrFile(m.id), null);
    if (existing === null) existing = [];
    const exById = {}; existing.forEach(t => { exById[t.id] = t; });
    // add new territories
    disc.forEach(d => { if (!exById[d.id]) { existing.push(newTerritory(d, now)); exById[d.id] = existing[existing.length - 1]; added++; } });
    // backfill + repair existing (preserve designer fields)
    existing.forEach(t => {
      if (byId[t.id]) backfill(t, byId[t.id], now);
      else {   // territory no longer in SVG → strip obsolete svg refs, keep record, report
        if ((t.svgPathKeys || []).length) { t.svgPathKeys = []; obsolete++; console.log("  [" + m.id + "] obsolete (no SVG): " + t.id + " — svgPathKeys cleared, record kept for designer review"); }
      }
    });
    existing.forEach(t => { if (byId[t.id]) backfilled++; });
    writeJson(terrFile(m.id), existing);
    total += existing.length;
  });
  writeCatalogMeta(now, total, "merge");
  console.log("merge: added " + added + ", synced " + backfilled + ", obsolete " + obsolete + ", total " + total);
  return 0;
}

// ---------------------------- CLI ----------------------------
function main() {
  const mode = (process.argv[2] || "--check");
  const now = new Date().toISOString();
  if (mode === "--check") process.exit(runCheck());
  if (mode === "--init") process.exit(runInit(now));
  if (mode === "--merge") process.exit(runMerge(now));
  console.error("unknown mode " + mode + " (use --check | --init | --merge)");
  process.exit(2);
}
if (require.main === module) main();

module.exports = { discover, newTerritory, backfill, runInit, runMerge, runCheck, MAPS,
  SCHEMA_VERSION, CATALOG_VERSION, GENERATOR_VERSION, DESIGNER_FIELDS };
