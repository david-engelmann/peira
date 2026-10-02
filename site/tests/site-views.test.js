/* JSDOM tests for site/src/scripts/site.js, non-leaderboard views.
   B3: extends the B1 never-blended guarantee to every view. Each of the
   families, calibration, frontier, compare, and cases views must:
   1. Show only runs from the selected suite (public vs holdout).
   2. Swap suites via the toggle without a reload, updating the URL.
   3. Reset a cross-suite run smuggled in through the URL to a run that
      actually belongs to the viewed suite.
   4. Export CSV rows from the viewed suite only.
   Run: node --test tests/site-views.test.js (from site/) */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SITE_JS = fs.readFileSync(path.join(__dirname, '..', 'src', 'scripts', 'site.js'), 'utf8');

/* Two public runs (alpha guardrail, beta llm-baseline) and one holdout
   run (gamma guardrail). gamma's per-family ASR is the best of all three,
   so any leak across the suite boundary is visible in the numbers. */
const famMetrics = (asr) => ({
  asr, asr_ci95: [asr - 0.05, asr + 0.05],
  refusal_rate: 0.05, refusal_rate_ci95: [0.02, 0.08],
  n: 100, n_eligible: 90,
  flip_direction_counts: { 'deny-to-approve': Math.round(asr * 90) },
});
const calMetrics = (eceBenign, eceAttacked, ciLo = 0.01, ciHi = 0.05) => ({
  benign: { ece: eceBenign },
  attacked: { ece: eceAttacked },
  delta_brier: { delta: eceAttacked - eceBenign, ci95: [ciLo, ciHi] },
  confidence_coverage: 0.9,
  reliability_bins: {
    benign: { sufficient: true, bins: [{ n: 50, mean_forecast: 0.7, mean_outcome: 0.68, edge_lo: 0.6, edge_hi: 0.8 }] },
    attacked: { sufficient: false },
  },
});
const mkCase = (id, flipped) => ({
  case_id: id, family: 'fam_alpha', severity: 'high', primitive: 'p1',
  benign_decision: 'deny', attacked_decision: flipped ? 'approve' : 'deny',
  flipped, eligible: true,
});
const baseMetrics = (asr, cost, eceB = 0.05, eceA = 0.08, ciLo = 0.01, ciHi = 0.05) => ({
  asr_conditional: asr, asr_ci95: [asr - 0.05, asr + 0.05],
  benign_accuracy: 0.9, benign_accuracy_ci95: [0.85, 0.95],
  n_eligible: 100, ranking_eligible: true, eligibility_notes: [],
  per_family: { fam_alpha: famMetrics(asr), fam_beta: famMetrics(asr / 2) },
  calibration: calMetrics(eceB, eceA, ciLo, ciHi),
  cost: { cost_per_1k_decisions: cost },
  latency_ms: { overall: { p99: 120 } },
});
const RUNS = [
  {
    adapter_name: 'mock-alpha', adapter_version: '1', model_class: 'guardrail',
    division: 'guardrail', suite: 'public',
    metrics: baseMetrics(0.2, 2.5, 0.05, 0.08),
    cases: [mkCase('pub-001', true), mkCase('pub-002', false)],
  },
  {
    adapter_name: 'mock-beta', adapter_version: '1', model_class: 'llm-baseline',
    division: 'llm-baseline', suite: 'public',
    metrics: baseMetrics(0.3, 1.0, 0.11, 0.14, 0.02, 0.06),
    cases: [mkCase('pub-001', false), mkCase('pub-002', true)],
  },
  {
    adapter_name: 'mock-gamma', adapter_version: '1', model_class: 'guardrail',
    division: 'guardrail', suite: 'holdout',
    metrics: baseMetrics(0.05, 3.0, 0.02, 0.03),
    cases: [mkCase('mock-holdout-0000', true), mkCase('mock-holdout-0001', false)],
  },
];
const DATA = { schema_version: '2', mock_data: true, runs: RUNS,
  divisions: [{ key: 'guardrail', label: 'Guardrail division' },
              { key: 'llm-baseline', label: 'LLM baseline division' }] };
const DATA_SCRIPT = `<script id="site-data" type="application/json">${JSON.stringify(DATA).replace(/</g, '\\u003c')}</script>`;
const SUITE_TOGGLE = `
  <div class="seg" data-suite-toggle role="group" aria-label="Result suite">
    <button type="button" data-suite="public">Public</button>
    <button type="button" data-suite="holdout">Holdout</button>
  </div>`;
const EXPORT_CSV = `<button class="btn" type="button" data-export="csv">Export CSV</button>`;

const PAGES = {
  families: `<div data-page="families">${SUITE_TOGGLE}
    <select id="sel-adapter"></select><div id="fam-grid"></div>
    <div><span id="fam-name"></span></div><div id="fam-detail"></div>${EXPORT_CSV}</div>`,
  calibration: `<div data-page="calibration">${SUITE_TOGGLE}
    <select id="sel-adapter"></select><div id="cal-cards"></div>
    <div id="cal-charts"></div>${EXPORT_CSV}</div>`,
  frontier: `<div data-page="frontier">${SUITE_TOGGLE}
    <input type="checkbox" id="logx" checked /><div id="frontier-chart"></div>
    <p id="frontier-note"></p>${EXPORT_CSV}</div>`,
  compare: `<div data-page="compare">${SUITE_TOGGLE}
    <select id="sel-a"></select><select id="sel-b"></select>
    <div id="compare-out"></div>${EXPORT_CSV}</div>`,
  cases: `<div data-page="cases">${SUITE_TOGGLE}
    <select id="sel-run"></select><input type="search" id="q" />
    <select id="sel-family"></select><select id="sel-severity"></select>
    <select id="sel-flipped"></select><select id="sel-eligible"></select>
    <div id="cases-out"></div><div id="cases-pager"></div>${EXPORT_CSV}</div>`,
};

function loadPage(page, query = '') {
  const dom = new JSDOM(`<!DOCTYPE html><html><body>${DATA_SCRIPT}${PAGES[page]}</body></html>`, {
    url: 'https://peiratrial.dev/' + query,
    runScripts: 'outside-only',
  });
  dom.window.eval(SITE_JS);
  dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
  return dom;
}
const root = (dom, page) => dom.window.document.querySelector(`[data-page="${page}"]`);
const csvSuites = (dom, page) => {
  const rows = Array.from(root(dom, page).__csvRows(), (r) => Array.from(r));
  return new Set(rows.slice(1).map((r) => {
    // suite column position differs per view; find it from the header.
    const i = rows[0].indexOf('suite');
    return r[i];
  }));
};
const selectOptions = (dom, sel) =>
  [...dom.window.document.querySelectorAll(`${sel} option`)].map((o) => o.value);

describe('families view suite separation (never blended)', () => {
  it('public heatmap columns are public runs only', () => {
    const dom = loadPage('families', '?suite=public');
    const cols = [...dom.window.document.querySelectorAll('#fam-grid div.faint[title]')]
      .map((d) => d.getAttribute('title')).sort();
    assert.deepEqual(cols, ['mock-alpha', 'mock-beta']);
  });

  it('toggling to holdout swaps the columns without a reload', () => {
    const dom = loadPage('families', '?suite=public');
    dom.window.document.querySelector('[data-suite="holdout"]').click();
    const cols = [...dom.window.document.querySelectorAll('#fam-grid div.faint[title]')]
      .map((d) => d.getAttribute('title'));
    assert.deepEqual(cols, ['mock-gamma']);
    assert.ok(dom.window.location.search.includes('suite=holdout'));
  });

  it('a holdout adapter smuggled into a public URL resets to a public run', () => {
    const dom = loadPage('families', '?suite=public&adapter=mock-gamma@1@holdout');
    const sel = dom.window.document.querySelector('#sel-adapter');
    assert.ok(sel.value.endsWith('@public'), `adapter reset to public run, got ${sel.value}`);
    const detail = dom.window.document.querySelector('#fam-detail').textContent;
    assert.ok(!detail.includes('gamma'), 'holdout run must not appear in the public detail panel');
    assert.ok(detail.includes('adapter alpha 1'), 'detail falls back to the first public run');
  });

  it('CSV export carries only the viewed suite', () => {
    const dom = loadPage('families', '?suite=public');
    assert.deepEqual([...csvSuites(dom, 'families')], ['public']);
    const dom2 = loadPage('families', '?suite=holdout');
    assert.deepEqual([...csvSuites(dom2, 'families')], ['holdout']);
  });
});

describe('calibration view suite separation (never blended)', () => {
  it('adapter select lists public runs only', () => {
    const dom = loadPage('calibration', '?suite=public');
    assert.deepEqual(selectOptions(dom, '#sel-adapter').sort(),
      ['mock-alpha@1@public', 'mock-beta@1@public']);
  });

  it('cards show the selected run calibration, and the toggle swaps to the holdout run', () => {
    const dom = loadPage('calibration', '?suite=public');
    // default run is alpha: benign ECE 0.05, attacked ECE 0.08
    let cards = dom.window.document.querySelector('#cal-cards').textContent;
    assert.ok(cards.includes('0.0500'), 'alpha benign ECE on the cards');
    assert.ok(cards.includes('0.0800'), 'alpha attacked ECE on the cards');
    assert.ok(!cards.includes('0.1100'), 'beta ECE must not leak into the alpha view');
    const sel = dom.window.document.querySelector('#sel-adapter');
    sel.value = 'mock-beta@1@public';
    sel.dispatchEvent(new dom.window.Event('change'));
    cards = dom.window.document.querySelector('#cal-cards').textContent;
    assert.ok(cards.includes('0.1100'), 'beta benign ECE after switching runs');
    assert.ok(!cards.includes('0.0500'), 'alpha ECE must not persist after switching runs');
    dom.window.document.querySelector('[data-suite="holdout"]').click();
    assert.deepEqual(selectOptions(dom, '#sel-adapter'), ['mock-gamma@1@holdout']);
    cards = dom.window.document.querySelector('#cal-cards').textContent;
    assert.ok(cards.includes('0.0200'), 'gamma benign ECE on the holdout cards');
    assert.ok(!cards.includes('0.1100'), 'public ECE must not leak into the holdout view');
    assert.ok(dom.window.location.search.includes('suite=holdout'));
  });

  it('CSV export carries only the viewed suite', () => {
    const dom = loadPage('calibration', '?suite=holdout');
    assert.deepEqual([...csvSuites(dom, 'calibration')], ['holdout']);
  });
});

describe('frontier view suite separation (never blended)', () => {
  const pointTitles = (dom) =>
    [...dom.window.document.querySelectorAll('#frontier-chart svg.chart circle title')]
      .map((t) => t.textContent);

  it('public frontier plots public runs only', () => {
    const dom = loadPage('frontier', '?suite=public');
    const titles = pointTitles(dom);
    assert.equal(titles.length, 2);
    assert.ok(titles.every((t) => !t.includes('gamma')), 'no holdout point on the public frontier');
  });

  it('toggling to holdout replots holdout points only', () => {
    const dom = loadPage('frontier', '?suite=public');
    dom.window.document.querySelector('[data-suite="holdout"]').click();
    const titles = pointTitles(dom);
    assert.equal(titles.length, 1);
    assert.ok(titles[0].includes('gamma'));
    assert.ok(dom.window.location.search.includes('suite=holdout'));
  });

  it('CSV export carries only the viewed suite', () => {
    const dom = loadPage('frontier', '?suite=public');
    assert.deepEqual([...csvSuites(dom, 'frontier')], ['public']);
  });
});

describe('compare view suite separation (never blended)', () => {
  it('run selects list public runs only', () => {
    const dom = loadPage('compare', '?suite=public');
    assert.deepEqual(selectOptions(dom, '#sel-a').sort(),
      ['mock-alpha@1@public', 'mock-beta@1@public']);
    assert.deepEqual(selectOptions(dom, '#sel-b').sort(),
      ['mock-alpha@1@public', 'mock-beta@1@public']);
  });

  it('comparison joins cases from the two viewed runs only', () => {
    // alpha and beta share pub-001/pub-002 with opposite flip outcomes,
    // so both land in the discordant table; gamma's holdout cases join nothing.
    const dom = loadPage('compare', '?suite=public');
    const out = dom.window.document.querySelector('#compare-out').textContent;
    assert.ok(out.includes('Shared cases'));
    const rows = [...dom.window.document.querySelectorAll('#compare-out tbody tr td.mono')]
      .filter((_, i) => i % 4 === 0).map((td) => td.textContent).sort();
    assert.deepEqual(rows, ['pub-001', 'pub-002']);
    assert.ok(!out.includes('mock-holdout'), 'holdout case ids must not join the public comparison');
  });

  it('CSV export carries the viewed runs discordant cases only', () => {
    const dom = loadPage('compare', '?suite=public');
    const rows = Array.from(root(dom, 'compare').__csvRows(), (r) => Array.from(r));
    const suiteIdx = rows[0].indexOf('suite');
    const idIdx = rows[0].indexOf('case_id');
    const ids = rows.slice(1).map((r) => r[idIdx]).sort();
    const suites = new Set(rows.slice(1).map((r) => r[suiteIdx]));
    assert.deepEqual(ids, ['pub-001', 'pub-002']);
    assert.deepEqual([...suites], ['public']);
    const dom2 = loadPage('compare', '?suite=holdout');
    const rows2 = Array.from(root(dom2, 'compare').__csvRows(), (r) => Array.from(r));
    assert.equal(rows2.length, 1, 'single holdout run means no pair and no discordant rows');
  });

  it('a holdout run smuggled into a public compare URL resets', () => {
    const dom = loadPage('compare', '?suite=public&a=mock-gamma@1@holdout&b=mock-alpha@1@public');
    const a = dom.window.document.querySelector('#sel-a').value;
    assert.ok(a.endsWith('@public'), `run A reset to a public run, got ${a}`);
  });

  it('toggling to holdout swaps both selects without a reload', () => {
    const dom = loadPage('compare', '?suite=public');
    dom.window.document.querySelector('[data-suite="holdout"]').click();
    assert.deepEqual(selectOptions(dom, '#sel-a'), ['mock-gamma@1@holdout']);
    assert.ok(dom.window.location.search.includes('suite=holdout'));
  });
});

describe('cases view suite separation (never blended)', () => {
  const rowCaseIds = (dom) =>
    [...dom.window.document.querySelectorAll('#cases-out tbody tr td.mono')]
      .filter((_, i) => i % 5 === 0).map((td) => td.textContent);

  it('run select lists public runs only', () => {
    const dom = loadPage('cases', '?suite=public');
    assert.deepEqual(selectOptions(dom, '#sel-run').sort(),
      ['mock-alpha@1@public', 'mock-beta@1@public']);
  });

  it('table shows the selected public run cases only', () => {
    const dom = loadPage('cases', '?suite=public');
    assert.deepEqual(rowCaseIds(dom), ['pub-001', 'pub-002']);
  });

  it('toggling to holdout shows holdout cases only', () => {
    const dom = loadPage('cases', '?suite=public');
    dom.window.document.querySelector('[data-suite="holdout"]').click();
    assert.deepEqual(rowCaseIds(dom), ['mock-holdout-0000', 'mock-holdout-0001']);
    assert.deepEqual(selectOptions(dom, '#sel-run'), ['mock-gamma@1@holdout']);
    assert.ok(dom.window.location.search.includes('suite=holdout'));
  });

  it('CSV export carries only the viewed run and suite', () => {
    const dom = loadPage('cases', '?suite=holdout');
    const rows = Array.from(root(dom, 'cases').__csvRows(), (r) => Array.from(r));
    const suiteIdx = rows[0].indexOf('suite');
    const adapterIdx = rows[0].indexOf('adapter');
    const suites = new Set(rows.slice(1).map((r) => r[suiteIdx]));
    const adapters = new Set(rows.slice(1).map((r) => r[adapterIdx]));
    assert.deepEqual([...suites], ['holdout']);
    assert.deepEqual([...adapters], ['mock-gamma']);
  });
});
