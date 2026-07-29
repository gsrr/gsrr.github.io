// Tests for the zoom-based map label placement (placeMapLabels / rectsOverlap).
// These extract the REAL functions from index.html (brace-matched) and eval them,
// so the tests exercise the shipped code, not a copy.
// Run: node tests/labels.test.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

// Pull out a `function name(...) { ... }` by matching balanced braces.
function extractFn(src, name) {
  const i = src.indexOf("function " + name);
  if (i < 0) throw new Error("function not found: " + name);
  const open = src.indexOf("{", i);
  let depth = 0, k = open;
  for (; k < src.length; k++) {
    if (src[k] === "{") depth++;
    else if (src[k] === "}") { depth--; if (depth === 0) { k++; break; } }
  }
  return src.slice(i, k);
}

const ctx = {};
vm.runInNewContext(
  extractFn(html, "rectsOverlap") + "\n" + extractFn(html, "placeMapLabels") +
  "\nthis.placeMapLabels = placeMapLabels;",
  ctx
);
const placeMapLabels = ctx.placeMapLabels;

function B(x0, y0, x1, y1) { return { x0: x0, y0: y0, x1: x1, y1: y1 }; }
function lab(o) {
  return Object.assign({ priority: 1, minZoom: 0, maxZoom: Infinity, selected: false, box: B(0, 0, 10, 10) }, o);
}

let passed = 0;
function test(name, fn) { fn(); passed++; console.log("  ok -", name); }

// 1) Zoom filtering: below minZoom hidden; at/above minZoom eligible.
test("zoom filtering hides labels below their minZoom", () => {
  const country = lab({ minZoom: 0, box: B(0, 0, 20, 10) });
  const city = lab({ minZoom: 3, box: B(100, 100, 120, 110) }); // far away → no overlap factor
  placeMapLabels([country, city], 1);
  assert.strictEqual(country.visible, true, "country visible when zoomed out");
  assert.strictEqual(city.visible, false, "city hidden when zoomed out");
  placeMapLabels([country, city], 4);
  assert.strictEqual(city.visible, true, "city visible when zoomed in past minZoom");
});

test("zoom filtering respects maxZoom", () => {
  const a = lab({ minZoom: 0, maxZoom: 2 });
  placeMapLabels([a], 1); assert.strictEqual(a.visible, true);
  placeMapLabels([a], 5); assert.strictEqual(a.visible, false, "hidden above maxZoom");
});

// 2) Overlapping labels: the overlapped lower-priority one is hidden.
test("overlapping labels: only one of a colliding pair shows", () => {
  const hi = lab({ priority: 10, box: B(0, 0, 30, 12) });
  const lo = lab({ priority: 1, box: B(10, 2, 40, 14) }); // overlaps hi
  placeMapLabels([lo, hi], 1); // pass lo first to prove ordering isn't input-order dependent
  assert.strictEqual(hi.visible, true, "higher priority kept");
  assert.strictEqual(lo.visible, false, "overlapping lower priority hidden");
});

test("non-overlapping labels both show", () => {
  const a = lab({ priority: 5, box: B(0, 0, 20, 10) });
  const b = lab({ priority: 4, box: B(100, 0, 120, 10) });
  placeMapLabels([a, b], 1);
  assert.strictEqual(a.visible, true);
  assert.strictEqual(b.visible, true);
});

// 3) Priority ordering: among mutually-overlapping labels, the highest wins.
test("priority ordering: highest priority wins a 3-way overlap", () => {
  const box = B(0, 0, 40, 16);
  const p1 = lab({ priority: 1, box: B(0, 0, 40, 16) });
  const p2 = lab({ priority: 2, box: B(5, 1, 45, 17) });
  const p3 = lab({ priority: 3, box: B(2, 2, 42, 18) });
  placeMapLabels([p1, p2, p3], 1);
  assert.strictEqual(p3.visible, true, "priority 3 shown");
  assert.strictEqual(p2.visible, false);
  assert.strictEqual(p1.visible, false);
});

// 4) Selected label always visible — even if low priority, overlapping, or below minZoom.
test("selected label is always visible despite overlap + low priority", () => {
  const hi = lab({ priority: 100, box: B(0, 0, 40, 16) });
  const sel = lab({ priority: 1, selected: true, box: B(5, 1, 45, 17) }); // overlaps hi, low priority
  placeMapLabels([hi, sel], 1);
  assert.strictEqual(sel.visible, true, "selected stays visible");
});

test("selected label is visible even when below its minZoom", () => {
  const sel = lab({ minZoom: 5, selected: true, box: B(0, 0, 20, 10) });
  placeMapLabels([sel], 1);
  assert.strictEqual(sel.visible, true, "selected bypasses zoom filter");
});

console.log("\nAll " + passed + " label tests passed.");
