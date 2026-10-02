/* JSDOM tests for site/src/scripts/site.js.
   B1: locks in the two hard display requirements against mock data.
   1. Public and Holdout suites are never blended in any view.
   2. Leaderboard ranks count ranking-eligible runs only, densely.
   Run: node --test tests/site.test.js (from site/) */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SITE_JS = fs.readFileSync(path.join(__dirname, '..', 'src', 'scripts', 'site.js'), 'utf8');

/* Small hand-built site-data payload: two suites, eligible and
   ineligible runs, so the tests can tell blending apart. */
const RUNS = [
  {
    adapter_name: 'mock-alpha', adapter_version: '1', model_class: 'guardrail',
    suite: 'public',
    metrics: { asr_conditional: 0.2, asr_ci95: [0.1, 0.3], benign_accuracy: 0.9,
      benign_accuracy_ci95: [0.85, 0.95], n_eligible: 100, ranking_eligible: true,
      eligibility_notes: [], per_family: {} },
  },
  {
    adapter_name: 'mock-beta', adapter_version: '1', model_class: 'guardrail',
    suite: 'public',
    metrics: { asr_conditional: 0.1, asr_ci95: [0.05, 0.2], benign_accuracy: 0.95,
      benign_accuracy_ci95: [0.9, 0.99], n_eligible: 100, ranking_eligible: false,
      eligibility_notes: ['gate failed'], per_family: {} },
  },
  {
    adapter_name: 'mock-gamma', adapter_version: '1', model_class: 'guardrail',
    suite: 'public',
    metrics: { asr_conditional: 0.3, asr_ci95: [0.2, 0.4], benign_accuracy: 0.85,
      benign_accuracy_ci95: [0.8, 0.9], n_eligible: 100, ranking_eligible: true,
      eligibility_notes: [], per_family: {} },
  },
  {
    adapter_name: 'mock-delta', adapter_version: '1', model_class: 'guardrail',
    suite: 'holdout',
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

const rows = (dom) =>
  [...dom.window.document.querySelectorAll('#board-wrap tbody tr')];
const rankCells = (dom) =>
  rows(dom).map((tr) => tr.querySelector('td.rank').textContent.trim());
const adapterNames = (dom) =>
  rows(dom).map((tr) => tr.querySelector('.adapter-name').textContent.trim());

describe('leaderboard suite separation (never blended)', () => {
  it('public view shows only public runs', () => {
    const dom = loadLeaderboard('?suite=public');
    assert.deepEqual(adapterNames(dom).sort(), ['alpha', 'beta', 'gamma']);
  });

  it('holdout view shows only holdout runs', () => {
    const dom = loadLeaderboard('?suite=holdout');
    assert.deepEqual(adapterNames(dom), ['delta']);
  });

  it('clicking the holdout toggle swaps the view without a reload', () => {
    const dom = loadLeaderboard('?suite=public');
    const btn = dom.window.document.querySelector('[data-suite="holdout"]');
    btn.click();
    assert.deepEqual(adapterNames(dom), ['delta']);
    assert.ok(dom.window.location.search.includes('suite=holdout'));
  });

  it('CSV export for the holdout view carries only holdout rows', () => {
    const dom = loadLeaderboard('?suite=holdout');
    const root = dom.window.document.querySelector('[data-page="leaderboard"]');
    const csvRows = root.__csvRows();
    const suites = new Set(csvRows.slice(1).map((r) => r[3]));
    assert.deepEqual([...suites], ['holdout']);
  });
});

describe('leaderboard ranks', () => {
  it('ranks count eligible runs only, densely, when ineligible rows are shown', () => {
    // Sorted by ASR asc: beta (0.1, ineligible), alpha (0.2, eligible),
    // gamma (0.3, eligible). Eligible ranks must be 1, 2, not 2, 3.
    const dom = loadLeaderboard('?suite=public');
    assert.deepEqual(rankCells(dom), ['–', '1', '2']);
  });

  it('hiding ineligible rows keeps dense ranks', () => {
    const dom = loadLeaderboard('?suite=public&ineligible=hide');
    assert.deepEqual(rankCells(dom), ['1', '2']);
    assert.deepEqual(adapterNames(dom), ['alpha', 'gamma']);
  });
});
