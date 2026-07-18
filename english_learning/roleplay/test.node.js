/* Node runner for the role-play test suite (no browser needed).
   Usage:  node roleplay/test.node.js
   Shims `window`, loads the browser modules in a shared VM context, loads the
   scenario JSON from disk, and runs RP.runTests. Exits non-zero on any failure. */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const HERE = __dirname;
const ctx = { console };
ctx.window = ctx;            // modules do (function(g){...})(window)
ctx.globalThis = ctx;
vm.createContext(ctx);

for (const f of ["classifier.js", "engine.js", "tests.js"]) {
  const code = fs.readFileSync(path.join(HERE, f), "utf8");
  vm.runInContext(code, ctx, { filename: f });
}

const graph = JSON.parse(fs.readFileSync(path.join(HERE, "scenarios", "restaurant.json"), "utf8"));

ctx.RP.runTests(graph).then((res) => {
  for (const c of res.cases) {
    console.log((c.ok ? "  PASS " : "  FAIL ") + c.name + (c.detail ? "   [" + c.detail + "]" : ""));
  }
  console.log("\n" + res.passed + " / " + res.total + " passed");
  process.exit(res.passed === res.total ? 0 : 1);
});
