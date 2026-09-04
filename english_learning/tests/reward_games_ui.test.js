// Phase 14A.10B — THE REWARD-GAME CLIENT: four interactions, one server decision.
//
//   node tests/reward_games_ui.test.js
//
// The server half (entitlement, assignment, prize, idempotency, Home Base credit) is pinned in
// tests/reward_games_test.py and must not be duplicated here. This file pins the CLIENT: that it
// opens the game the server assigned, that the four games are genuinely four different
// interactions, that every visible number comes from the server, and that nothing in the browser
// can name or influence a prize.
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

const mod = slice("let rgPrizes = null;", "function launchAttack(", "reward game module");
const wheel = slice("function rgWheel(ent, prizes) {", "function rgChests(", "wheel");
const chests = slice("function rgChests(ent, prizes) {", "function rgTarget(", "chests");
const target = slice("function rgTarget(ent, prizes) {", "function rgDice(", "target");
const dice = slice("function rgDice(ent, prizes) {", "const RG_GAMES", "dice");
const result = slice("function rgResult(res) {", "function rgWheel(", "result");

// ===================== assignment routes to the right game =====================
assert(/const RG_GAMES = \{ lucky_wheel: rgWheel, treasure_chests: rgChests,\s*target_shot: rgTarget, dice_roll: rgDice \};/.test(code),
  "the four assigned game ids map to four renderers");
assert(/const fn = RG_GAMES\[ent\.game\];/.test(mod),
  "the game opened is the one the ENTITLEMENT names");
assert(/if \(!fn \|\| !prizes\.length\) return;/.test(mod),
  "an unknown game is refused, never guessed at");
assert(mod.indexOf("Math.random() < 0.25") < 0 && !/RG_GAMES\[Math/.test(mod),
  "the client never picks a game for itself");
ok("assignment: the server's `game` selects the renderer; the client neither chooses nor guesses " +
   "one");

// ===================== all four render, and differ =====================
assert(/class="rg-wheel"/.test(wheel) && /conic-gradient\(/.test(wheel) &&
       /style\.transform = "rotate\(/.test(wheel), "Lucky Wheel is a rotating wheel");
assert(/data-chest="' \+ i \+/.test(chests) && /\[0, 1, 2\]\.map/.test(chests) &&
       /classList\.add\("rg-open"\)/.test(chests), "Treasure Chests is three chests, one opens");
assert(/setInterval\(/.test(target) && /aim\.style\.left = x \+ "%"/.test(target) &&
       /clearInterval/.test(target), "Target Shot is a timing interaction against a moving aim");
assert(/classList\.add\("rg-tumble"\)/.test(dice) && /FACES\[\(n\+\+\) % 6\]/.test(dice),
  "Dice Roll tumbles a die");
const centres = [wheel, chests, target, dice].map(s =>
  (s.match(/rg-wheel|rg-chest|rg-aim|rg-die/g) || [])[0]);
assert(new Set(centres).size === 4, "the four central interactions are genuinely different");
assert(/\.rg-card|\.rg-stage/.test(html) && (mod.match(/function rgShell\(/g) || []).length === 1,
  "...while sharing ONE shell");
assert((code.match(/function rgResult\(/g) || []).length === 1, "...and ONE result treatment");
ok("all four mini-games render, each with its own interaction (spin / choose / time / roll), " +
   "inside one shared shell and one shared result screen");

// ===================== every displayed value is the server's =====================
assert(/fetch\(withRoom\("\/api\/learning\/rewards\?token="/.test(mod),
  "the prize table is fetched from the server");
assert(/rgPrizes = j\.prizes \|\| \[\];/.test(mod), "...and is what the games render");
assert(/prizes\.map\(\(p, i\) =>/.test(mod) && /escapeHtml\(rgLabel\(p\)\)/.test(mod),
  "the legend is built from that table, not from literals");
assert(code.indexOf("3,000 Gold") < 0 && code.indexOf("670 Infantry") < 0 &&
       code.indexOf("420 Archers") < 0 && code.indexOf("400 Cavalry") < 0,
  "no prize label or amount is hard-coded in the client");
assert(/const p = res\.prize \|\| \{\};/.test(result) && /rgLabel\(p\)/.test(result),
  "the result screen shows the SERVER's prize");
ok("every reward value on screen -- the wheel legend, the chest reveal, the result -- comes from " +
   "the server's own table and response; the client hard-codes no prize");

// ===================== the client cannot influence the outcome =====================
const post = slice("function rgPlay(id, extra, cb) {", "function rgResult(", "rgPlay");
assert(/const body = Object\.assign\(\{ id: id \}, extra \|\| \{\}\);/.test(post),
  "the request carries the entitlement id and presentation data only");
assert(!/reward|prize|gold|troop|unit/i.test(post.split("const body")[1].split("fetch")[0]),
  "nothing reward-shaped is assembled into the payload");
assert(chests.indexOf("chestIndex: parseInt(bt.dataset.chest, 10)") > 0,
  "the chest index is the only interaction datum sent");
assert(target.indexOf("rgPlay(ent.id, null,") > 0 && wheel.indexOf("rgPlay(ent.id, null,") > 0 &&
       dice.indexOf("rgPlay(ent.id, null,") > 0,
  "the wheel, the shot and the die send no interaction data at all");
assert(!/score|accuracy|angle|face/.test(post), "no score, angle or die face is ever posted");
assert(/const idx = Math\.max\(0, prizes\.findIndex\(p => p\.id === \(res\.prize \|\| \{\}\)\.id\)\);/.test(wheel),
  "the wheel's landing segment is DERIVED from the server result");
assert(/die\.textContent = FACES\[Math\.floor\(Math\.random\(\) \* 6\)\];/.test(dice) &&
       /cosmetic only/.test(html), "the die face is explicitly cosmetic");
ok("security: the browser sends an entitlement id and, for the chests, which chest was tapped -- " +
   "never a prize, a score, an angle or a die face. The wheel is TOLD where to stop");

// ===================== every game wins =====================
assert(!/rg-empty|Try again|no reward|better luck|MISS/i.test(mod),
  "there is no losing state anywhere in the reward games");
assert(/YOU WON!/.test(result), "the result always announces a win");
assert(/Every chest holds a prize|every shot wins|every roll wins|Every segment is a prize/i.test(mod),
  "and the copy says so before the player commits");
ok("every game wins: no empty chest, no miss, no blank segment, no bad roll -- and the copy " +
   "promises that up front");

// ===================== the result, and both exits =====================
assert(/Added to \\u\{1F3E0\} Home Base/.test(result), "a troop prize says where it went");
assert(/id="rgMore">\\u\{1F4DA\} CONTINUE LEARNING/.test(result) &&
       /id="rgWorld">\\u\{1F5FA\}\\u\{FE0F\} GO TO WORLD/.test(result), "both exits are offered");
assert(/rgOpenNextPending\(function \(opened\) \{ if \(!opened\) openLearningHome\(\); \}\);/.test(result),
  "CONTINUE LEARNING opens the NEXT pending game if there is one, so claiming one never " +
  "discards another");
assert(/goToGameMap\(\);/.test(result), "GO TO WORLD uses the existing World route");
assert(/loadEconomy\(function \(\) \{ loadTerritory\(function \(\) \{ renderEmpire\(\); refreshMap\(\); \}\); \}\);/
  .test(result), "...after reconciling the caches, so won troops are on screen immediately");
ok("the result screen names the prize, says troops went to Home Base, and both exits work -- " +
   "Continue Learning even picks up a second pending game");

// ===================== auto-open and Academy re-entry =====================
assert(/if \(j && j\.rewardGame && typeof openRewardGame === "function"\) \{/.test(code),
  "a NEW pass opens its game immediately, inside the learning flow");
assert(/"rewardGame": game_now/.test(fs.readFileSync(path.join(__dirname, "..", "server.py"), "utf8")),
  "...from the field the server sets only when it just created one");
assert(/id="acRewardReady" hidden/.test(code) && /id="acRewardPlay"/.test(code),
  "the Academy carries a reward-ready banner");
assert(/box2\.hidden = n < 1;/.test(code) && /n > 1 \? \("Rewards ready: " \+ n\)/.test(code),
  "...shown only when something is pending, and counting more than one");
assert(/btn\.addEventListener\("click", function \(\) \{ rgOpenNextPending\(function \(\) \{\}\); \}\);/.test(code),
  "PLAY NOW opens the oldest pending game");
assert(/if \(j\.next\) \{ openRewardGame\(j\.next\); if \(cb\) cb\(true\); \}/.test(mod),
  "`next` is the server's oldest-first choice, not a client sort");
ok("auto-open after a new pass, and a persistent Academy banner that opens the oldest pending " +
   "game -- a reward can never be lost behind navigation");

// ===================== no stale pass-gold promise =====================
assert(code.indexOf("Pass the quiz +") < 0, "the old direct pass-gold promise is gone");
assert(/'<span class="ac-rw">Pass a quiz \\u2192 \\u\{1F381\} reward game'/.test(code),
  "the Academy now promises a reward game for a pass");
assert(/\(ec\.masteryGold \? ' \\u00b7 master the lesson \+' \+ ec\.masteryGold \+ ' Gold' : ''\)/.test(code),
  "...and still states mastery's own gold, from the server's figure");
assert(/once per lesson, not per replay/.test(code), "and that both are first-time only");
ok("no stale '+500 pass gold' promise survives: the Academy advertises a reward game for a pass " +
   "and the server's own mastery figure");

// ===================== accessibility / input =====================
assert(/aria-label="Open treasure chest ' \+ \(i \+ 1\)/.test(chests), "chests are labelled");
assert(/:focus-visible/.test(html.slice(html.indexOf(".rg-go"), html.indexOf(".rg-wheel-wrap"))),
  "the primary action has a visible focus ring");
assert(!/mouseover|mouseenter|contextmenu|dblclick/.test(mod),
  "no hover, right-click or double-click is required");
assert(/\.rg-chest \{ width: 96px; height: 96px/.test(html) && /padding: 14px 34px/.test(html),
  "the primary targets are large");
assert(/rg-dest|rg-prize/.test(result), "the reward is announced in TEXT, not only by animation");
ok("input and accessibility: plain click/tap, large targets, visible focus, and the prize is " +
   "always stated in words as well as shown");

console.log("\nAll " + passed + " reward-game UI checks passed.");
