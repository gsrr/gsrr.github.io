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

// ---------- 8. Phase 9H: tab copy names the ACTIVITY, never a "Level N" ordinal ----------
// The ordinal was misleading twice over: it is a tab POSITION, not a curriculum level (Pre-A1 has no
// Reorder, so the same activity sat at different numbers in different families), and it duplicated the
// number already rendered in .lvl on the tab itself. The number is still there; only the copy changed.
const TAB_LABEL = {};
const tabRe = /<div class="levelTab[^"]*"\s+data-level="(\d+)"\s+data-name="([^"]*)"/g;
let m;
while ((m = tabRe.exec(html)) !== null) TAB_LABEL[m[1]] = m[2];
assert(Object.keys(TAB_LABEL).length === 10,
  'expected 10 tab definitions, found ' + Object.keys(TAB_LABEL).length);
Object.entries(TAB_LABEL).forEach(([lvl, name]) => assert(!/Level\s*\d/.test(name),
  'tab ' + lvl + ' still carries "Level N" copy: ' + JSON.stringify(name)));
assert(!/dataset\.name\s*=\s*"Level "/.test(code),
  'renumberTabs() must not rewrite data-name back into "Level <pos> · ..."');
assert(/lvlSpan\.textContent = pos/.test(code),
  'renumberTabs() must still renumber the visible .lvl position');
ok('8. all 10 activity tabs are labelled by activity, with no "Level N" ordinal, while .lvl still '
   + 'carries the position');

// each tab's label must name the activity TYPE it renders, so the copy cannot drift from the routing
const EXPECT_LABEL = { read_along: 'Read Along', quiz3: 'Quiz', quiz4: 'Tricky Quiz',
                       matching: 'Matching', reorder: 'Reorder', wh: 'WH Questions',
                       dictation: 'Dictation', cloze: 'Fill in the Blank', roleplay: 'Role-play' };
Object.entries(mapped).forEach(([type, lvl]) => {
  const want = EXPECT_LABEL[type];
  assert(want, 'no expected label for activity type ' + type);
  assert((TAB_LABEL[lvl] || '').indexOf(want) === 0,
    'tab ' + lvl + ' renders ' + type + ' but is labelled ' + JSON.stringify(TAB_LABEL[lvl]));
});
const labels = Object.values(TAB_LABEL);
assert(new Set(labels).size === labels.length, 'tab labels must be unique: ' + labels.join(' | '));
ok('9. every tab label names the activity type it renders, and no two tabs share a label');

// ---------- 10. Phase 9H: the lesson header is the OPENED lesson's identity ----------
// It used to read manifest.levels[selLevelIdx].name -- the level last BROWSED. Learning Home never
// sets selLevelIdx, so every lesson opened from Home inherited a stale family (A1/002 rendered
// "Pre-A1 · 002 · My Weekend"). lessonTitleOf() takes the title from the authoritative progress row.
assert(/learnTitle\.textContent = lessonTitleOf\(a\.file\)/.test(code),
  'selectArticle() must set the header from lessonTitleOf(a.file)');
assert(!/learnTitle\.textContent = \(manifest\.levels\[selLevelIdx\]/.test(code),
  'the header must not derive from selLevelIdx (the level last browsed)');
assert(/function lessonTitleOf\(/.test(code) && /progressForContent\(contentPath\)/.test(code),
  'lessonTitleOf() must resolve identity through the authoritative progress row');
ok('10. the lesson header derives from the opened lesson, not from the previously browsed level');

// ---------- 11. Phase 9H: "Campaign" is earned by qualification grants, not hard-coded ----------
// A course whose lessons GRANT QUALIFICATIONS unlocks territory, so "campaign" is accurate for it.
// Every other course unlocks nothing in the world and is a "Course". Derived from `grants`, which the
// public registry view already sends -- a second qualification-bearing course needs no code change.
assert(/function courseIsCampaign\(/.test(code) && /function courseKindLabel\(/.test(code),
  'courseIsCampaign()/courseKindLabel() must exist');
const kindFn = code.slice(code.indexOf('function courseIsCampaign('),
                          code.indexOf('function homeCampaigns('));
assert(/grants/.test(kindFn), 'courseIsCampaign() must decide from qualification grants');
assert(!/english\.prea1\.taipei|taipei/i.test(kindFn),
  'courseIsCampaign() must not name a course id -- the rule has to be data-driven');
assert(!/' Campaign<\/div>'|" Campaign<\/div>"/.test(code),
  'the Home course heading must use courseKindLabel(), not a literal " Campaign"');
assert(!/"\u{1F3C6} Campaign Complete"/u.test(code),
  'the completion banner must use courseKindLabel(), not a literal "Campaign Complete"');
assert(/courseKindLabel\(c\.cid\)/.test(code), 'the Home card must label its own course kind');
// and the registry must still back that rule: exactly one course grants qualifications
const grantCourses = new Set();
for (const [aid, spec] of Object.entries(registry.activities)) {
  const g = spec.grants || (registry.qualifications[aid] ? [aid] : []);
  const lid = spec.lessonId;
  const declared = Object.keys(registry.qualifications).some(q => q === aid || q.indexOf(aid) === 0);
  if ((g && g.length) || declared) grantCourses.add(registry.lessons[lid].courseId);
}
assert(grantCourses.size === 1 && grantCourses.has('english.prea1.taipei'),
  'exactly one course should grant qualifications, got ' + [...grantCourses].join(','));
ok('11. "Campaign" is derived from qualification grants (Taipei only); every other course is a '
   + '"Course", with no course id hard-coded in the client');

console.log('\nAll ' + passed + ' activity-catalog tests passed.');
