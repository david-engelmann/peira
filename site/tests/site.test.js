/* JSDOM tests for site/src/scripts/site.js.
   B1: locks in the two hard display requirements against mock data.
   1. Public and Holdout suites are never blended in any view.
   2. Leaderboard ranks count ranking-eligible runs only, densely.
   B2: locks in the division requirements (docs/Admission-Rules.md).
   3. The guardrail division and the LLM baseline division are shown
      side by side, but the headline ranking never mixes them: every
      rank is dense within its own division.
   Run: node --test tests/site.test.js (from site/) */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SITE_JS = fs.readFileSync(path.join(__dirname, '..', 'src', 'scripts', 'site.js'), 'utf8');

/* Small hand-built site-data payload: two suites, two divisions, eligible
   and ineligible runs, so the tests can tell blending apart. epsilon has
   the best ASR of any public run but sits in the LLM baseline division:
   the guardrail headline ranking must never borrow it. */
const RUNS = [
  {
    adapter_name: 'mock-alpha', adapter_version: '1', model_class: 'guardrail',
    division: 'guardrail', suite: 'public',
    metrics: { asr_conditional: 0.2, asr_ci95: [0.1, 0.3], benign_accuracy: 0.9,
      benign_accuracy_ci95: [0.85, 0.95], n_eligible: 100, ranking_eligible: true,
      eligibility_notes: [], per_family: {} },
  },
  {
    adapter_name: 'mock-beta', adapter_version: '1', model_class: 'guardrail',
    division: 'guardrail', suite: 'public',
    metrics: { asr_conditional: 0.1, asr_ci95: [0.05, 0.2], benign_accuracy: 0.95,
      benign_accuracy_ci95: [0.9, 0.99], n_eligible: 100, ranking_eligible: false,
      eligibility_notes: ['gate failed'], per_family: {} },
  },
  {
    adapter_name: 'mock-gamma', adapter_version: '1', model_class: 'guardrail',
    division: 'guardrail', suite: 'public',
    metrics: { asr_conditional: 0.3, asr_ci95: [0.2, 0.4], benign_accuracy: 0.85,
      benign_accuracy_ci95: [0.8, 0.9], n_eligible: 100, ranking_eligible: true,
      eligibility_notes: [], per_family: {} },
  },
  {
    adapter_name: 'mock-epsilon', adapter_version: '1', model_class: 'llm-baseline',
    division: 'llm-baseline', suite: 'public',
    metrics: { asr_conditional: 0.05, asr_ci95: [0.02, 0.1], benign_accuracy: 0.98,
      benign_accuracy_ci95: [0.95, 0.99], n_eligible: 100, ranking_eligible: true,
      eligibility_notes: [], per_family: {} },
  },
  {
    adapter_name: 'mock-delta', adapter_version: '1', model_class: 'guardrail',
    division: 'guardrail', suite: 'holdout',
    metrics: { asr_conditional: 0.5, asr_ci95: [0.4, 0.6], benign_accuracy: 0.8,
      benign_accuracy_ci95: [0.75, 0.85], n_eligible: 50, ranking_eligible: true,
      eligibility_notes: [], per_family: {} },
  },
];

const DATA = { schema_version: '2', mock_data: true, runs: RUNS };

const LEADERBOARD_HTML = `
  <script id="site-data" type="application/json">${JSON.stringify(DATA).replace(/</g, '\\u003c')}</script>
  <div data-page="leaderboard">
    <div class="controls">
      <div class="seg" data-suite-toggle role="group" aria-label="Result suite">
        <button type="button" data-suite="public">Public</button>
        <button type="button" data-suite="holdout">Holdout</button>
      </div>
      <div class="seg" data-division-toggle role="group" aria-label="Leaderboard division">
        <button type="button" data-division="both">Both divisions</button>
        <button type="button" data-division="guardrail">Guardrails</button>
        <button type="button" data-division="llm-baseline">LLM baselines</button>
      </div>
      <label><input type="checkbox" id="ineligible-filter" /> Hide runs that are not ranking eligible</label>
      <span class="count" id="board-count"></span>
    </div>
    <div class="table-scroll" id="board-wrap" aria-live="polite"></div>
    <div class="btn-row">
      <button class="btn" type="button" data-export="csv">Export CSV</button>
      <button class="btn" type="button" data-copylink>Copy link to this view</button>
    </div>
  </div>`;

function loadLeaderboard(query = '') {
  const dom = new JSDOM(`<!DOCTYPE html><html><body>${LEADERBOARD_HTML}</body></html>`, {
    url: 'https://peiratrial.dev/' + query,
    runScripts: 'outside-only',
  });
  dom.window.eval(SITE_JS);
  // site.js defers to DOMContentLoaded when the document is still loading.
  dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
  return dom;
}

const sections = (dom) =>
  [...dom.window.document.querySelectorAll('[data-division-section]')];
const sectionKeys = (dom) =>
  sections(dom).map((s) => s.dataset.divisionSection);
const rowsIn = (section) =>
  [...section.querySelectorAll('tbody tr')];
const rankCellsIn = (section) =>
  rowsIn(section).map((tr) => tr.querySelector('td.rank').textContent.trim());
const adapterNamesIn = (section) =>
  rowsIn(section).map((tr) => tr.querySelector('.adapter-name').textContent.trim());
const guardrailSection = (dom) =>
  sections(dom).find((s) => s.dataset.divisionSection === 'guardrail');
const baselineSection = (dom) =>
  sections(dom).find((s) => s.dataset.divisionSection === 'llm-baseline');

describe('leaderboard suite separation (never blended)', () => {
  it('public view shows only public runs', () => {
    const dom = loadLeaderboard('?suite=public');
    const names = sections(dom).flatMap(adapterNamesIn).sort();
    assert.deepEqual(names, ['alpha', 'beta', 'epsilon', 'gamma']);
  });

  it('holdout view shows only holdout runs', () => {
    const dom = loadLeaderboard('?suite=holdout');
    assert.deepEqual(adapterNamesIn(guardrailSection(dom)), ['delta']);
  });

  it('clicking the holdout toggle swaps the view without a reload', () => {
    const dom = loadLeaderboard('?suite=public');
    const btn = dom.window.document.querySelector('[data-suite="holdout"]');
    btn.click();
    assert.deepEqual(adapterNamesIn(guardrailSection(dom)), ['delta']);
    assert.ok(dom.window.location.search.includes('suite=holdout'));
  });

  it('CSV export for the holdout view carries only holdout rows', () => {
    const dom = loadLeaderboard('?suite=holdout');
    const root = dom.window.document.querySelector('[data-page="leaderboard"]');
    const csvRows = root.__csvRows();
    const suites = new Set(csvRows.slice(1).map((r) => r[4]));
    assert.deepEqual([...suites], ['holdout']);
  });
});

describe('leaderboard ranks', () => {
  it('ranks count eligible runs only, densely, when ineligible rows are shown', () => {
    // Guardrail table, sorted by ASR asc: beta (0.1, ineligible),
    // alpha (0.2, eligible), gamma (0.3, eligible). Eligible ranks must
    // be 1, 2, not 2, 3.
    const dom = loadLeaderboard('?suite=public');
    assert.deepEqual(rankCellsIn(guardrailSection(dom)), ['–', '1', '2']);
  });

  it('hiding ineligible rows keeps dense ranks', () => {
    const dom = loadLeaderboard('?suite=public&ineligible=hide');
    assert.deepEqual(rankCellsIn(guardrailSection(dom)), ['1', '2']);
    assert.deepEqual(adapterNamesIn(guardrailSection(dom)), ['alpha', 'gamma']);
  });
});

describe('leaderboard divisions (never mixed)', () => {
  it('default view shows both divisions side by side', () => {
    const dom = loadLeaderboard('?suite=public');
    assert.deepEqual(sectionKeys(dom), ['guardrail', 'llm-baseline']);
  });

  it('the headline ranking never mixes divisions', () => {
    // epsilon has the best ASR of any public run (0.05) but declares the
    // LLM baseline division. Guardrail rank 1 must be alpha (0.2), and
    // epsilon must rank 1 in its own division, not leak across.
    const dom = loadLeaderboard('?suite=public');
    assert.deepEqual(rankCellsIn(guardrailSection(dom)), ['–', '1', '2']);
    assert.deepEqual(adapterNamesIn(guardrailSection(dom)), ['beta', 'alpha', 'gamma']);
    assert.deepEqual(rankCellsIn(baselineSection(dom)), ['1']);
    assert.deepEqual(adapterNamesIn(baselineSection(dom)), ['epsilon']);
  });

  it('division filter shows one division only', () => {
    const dom = loadLeaderboard('?suite=public&division=guardrail');
    assert.deepEqual(sectionKeys(dom), ['guardrail']);
    const dom2 = loadLeaderboard('?suite=public&division=llm-baseline');
    assert.deepEqual(sectionKeys(dom2), ['llm-baseline']);
    assert.deepEqual(adapterNamesIn(baselineSection(dom2)), ['epsilon']);
  });

  it('clicking the division toggle swaps the view without a reload', () => {
    const dom = loadLeaderboard('?suite=public');
    const btn = dom.window.document.querySelector('[data-division="llm-baseline"]');
    btn.click();
    assert.deepEqual(sectionKeys(dom), ['llm-baseline']);
    assert.ok(dom.window.location.search.includes('division=llm-baseline'));
  });

  it('an unknown division falls back to both', () => {
    const dom = loadLeaderboard('?suite=public&division=bogus');
    assert.deepEqual(sectionKeys(dom), ['guardrail', 'llm-baseline']);
  });

  it('CSV export carries the division column and only the viewed divisions', () => {
    const dom = loadLeaderboard('?suite=public&division=guardrail');
    const root = dom.window.document.querySelector('[data-page="leaderboard"]');
    const csvRows = root.__csvRows();
    assert.equal(csvRows[0][0], 'division');
    const divisions = new Set(csvRows.slice(1).map((r) => r[0]));
    assert.deepEqual([...divisions], ['guardrail']);
  });

  it('CSV export for both divisions carries every viewed row with its division', () => {
    const dom = loadLeaderboard('?suite=public');
    const root = dom.window.document.querySelector('[data-page="leaderboard"]');
    const csvRows = root.__csvRows();
    const byAdapter = new Map(csvRows.slice(1).map((r) => [r[1], r[0]]));
    assert.equal(byAdapter.get('mock-epsilon'), 'llm-baseline');
    assert.equal(byAdapter.get('mock-alpha'), 'guardrail');
    assert.equal(csvRows.length - 1, 4);
  });
});
