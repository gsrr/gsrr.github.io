/* Phase 9E.2 — the client renders exactly the activities the REGISTRY declares for a lesson.
 *
 *   node tests/activity_catalog.test.js
 *
 * Two invariants, both derived — neither is a curriculum census:
 *
 *  1. RENDERER COVERAGE. Every activity type the registry declares must have a tab that can present
 *     it. Without this a registry could require an activity the UI silently cannot show, which would
 *     make mastery unreachable. (A type census is fine here: it describes renderer capability, not
 *     how many lessons exist.)
 *
 *  2. NO SECOND CURRICULUM SCHEMA. The lesson player must decide availability from the registry, not
 *     by sniffing the content file. Before 9E.2 it toggled tabs on `content.reorder`, `content.wh`,
 *     `content.dictation`, `content.cloze` and the dialogue length — a second shape authority that
 *     disagreed with the registry for every A1 lesson.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const registry = JSON.parse(fs.readFileSync(path.join(ROOT, 'learning', 'registry.json'), 'utf8'));

let passed = 0;
const ok = n => { passed++; console.log('  ok - ' + n); };
const assert = (c, m) => { if (!c) { console.error('  FAIL - ' + m); process.exit(1); } };

// strip // comments so prose describing the OLD behaviour never satisfies a check
const code = html.split('\n').map(l => l.replace(/\/\/.*/, '')).join('\n');

// ---------- 1. the tab -> activity type map exists and is the only client curriculum knowledge ----
const mapMatch = code.match(/const TAB_ACTIVITY_TYPE = \{([\s\S]*?)\};/);
assert(mapMatch, 'TAB_ACTIVITY_TYPE map not found in index.html');
const mapped = {};
mapMatch[1].replace(/"(\d+)":\s*"([a-z0-9_]+)"/g, (_, lvl, type) => { mapped[type] = lvl; return ''; });
assert(Object.keys(mapped).length >= 9, 'TAB_ACTIVITY_TYPE should map at least the 9 known types, got '
  + JSON.stringify(mapped));
ok('1. TAB_ACTIVITY_TYPE maps ' + Object.keys(mapped).length + ' activity types to tabs: '
   + Object.keys(mapped).sort().join(', '));

// ---------- 2. RENDERER COVERAGE: every registry activity type has a tab ----------
const types = new Set();
for (const aid of Object.keys(registry.activities)) types.add(aid.slice(aid.lastIndexOf('.') + 1));
const uncovered = [...types].filter(t => !mapped[t]).sort();
assert(uncovered.length === 0,
  'registry declares activity type(s) with NO client renderer/tab: ' + JSON.stringify(uncovered)
  + ' — a required activity of that type could never be completed');
ok('2. renderer coverage: every registry activity type (' + [...types].sort().join(', ')
   + ') has a presenting tab');

// ---------- 3. availability is registry-driven, not content-sniffed ----------
assert(/function applyRegistryTabs\(/.test(code), 'applyRegistryTabs() must exist');
assert(/function registeredActivityTypes\(/.test(code), 'registeredActivityTypes() must exist');
assert(/applyRegistryTabs\(article\.file\)/.test(code),
  'the lesson player must call applyRegistryTabs(article.file) when opening a lesson');
ok('3. the lesson player derives tab availability from applyRegistryTabs()/registeredActivityTypes()');

// the retired content sniffs must be gone from executable code
const SNIFFS = [
  ['hasReorder', /hasReorder/],
  ['hasWh', /hasWh/],
  ['hasDict', /hasDict/],
  ['hasCloze', /hasCloze/],
  ['dialogue-length role-play gate', /toggle\("hidden",\s*!\(script && script\.length/],
];
SNIFFS.forEach(([name, re]) => assert(!re.test(code),
  'content-sniffing tab visibility survives in executable code: ' + name));
ok('4. all five content-sniffing visibility branches are gone (reorder/wh/dictation/cloze/dialogue)');

// ---------- 5. no course- or lesson-specific branch decides availability ----------
['prea1.core', 'a1.core', 'prea1.taipei'].forEach(cid => assert(!code.includes(cid),
  'the client must not branch on course id ' + cid));
ok('5. no course-specific or lesson-specific availability branch exists in the client');

// ---------- 6. registered != required: the client must not treat catalog as the denominator ------
// Mastery progress is the server row's requiredActivityIds; the tab strip is presentation only.
assert(/requiredActivityIds/.test(code), 'progress must read requiredActivityIds from the server row');
assert(!/TAB_ACTIVITY_TYPE[\s\S]{0,400}requiredActivityIds/.test(mapMatch[0]),
  'the tab map must not participate in computing required activities');
ok('6. mastery progress still reads the server row requiredActivityIds; the tab map is presentation only');

// ---------- 7. per-family expectation, derived from the registry itself ----------
const byLesson = {};
for (const [aid, spec] of Object.entries(registry.activities)) {
  (byLesson[spec.lessonId] = byLesson[spec.lessonId] || []).push(aid.slice(aid.lastIndexOf('.') + 1));
}
const sample = {
  'english.prea1.core.005': 7,
  'english.prea1.taipei.zoo': 7,
  'english.a1.core.002': 9,
};
for (const [lid, n] of Object.entries(sample)) {
  assert(byLesson[lid] && byLesson[lid].length === n,
    lid + ' should declare ' + n + ' activities, got ' + (byLesson[lid] || []).length);
  byLesson[lid].forEach(t => assert(mapped[t], lid + ' declares un-renderable type ' + t));
}
const a1 = byLesson['english.a1.core.002'].sort();
['quiz4', 'wh', 'cloze', 'roleplay'].forEach(t => assert(a1.includes(t),
  'A1 must KEEP its existing practice activity ' + t + ' (9E.2 must not remove learner content)'));
const req = registry.lessons['english.a1.core.002'].completionPolicy.requiredActivityIds;
assert(req.length === 5, 'A1 mastery must still require exactly 5 activities, got ' + req.length);
ok('7. Pre-A1 7 / Taipei 7 / A1 9 declared activities, all renderable; A1 keeps quiz4+wh+cloze+'
   + 'roleplay while mastery still requires 5');

console.log('\nAll ' + passed + ' activity-catalog tests passed.');
