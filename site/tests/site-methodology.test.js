/* JSDOM tests for site/src/pages/methodology.astro.
   B4: locks in the methodology content page requirements.
   1. All required sections render (paired cases, flip definition,
      conditional ASR, CIs, divisions, baseline context, ranking
      eligibility, suites, calibration, cost/latency, sealed artifacts,
      mock-data honesty).
   2. Copy bar: no em dashes, en dashes, colons, or semicolons in
      visible text.
   3. The page links to the full methodology docs.
   Self-contained: parses the .astro source directly (strips frontmatter),
   no build step required.
   Run: node --test tests/site-methodology.test.js (from site/) */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(
  path.join(__dirname, '..', 'src', 'pages', 'methodology.astro'), 'utf8');

// Strip the Astro frontmatter (--- ... ---) to get the template HTML.
const TEMPLATE = SOURCE.replace(/^---[\s\S]*?---\s*/, '');
const dom = new JSDOM(TEMPLATE);
const doc = dom.window.document;
const text = () => doc.body.textContent || '';

const REQUIRED_HEADINGS = [
  'Paired cases',
  'What counts as a flip',
  'Conditional attack success rate',
  'Confidence intervals',
  'Divisions',
  'Baseline context',
  'Ranking eligibility',
  'Public and Holdout suites',
  'Calibration',
  'Cost and latency',
  'Sealed artifacts',
  'Mock data honesty',
];

describe('methodology page', () => {
  it('renders every required section heading', () => {
    const headings = Array.from(doc.querySelectorAll('h2'))
      .map((h) => h.textContent.trim());
    for (const required of REQUIRED_HEADINGS) {
      assert.ok(
        headings.includes(required),
        `missing section: ${required} (have: ${headings.join(', ')})`);
    }
  });

  it('explains divisions without mixing headlines', () => {
    const t = text();
    assert.ok(t.includes('never mixes them') || t.includes('never mixes'),
      'divisions section must state headlines are never mixed');
    assert.ok(t.includes('dense within'),
      'divisions section must mention dense ranks within each division');
  });

  it('states the ranking eligibility gates', () => {
    const t = text();
    assert.ok(t.includes('two hundred eligible cases') || t.includes('200 eligible'),
      'must state the 200-case overall gate');
    assert.ok(t.includes('twenty eligible') || t.includes('20 eligible'),
      'must state the per-family gate');
  });

  it('defines a flip as decision or abstention change', () => {
    const t = text();
    assert.ok(t.includes('abstention state changes') || t.includes('abstained'),
      'flip definition must cover abstention changes');
  });

  it('has no em dashes, en dashes, colons, or semicolons in visible text', () => {
    const t = text();
    for (const ch of t) {
      const cp = ch.codePointAt(0);
      assert.ok(cp !== 0x2014, 'em dash found in visible text');
      assert.ok(cp !== 0x2013, 'en dash found in visible text');
    }
    // Colons and semicolons: allow none in prose (URLs excluded by scoping
    // to text nodes without http).
    const walker = doc.createTreeWalker(doc.body, 4 /* NodeFilter.SHOW_TEXT */);
    let node;
    while ((node = walker.nextNode())) {
      const v = node.nodeValue;
      if (v.includes('http')) continue;
      assert.ok(!v.includes(':'), `colon in text: ${v.trim().slice(0, 80)}`);
      assert.ok(!v.includes(';'), `semicolon in text: ${v.trim().slice(0, 80)}`);
    }
  });

  it('links to the full methodology docs', () => {
    const links = Array.from(doc.querySelectorAll('a[href]'))
      .map((a) => a.getAttribute('href'));
    assert.ok(
      links.some((h) => h.includes('/docs')),
      `expected a link to the full docs (have: ${links.join(', ')})`);
  });
});
