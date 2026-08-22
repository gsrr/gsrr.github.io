// Tests for the ONE camera transform that places territory labels on the World board.
//
// WHY THIS FILE EXISTS. Before Phase 13C the label layer measured its basis from
// svg.getBoundingClientRect(), which the browser reports AFTER the camera's CSS transform, and then
// applied the camera a second time. The scale was therefore squared and the pan doubled, so a label
// sat 214 px from its territory at the home camera and 2094 px away at 8x. Nothing in the suite
// noticed, because nothing executed the projection -- world_camera.test.js pins the camera's own
// API and labels.test.js pins the pure visibility filter, and the projection sat between them.
//
// These tests EXECUTE the shipped projection block, extracted from index.html, against stub
// geometry. They are arithmetic, not string matching: the stubs deliberately report a
// getBoundingClientRect that disagrees with the untransformed client box, which is exactly the
// condition the old code got wrong, and they assert on the numbers that come out.
//
// Run: node tests/label_transform.test.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

// A comment-stripped view: prose that NAMES a call is not a second call site. (This project has
// been bitten before by substring scans matching the very comments that explain the rule.)
// The split must tolerate CRLF: index.html uses it, and JS `.` does not match \r, so a
// line-comment regex anchored with $ would silently strip nothing.
const CODE = html.split(/\r?\n/).map(L => L.replace(/^\s*\/\/.*$/, "")).join("\n");

let passed = 0;
function test(name, fn) { fn(); passed++; console.log("  ok -", name); }

// ---------------------------------------------------------------------------------------------
// Extract the real block: the layout basis, the authoritative matrix, and the two projections.
// ---------------------------------------------------------------------------------------------
const START = "let PK = 1, POX = 0, POY = 0;";
const END = "const toVp = (x, y) =>";
const i0 = html.indexOf(START);
assert.ok(i0 > 0, "the label layout basis is no longer declared as expected");
const i1 = html.indexOf(END, i0);
assert.ok(i1 > i0, "the toVp projection is no longer declared as expected");
const BLOCK = html.slice(i0, html.indexOf("\n", i1) + 1);

// The block's only free names are the map's viewBox and the two DOM nodes it measures, so it can be
// executed directly with stubs for those. The factory is compiled ONCE, in one context, so the
// objects it returns are comparable across calls.
const FACTORY = vm.runInNewContext(
  "(function (holder, svg, vx, vy, vw, vh) {" + BLOCK + `
  return { captureGeom: captureGeom, captureCTM: captureCTM, projX: projX, projY: projY,
           toVp: toVp, basis: function () { return { PK: PK, POX: POX, POY: POY }; },
           ctm: function () { return CTM; } };
})`,
  { Math: Math }, { filename: "index.html:labelProjection" });
function build(stub) {
  return FACTORY(stub.holder, stub.svg, stub.vx, stub.vy, stub.vw, stub.vh);
}
const near = (a, b, eps) => Math.abs(a - b) <= (eps == null ? 1e-12 : eps);
function sameBasis(a, b, why) {
  assert.ok(near(a.PK, b.PK) && near(a.POX, b.POX) && near(a.POY, b.POY),
    why + " (" + JSON.stringify(a) + " vs " + JSON.stringify(b) + ")");
}

// A stub board. `clientWidth/clientHeight` are the UNTRANSFORMED layout box, which is what the CSS
// transform never touches. `rect` is what getBoundingClientRect reports, i.e. post-transform -- the
// value the pre-13C code mistakenly measured. They are deliberately inconsistent here.
function stubBoard(o) {
  o = o || {};
  const lw = o.lw == null ? 900 : o.lw, lh = o.lh == null ? 562 : o.lh;
  const s = o.s == null ? 1 : o.s, tx = o.tx || 0, ty = o.ty || 0;
  const hostLeft = o.hostLeft == null ? 40 : o.hostLeft, hostTop = o.hostTop == null ? 130 : o.hostTop;
  // the matrix a real browser reports for: viewBox fit (k, centred) then translate(tx,ty) scale(s)
  const vw = o.vw == null ? 1010 : o.vw, vh = o.vh == null ? 666 : o.vh;
  const vx = o.vx || 0, vy = o.vy || 0;
  const k = Math.min(lw / vw, lh / vh);
  const ox = (lw - vw * k) / 2, oy = (lh - vh * k) / 2;
  const m = { a: k * s, b: 0, c: 0, d: k * s,
              e: hostLeft + tx + (ox - vx * k) * s, f: hostTop + ty + (oy - vy * k) * s };
  m.inverse = function () { return m; };
  return {
    vx: vx, vy: vy, vw: vw, vh: vh, k: k, ox: ox, oy: oy, m: m, s: s, tx: tx, ty: ty,
    holder: {
      clientWidth: lw, clientHeight: lh,
      // post-transform box, as a browser reports it for a scaled child
      getBoundingClientRect: function () {
        return { left: hostLeft, top: hostTop, width: lw, height: lh,
                 right: hostLeft + lw, bottom: hostTop + lh };
      }
    },
    svg: {
      getScreenCTM: function () { return o.noCTM ? null : m; },
      // the transformed box -- reading THIS is the bug the phase fixed
      getBoundingClientRect: function () {
        return { left: hostLeft + tx, top: hostTop + ty, width: lw * s, height: lh * s,
                 right: hostLeft + tx + lw * s, bottom: hostTop + ty + lh * s };
      }
    }
  };
}

// ---------------------------------------------------------------------------------------------
// 1. The layout basis is a LAYOUT measurement, so the camera must not move it.
// ---------------------------------------------------------------------------------------------
test("the layout basis is measured from the untransformed box, not the transformed one", () => {
  const b = stubBoard({ s: 1 });
  const L = build(b);
  const got = L.basis();
  assert.ok(Math.abs(got.PK - b.k) < 1e-12,
    "PK should be the s=1 fit ratio " + b.k + ", got " + got.PK);
  assert.ok(Math.abs(got.POX - b.ox) < 1e-12 && Math.abs(got.POY - b.oy) < 1e-12,
    "POX/POY should be the letterbox offsets");
});

test("the layout basis is IDENTICAL at every camera scale (the s-squared regression)", () => {
  // Same layout, four cameras. The transformed rect the old code read differs by 8x between the
  // first and the last; the untransformed client box does not. If the basis ever tracks the camera
  // again, PK changes here and this fails.
  const seen = [1, 2, 8, 16].map(s => {
    const b = stubBoard({ s: s, tx: -160 * s, ty: -98 * s });
    const L = build(b);
    L.captureGeom();
    return L.basis();
  });
  seen.forEach((g, i) => {
    assert.ok(Math.abs(g.PK - seen[0].PK) < 1e-12,
      "PK moved with the camera: " + JSON.stringify(seen.map(x => x.PK)));
    assert.ok(Math.abs(g.POX - seen[0].POX) < 1e-12 && Math.abs(g.POY - seen[0].POY) < 1e-12,
      "the letterbox offset moved with the camera: " + JSON.stringify(seen));
  });
});

test("the layout basis is IDENTICAL at every pan (the doubled-tx regression)", () => {
  const a = stubBoard({ s: 4, tx: 0, ty: 0 }), aL = build(a);
  const c = stubBoard({ s: 4, tx: -900, ty: -400 }), cL = build(c);
  sameBasis(aL.basis(), cL.basis(),
    "panning changed the layout basis, so an offset is being counted twice");
});

test("cam.focusRect's input (toVp) is likewise camera-independent", () => {
  // focusRect is documented to take s=1 viewport units and apply the camera itself. If toVp were
  // camera-dependent the camera would be applied twice there too -- which is why "jump to Europe"
  // used to compute the wrong zoom as well as the wrong centre.
  const a = build(stubBoard({ s: 1 })), z = build(stubBoard({ s: 9, tx: -1200, ty: -700 }));
  const p1 = a.toVp(500, 300), p2 = z.toVp(500, 300);
  assert.ok(near(p1.x, p2.x) && near(p1.y, p2.y),
    "toVp moved with the camera, so focusRect is being fed camera-contaminated coordinates: " +
    JSON.stringify(p1) + " vs " + JSON.stringify(p2));
});

// ---------------------------------------------------------------------------------------------
// 2. The projection IS the browser's matrix -- not an approximation of it.
// ---------------------------------------------------------------------------------------------
test("projX/projY apply exactly the matrix the browser reports, in holder-relative px", () => {
  const b = stubBoard({ s: 3.7, tx: -410, ty: -260 });
  const L = build(b);
  L.captureCTM();
  const hostLeft = b.holder.getBoundingClientRect().left;
  const hostTop = b.holder.getBoundingClientRect().top;
  [[0, 0], [505, 333], [1010, 666], [-7.5, 912.25]].forEach(pt => {
    const wantX = b.m.a * pt[0] + b.m.c * pt[1] + b.m.e - hostLeft;
    const wantY = b.m.b * pt[0] + b.m.d * pt[1] + b.m.f - hostTop;
    assert.ok(Math.abs(L.projX(pt[0], pt[1]) - wantX) < 1e-9, "projX diverged from the matrix");
    assert.ok(Math.abs(L.projY(pt[0], pt[1]) - wantY) < 1e-9, "projY diverged from the matrix");
  });
});

test("a label's projected position round-trips back to its map anchor at every camera", () => {
  // This is the geographic-anchor invariant: inverse-transform the projected position and you must
  // get the map coordinate you started from, at any zoom and any pan.
  const ANCHOR = [297.9, 411.62];   // a real territory anchor (Saint Martin), in viewBox units
  [[1, 0, 0], [1.32, -157, -98], [4, -620, -390], [16, -3100, -1900]].forEach(cam => {
    const b = stubBoard({ s: cam[0], tx: cam[1], ty: cam[2] });
    const L = build(b);
    L.captureCTM();
    const hostLeft = b.holder.getBoundingClientRect().left;
    const hostTop = b.holder.getBoundingClientRect().top;
    const sx = L.projX(ANCHOR[0], ANCHOR[1]) + hostLeft;
    const sy = L.projY(ANCHOR[0], ANCHOR[1]) + hostTop;
    // invert the (axis-aligned) matrix by hand: the point must come back unchanged
    const backX = (sx - b.m.e) / b.m.a, backY = (sy - b.m.f) / b.m.d;
    assert.ok(Math.abs(backX - ANCHOR[0]) < 1e-6 && Math.abs(backY - ANCHOR[1]) < 1e-6,
      "anchor moved at s=" + cam[0] + ": " + backX + "," + backY);
  });
});

test("the projection has no missing CTM fallback that would silently park labels", () => {
  const b = stubBoard({ noCTM: true });
  const L = build(b);
  L.captureCTM();
  assert.strictEqual(L.ctm(), null, "an unavailable matrix must be reported as null, not guessed at");
});

// ---------------------------------------------------------------------------------------------
// 3. A resize must re-measure the basis (12C wanted this; 13C makes it safe at any camera).
// ---------------------------------------------------------------------------------------------
test("captureGeom re-measures after a resize, at any camera position", () => {
  const b = stubBoard({ s: 6, tx: -800, ty: -500 });
  const L = build(b);
  const before = L.basis();
  b.holder.clientWidth = 390; b.holder.clientHeight = 355;   // phone breakpoint
  L.captureGeom();
  const after = L.basis();
  assert.ok(after.PK < before.PK, "a narrower viewport must reduce the fit ratio");
  assert.ok(Math.abs(after.PK - Math.min(390 / b.vw, 355 / b.vh)) < 1e-12,
    "the re-measured ratio should be the new box's fit ratio");
});

// ---------------------------------------------------------------------------------------------
// 4. There is exactly ONE camera transform in the source, and the label position never consults
//    the camera scalars. (Absence cannot be measured arithmetically, so these are structural.)
// ---------------------------------------------------------------------------------------------

test("the label position is computed from the matrix, never from s/tx/ty", () => {
  const i = html.indexOf("const cands = markerSpecs.map(L => {");
  assert.ok(i > 0, "the label candidate builder moved");
  const body = html.slice(i, html.indexOf("placeMapLabels(cands", i));
  assert.ok(/projX\(L\.cx, L\.cy\)/.test(body) && /projY\(L\.cx, L\.cy\)/.test(body),
    "labels must be positioned through the authoritative matrix");
  // the pre-13C formula, in any of its shapes
  assert.ok(!/\bPK\s*\*\s*s\b/.test(body), "PK * s is the doubled-scale bug");
  assert.ok(!/(POX|POY)\s*\+\s*t[xy]/.test(body), "POX + tx is the doubled-pan bug");
  assert.ok(!/\bfx\s*=\s*[^;]*\bs\b/.test(body.replace(/projX|projY/g, "")),
    "the label x must not be a function of the camera scale");
});

test("only the projection reads getScreenCTM, and nothing else re-applies the camera to a point", () => {
  const calls = CODE.match(/getScreenCTM\(\)/g) || [];
  assert.strictEqual(calls.length, 1,
    "there should be exactly one authoritative matrix read, found " + calls.length);
  // geoOffScreen used to re-apply the camera by hand on top of toVp()
  const i = html.indexOf("geoOffScreen = function");
  const body = html.slice(i, html.indexOf("};", html.indexOf("return sx <", i)));
  assert.ok(/projX\(/.test(body) && /projY\(/.test(body),
    "geoOffScreen must use the same projection as the labels");
  assert.ok(!/t[xy]\s*\+\s*c\.[xy]\s*\*\s*st\.s/.test(body),
    "geoOffScreen must not maintain a second camera formula");
});

test("a camera update only moves labels; it never rebuilds the map", () => {
  const i = html.indexOf("relayoutLabels = function (s, tx, ty)");
  assert.ok(i > 0, "relayoutLabels moved");
  const body = html.slice(i, html.indexOf("_geoResel = function", i));
  ["innerHTML", "appendChild", "removeChild", "createElementNS", "createElement", "fetch(",
   "setAttribute(\"d\"", "getBBox("].forEach(bad => {
    assert.ok(body.indexOf(bad) < 0,
      "a camera update must not " + bad + " -- that is a redraw, not a reposition");
  });
  assert.ok(/style\.left/.test(body) && /style\.top/.test(body) && /style\.display/.test(body),
    "a camera update should set position and visibility only");
});

test("the label pill is centred by a SCREEN-space transform the camera cannot scale", () => {
  // The anchor is projected; the pill is then centred on it in CSS. That offset is screen-space and
  // must stay a plain translate -- if it were expressed in map units the camera would multiply it.
  const css = html.slice(html.indexOf(".geo-lab {"), html.indexOf(".geo-lab {") + 400);
  assert.ok(/transform:\s*translate\(-50%,\s*-50%\)/.test(css),
    "the pill centring should be translate(-50%, -50%), a screen-space translation");
  assert.ok(!/scale\(/.test(css), "the pill must not carry a scale of its own");
});

test("the semantic-zoom band is derived from the camera scale and drives presentation only", () => {
  const i = html.indexOf("holder.dataset.zoom =");
  assert.ok(i > 0, "the zoom band assignment moved");
  const line = html.slice(i, html.indexOf("\n", i));
  assert.ok(/s\s*<\s*2/.test(line) && /s\s*<\s*4\.2/.test(line),
    "the far/mid/near thresholds should still be 2 and 4.2: " + line.trim());
  // the band reaches the label layer only as placeMapLabels' zoom argument, i.e. as a filter
  const rl = html.indexOf("relayoutLabels(s, tx, ty);");
  assert.ok(rl > i, "the band is set before the labels are re-placed");
});

// ---------------------------------------------------------------------------------------------
// 5. Semantic zoom changes visibility, never the anchor -- executed against the real filter.
// ---------------------------------------------------------------------------------------------
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
const pctx = {};
vm.runInNewContext(extractFn(html, "rectsOverlap") + "\n" + extractFn(html, "placeMapLabels") +
  "\nthis.placeMapLabels = placeMapLabels;", pctx);

test("changing the zoom band changes .visible only -- never fx, fy or the collision box", () => {
  const mk = (i) => ({ fx: 100 + i * 37, fy: 60 + i * 23, priority: i,
    minZoom: i, maxZoom: Infinity, selected: false,
    box: { x0: 100 + i * 37 - 20, y0: 60 + i * 23 - 10, x1: 100 + i * 37 + 20, y1: 60 + i * 23 + 10 } });
  const cands = [0, 1, 2, 3, 4, 5, 6, 7].map(mk);
  const snap = () => cands.map(c => [c.fx, c.fy, c.box.x0, c.box.y0, c.box.x1, c.box.y1].join(","));
  const before = snap();
  const visAt = z => { pctx.placeMapLabels(cands, z); return cands.map(c => c.visible ? 1 : 0).join(""); };
  const v1 = visAt(1), v4 = visAt(4), v9 = visAt(9);
  assert.deepStrictEqual(snap(), before,
    "the zoom filter moved a label's anchor or box; it may only change visibility");
  assert.notStrictEqual(v1, v9, "a higher zoom should admit more labels");
  assert.ok(v9.split("1").length >= v4.split("1").length &&
            v4.split("1").length >= v1.split("1").length,
    "label density should not fall as the camera zooms in: " + v1 + " / " + v4 + " / " + v9);
});

test("the selected label survives its zoom band and keeps its anchor", () => {
  const sel = { fx: 250, fy: 140, priority: 0, minZoom: 12, maxZoom: Infinity, selected: true,
                box: { x0: 230, y0: 130, x1: 270, y1: 150 } };
  const before = [sel.fx, sel.fy];
  pctx.placeMapLabels([sel], 1);
  assert.strictEqual(sel.visible, true, "a selected label must stay visible below its band");
  assert.deepStrictEqual([sel.fx, sel.fy], before, "making a label visible must not move it");
});

console.log("\nAll " + passed + " label-transform checks passed.");
