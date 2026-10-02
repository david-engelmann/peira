/* JSDOM-adjacent tests for per-view OG/social images.
   Program B B5: every data view ships its own social image instead of
   sharing the leaderboard one.

   These tests parse source directly (no dist/ dependency): each page must
   declare its ogImage, every referenced file must exist in public/og/,
   and Base.astro must wire the prop into both og:image and twitter:image.
   Run: node --test tests/site-og.test.js (from site/) */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SITE = path.join(__dirname, '..');
const PAGES = path.join(SITE, 'src', 'pages');
const OG_DIR = path.join(SITE, 'public', 'og');

/* page file -> expected og image file. index.astro keeps the default. */
const EXPECTED = {
  'index.astro': 'og-leaderboard.png',
  'families.astro': 'og-families.png',
  'calibration.astro': 'og-calibration.png',
  'frontier.astro': 'og-frontier.png',
  'compare.astro': 'og-compare.png',
  'cases.astro': 'og-cases.png',
  'methodology.astro': 'og-methodology.png',
};

describe('per-view OG images', () => {
  it('Base.astro accepts an ogImage prop defaulting to the leaderboard image', () => {
    const src = fs.readFileSync(path.join(SITE, 'src', 'layouts', 'Base.astro'), 'utf8');
    assert.match(src, /ogImage\s*=\s*'og-leaderboard\.png'/);
  });

  it('Base.astro renders ogImage into og:image and twitter:image', () => {
    const src = fs.readFileSync(path.join(SITE, 'src', 'layouts', 'Base.astro'), 'utf8');
    assert.match(src, /og:image"\s+content=\{"https:\/\/peiratrial\.dev\/og\/" \+ ogImage\}/);
    assert.match(src, /twitter:image"\s+content=\{"https:\/\/peiratrial\.dev\/og\/" \+ ogImage\}/);
  });

  it('every data page declares its own ogImage', () => {
    for (const [page, image] of Object.entries(EXPECTED)) {
      if (page === 'index.astro') continue; // index keeps the default
      const src = fs.readFileSync(path.join(PAGES, page), 'utf8');
      assert.match(src, new RegExp(`ogImage="${image.replace('.', '\\.')}"`),
        `${page} must pass ogImage="${image}"`);
    }
  });

  it('every referenced OG image exists as png, svg, and alt text', () => {
    for (const image of Object.values(EXPECTED)) {
      const base = image.replace(/\.png$/, '');
      for (const ext of ['.png', '.svg', '.alt.txt']) {
        const p = path.join(OG_DIR, base + ext);
        assert.ok(fs.existsSync(p), `missing ${base + ext}`);
      }
    }
  });

  it('no page still hardcodes the shared leaderboard image in meta', () => {
    const src = fs.readFileSync(path.join(SITE, 'src', 'layouts', 'Base.astro'), 'utf8');
    assert.ok(!src.includes('content="https://peiratrial.dev/og/og-leaderboard.png"'),
      'Base.astro must not hardcode og-leaderboard.png in meta tags');
  });

  it('alt text sidecars are non-empty and name their view', () => {
    const viewNames = {
      'og-leaderboard': 'leaderboard', 'og-families': 'families',
      'og-calibration': 'calibration', 'og-frontier': 'frontier',
      'og-compare': 'compare', 'og-cases': 'cases',
      'og-methodology': 'methodology',
    };
    for (const [base, view] of Object.entries(viewNames)) {
      const alt = fs.readFileSync(path.join(OG_DIR, base + '.alt.txt'), 'utf8');
      assert.ok(alt.trim().length > 50, `${base}.alt.txt is too short`);
      assert.ok(alt.toLowerCase().includes(view),
        `${base}.alt.txt must name the ${view} view`);
    }
  });
});
