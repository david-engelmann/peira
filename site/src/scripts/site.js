/* Peira display site client logic. Dependency-free.
   Every page reads the build-time JSON from #site-data, keeps ALL view
   state in the URL query string, and re-renders on control changes.
   Copy on this page avoids em dashes, colons and semicolons per the
   public copy rules, and every mock surface stays labeled as mock. */
(() => {
  'use strict';

  const DATA_EL = document.getElementById('site-data');
  if (!DATA_EL) return;
  const DATA = JSON.parse(DATA_EL.textContent);
  const MOCK = DATA.mock_data === true;
  const RUNS = DATA.runs || [];
  const page = (document.querySelector('[data-page]') || {}).dataset?.page;
  if (!page) return;

  /* ---------- query state ---------- */
  const getQuery = () => new URLSearchParams(window.location.search);
  const readState = (defaults) => {
    const q = getQuery();
    const s = { ...defaults };
    for (const k of Object.keys(defaults)) {
      if (q.has(k)) s[k] = q.get(k);
    }
    return s;
  };
  const writeState = (state) => {
    const url = new URL(window.location.href);
    url.search = '';
    for (const [k, v] of Object.entries(state)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
    }
    window.history.replaceState({}, '', url);
  };

  /* ---------- formatting ---------- */
  // Escape artifact-derived strings before HTML interpolation. Artifact
  // content is sealed for integrity, not sanitized, so every name, note,
  // case ID, and decision that reaches innerHTML goes through esc().
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const num = (x, digits) => {
    if (x === null || x === undefined || Number.isNaN(x)) return 'withheld';
    return digits === undefined ? Number(x).toLocaleString('en-US') : Number(x).toFixed(digits);
  };
  const pct = (x, digits = 1) => {
    if (x === null || x === undefined || Number.isNaN(x)) return 'withheld';
    return (Number(x) * 100).toFixed(digits) + '%';
  };
  const ciText = (ci, asPct = true) => {
    if (!ci || ci[0] === null || ci[1] === null) return '';
    const f = asPct ? pct : (x) => num(x, 4);
    return '95% CI ' + f(ci[0]) + ' to ' + f(ci[1]);
  };
  const money = (x) => (x === null || x === undefined ? 'withheld' : '$' + Number(x).toFixed(2));
  const ms = (x) => (x === null || x === undefined ? 'withheld' : Math.round(Number(x)).toLocaleString('en-US') + ' ms');
  const shortName = (name) => name.replace(/^mock-/, '');
  const runLabel = (r) => `${shortName(r.adapter_name)} ${r.adapter_version}`;

  /* ---------- data access ---------- */
  const runsForSuite = (suite) => RUNS.filter((r) => r.suite === suite);
  const runId = (r) => r.adapter_name + '@' + r.adapter_version + '@' + r.suite;
  const findRun = (id) => RUNS.find((r) => runId(r) === id);
  const allFamilies = () => {
    const s = new Set();
    for (const r of RUNS) for (const f of Object.keys(r.metrics.per_family || {})) s.add(f);
    return [...s].sort();
  };
  // EB-5: matrix rows inside one suite view use the families present in
  // that suite, so the view never renders rows for families absent from
  // every run in view, while gaps between runs in the same suite stay
  // visible as "not evaluated" cells. The build-wide canonical inventory
  // (dataset.families, see SITE_DATA_SCHEMA.md) is the contract the
  // rows are drawn from; the suite slice is a view concern only.
  const suiteFamilies = (suite) => {
    const s = new Set();
    for (const r of runsForSuite(suite)) for (const f of Object.keys(r.metrics.per_family || {})) s.add(f);
    return [...s].sort();
  };
  const coverageCell = (r) => {
    const c = r.coverage || {};
    if (c.families_total === null || c.families_total === undefined || c.families_total === 0) return 'withheld';
    const pctTxt = (c.coverage_pct === null || c.coverage_pct === undefined) ? '' : `<span class="ci">${Number(c.coverage_pct).toFixed(1)}% of families</span>`;
    return `${c.families_evaluated}/${c.families_total}${pctTxt}`;
  };
  // EB-5: a family counts as evaluated only when the run has cases in
  // it. The metrics layer lists required-but-unevaluated families with
  // n=0; those render as "not evaluated", never as measured zeros.
  const familyEvaluated = (pf) => pf !== undefined && pf !== null && (pf.n || 0) > 0;

  const PALETTE = ['#e8a33d', '#6fbf73', '#7aa5e8', '#b493e8', '#58b8a8', '#d96a5f', '#d8b84a', '#8fc1e8'];
  const colorFor = (name, suiteRuns) => {
    const i = suiteRuns.findIndex((r) => r.adapter_name === name);
    return PALETTE[(i < 0 ? 0 : i) % PALETTE.length];
  };

  /* ---------- exports ---------- */
  const download = (filename, content, mime) => {
    const blob = content instanceof Blob ? content : new Blob([content], { type: mime });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 400);
  };
  const csvCell = (v) => {
    if (v === null || v === undefined) return '';
    if (typeof v === 'number') return String(v);
    let s = String(v);
    // CSV injection defense: a hostile cell value starting with a
    // formula trigger must not execute as a spreadsheet formula on open.
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const rowsToCsv = (rows) => rows.map((r) => r.map(csvCell).join(',')).join('\n') + '\n';
  const mockNote = () => MOCK ? 'mock data, synthetic placeholder values' : '';

  const exportSvg = (svgEl, filename) => {
    const clone = svgEl.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    const css = 'text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}';
    const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    style.textContent = css;
    clone.insertBefore(style, clone.firstChild);
    download(filename, new XMLSerializer().serializeToString(clone), 'image/svg+xml');
  };
  const exportPng = (svgEl, filename, scale = 2) => {
    const clone = svgEl.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    const w = Number(svgEl.getAttribute('width')) || 800;
    const h = Number(svgEl.getAttribute('height')) || 500;
    const str = new XMLSerializer().serializeToString(clone);
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = w * scale; c.height = h * scale;
      const ctx = c.getContext('2d');
      ctx.fillStyle = '#17171d';
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height);
      c.toBlob((b) => b && download(filename, b, 'image/png'), 'image/png');
    };
    img.onerror = () => alert('PNG export failed for this chart.');
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(str);
  };
  const bindExport = (root, getSvg, getBaseName) => {
    // getBaseName is a function so the file name reflects the state at
    // click time, not at bind time (the suite toggle changes state
    // without a page reload).
    const csv = root.querySelector('[data-export="csv"]');
    const svg = root.querySelector('[data-export="svg"]');
    const png = root.querySelector('[data-export="png"]');
    if (csv) csv.addEventListener('click', () => {
      const rows = root.__csvRows ? root.__csvRows() : null;
      if (rows) download(getBaseName() + '.csv', rowsToCsv(rows), 'text/csv');
    });
    if (svg) svg.addEventListener('click', () => { const el = getSvg(); if (el) exportSvg(el, getBaseName() + '.svg'); });
    if (png) png.addEventListener('click', () => { const el = getSvg(); if (el) exportPng(el, getBaseName() + '.png'); });
  };
  const copyLink = (root) => {
    const btn = root.querySelector('[data-copylink]');
    if (btn) btn.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(window.location.href); btn.textContent = 'Link copied'; }
      catch { btn.textContent = 'Copy failed'; }
      setTimeout(() => { btn.textContent = 'Copy link to this view'; }, 1600);
    });
  };

  /* ---------- suite toggle ---------- */
  const bindSuiteToggle = (root, state, onChange) => {
    root.querySelectorAll('[data-suite-toggle]').forEach((seg) => {
      const btns = seg.querySelectorAll('button');
      const paint = () => btns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.suite === state.suite)));
      paint();
      btns.forEach((b) => b.addEventListener('click', () => {
        if (state.suite === b.dataset.suite) return;
        state.suite = b.dataset.suite;
        // reset run-scoped selections when the suite changes
        for (const k of ['adapter', 'a', 'b', 'run', 'page']) delete state[k];
        writeState(state);
        paint();
        onChange();
      }));
    });
  };
  /* ---------- svg helpers ---------- */
  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  };
  const txt = (parent, x, y, s, attrs) => {
    const t = el('text', { x, y, ...(attrs || {}) }, parent);
    t.textContent = s;
    return t;
  };
  const heatColor = (v) => {
    // v in [0,1]; green (low ASR) to amber to red (high ASR)
    if (v === null || v === undefined) return 'transparent';
    const c = Math.max(0, Math.min(1, v));
    const stops = [[111, 191, 115], [232, 163, 61], [217, 106, 95]];
    const seg = c < 0.5 ? [stops[0], stops[1], c * 2] : [stops[1], stops[2], (c - 0.5) * 2];
    const mix = seg[0].map((a, i) => Math.round(a + (seg[1][i] - a) * seg[2]));
    return `rgba(${mix[0]},${mix[1]},${mix[2]},${0.25 + 0.65 * c})`;
  };

  /* ================= leaderboard ================= */
  const leaderboard = () => {
    const root = document.querySelector('[data-page="leaderboard"]');
    const state = readState({ suite: 'public', sort: 'asr', dir: 'asc', ineligible: 'show' });
    const tableWrap = root.querySelector('#board-wrap');
    const countEl = root.querySelector('#board-count');

    const columns = [
      { key: 'asr', label: 'Conditional ASR', get: (r) => r.metrics.asr_conditional, nullsLast: true },
      { key: 'acc', label: 'Benign accuracy', get: (r) => r.metrics.benign_accuracy, nullsLast: true },
      { key: 'n', label: 'Eligible cases', get: (r) => r.metrics.n_eligible },
      { key: 'cov', label: 'Coverage', get: (r) => r.coverage && r.coverage.coverage_pct, nullsLast: true },
      { key: 'cost', label: 'Cost per 1k', get: (r) => r.metrics.cost && r.metrics.cost.cost_per_1k_decisions, nullsLast: true },
      { key: 'lat', label: 'p99 latency', get: (r) => r.metrics.latency_ms && r.metrics.latency_ms.overall && r.metrics.latency_ms.overall.p99, nullsLast: true },
    ];

    const render = () => {
      let runs = runsForSuite(state.suite);
      const eligibleOnly = state.ineligible === 'hide';
      if (eligibleOnly) runs = runs.filter((r) => r.metrics.ranking_eligible);
      const col = columns.find((c) => c.key === state.sort) || columns[0];
      const asc = state.dir === 'asc';
      runs = [...runs].sort((a, b) => {
        const va = col.get(a), vb = col.get(b);
        const na = va === null || va === undefined, nb = vb === null || vb === undefined;
        if (na && nb) return 0;
        if (na) return col.nullsLast ? 1 : -1;
        if (nb) return col.nullsLast ? -1 : 1;
        return asc ? va - vb : vb - va;
      });

      const colorMap = new Map();
      runsForSuite(state.suite).forEach((r, i) => {
        if (!colorMap.has(r.adapter_name)) colorMap.set(r.adapter_name, PALETTE[i % PALETTE.length]);
      });

      let html = '<table class="board"><thead><tr><th class="no-sort">Rank</th><th class="no-sort">Adapter</th>';
      for (const c of columns) {
        const arrow = state.sort === c.key ? '<span class="dir">' + (state.dir === 'asc' ? '▲' : '▼') + '</span>' : '';
        html += `<th data-sort="${c.key}">${c.label}${arrow}</th>`;
      }
      html += '<th class="no-sort">Eligibility</th></tr></thead><tbody>';
      runs.forEach((r, i) => {
        const m = r.metrics;
        const asrBar = m.asr_conditional === null ? '' : `<span class="bar"><i style="width:${Math.min(100, m.asr_conditional * 100).toFixed(1)}%;background:${colorMap.get(r.adapter_name)}"></i></span>`;
        const elig = m.ranking_eligible
          ? '<span class="badge ok">ranking eligible</span>'
          : '<span class="badge warn" title="' + esc((m.eligibility_notes || []).join(' ')) + '">not eligible</span>';
        const rankCell = m.ranking_eligible ? `<td class="rank num">${i + 1}</td>` : '<td class="rank num">–</td>';
        html += `<tr>${rankCell}` +
          `<td><span class="adapter-name">${esc(shortName(r.adapter_name))}</span><div class="faint mono" style="font-size:11.5px">${esc(r.adapter_version)} · ${esc(r.model_class || '')}</div></td>` +
          `<td class="num">${asrBar}${pct(m.asr_conditional)}<span class="ci">${ciText(m.asr_ci95)}</span></td>` +
          `<td class="num">${pct(m.benign_accuracy)}<span class="ci">${ciText(m.benign_accuracy_ci95)}</span></td>` +
          `<td class="num">${num(m.n_eligible)}</td>` +
          `<td class="num">${coverageCell(r)}</td>` +
          `<td class="num">${money(m.cost && m.cost.cost_per_1k_decisions)}</td>` +
          `<td class="num">${ms(m.latency_ms && m.latency_ms.overall && m.latency_ms.overall.p99)}</td>` +
          `<td>${elig}${MOCK ? ' <span class="badge mock">mock</span>' : ''}</td></tr>`;
      });
      html += '</tbody></table>';
      tableWrap.innerHTML = html;
      countEl.textContent = runs.length + ' of ' + runsForSuite(state.suite).length + ' runs in view';
      tableWrap.querySelectorAll('th[data-sort]').forEach((th) => th.addEventListener('click', () => {
        const k = th.dataset.sort;
        if (state.sort === k) state.dir = state.dir === 'asc' ? 'desc' : 'asc';
        else { state.sort = k; state.dir = k === 'acc' ? 'desc' : 'asc'; }
        writeState(state); render();
      }));

      root.__csvRows = () => {
        const rows = [['adapter', 'adapter_version', 'model_class', 'suite', 'ranking_eligible',
          'asr_conditional', 'asr_ci95_lo', 'asr_ci95_hi', 'benign_accuracy', 'benign_accuracy_ci95_lo',
          'benign_accuracy_ci95_hi', 'n_eligible', 'n_cases', 'coverage_families_evaluated',
          'coverage_families_total', 'coverage_pct', 'cost_per_1k_usd', 'p99_latency_ms', mockNote() ? 'mock_note' : ''].filter(Boolean)];
        for (const r of runs) {
          const m = r.metrics;
          const cov = r.coverage || {};
          rows.push([r.adapter_name, r.adapter_version, r.model_class, r.suite, m.ranking_eligible,
            m.asr_conditional, m.asr_ci95 && m.asr_ci95[0], m.asr_ci95 && m.asr_ci95[1],
            m.benign_accuracy, m.benign_accuracy_ci95 && m.benign_accuracy_ci95[0], m.benign_accuracy_ci95 && m.benign_accuracy_ci95[1],
            m.n_eligible, m.n_cases,
            cov.families_evaluated, cov.families_total, cov.coverage_pct,
            m.cost && m.cost.cost_per_1k_decisions,
            m.latency_ms && m.latency_ms.overall && m.latency_ms.overall.p99,
            mockNote()].filter((v, i) => i < rows[0].length));
        }
        return rows;
      };
    };

    bindSuiteToggle(root, state, render);
    root.querySelector('#ineligible-filter').addEventListener('change', (e) => {
      state.ineligible = e.target.checked ? 'hide' : 'show';
      writeState(state); render();
    });
    root.querySelector('#ineligible-filter').checked = state.ineligible === 'hide';
    bindExport(root, () => null, () => 'peira-leaderboard-' + state.suite);
    copyLink(root);
    render();
  };

  /* ================= families ================= */
  const families = () => {
    const root = document.querySelector('[data-page="families"]');
    const state = readState({ suite: 'public', adapter: '', family: '', sort: 'asr' });
    const gridEl = root.querySelector('#fam-grid');
    const detailEl = root.querySelector('#fam-detail');
    const selAdapter = root.querySelector('#sel-adapter');
    const matrixEl = root.querySelector('#matrix-table');
    const matrixAdapterEl = root.querySelector('#matrix-adapter');
    const matrixCovEl = root.querySelector('#matrix-coverage');
    const matrixNoteEl = root.querySelector('#matrix-note');
    // EB-5: rows come from the families present in the selected suite, so
    // the view never renders rows for families absent from every run in
    // view. A family present in the suite but missing from one run is a
    // visibly missing cell, never a silent gap.
    const famList = () => suiteFamilies(state.suite);

    // EB-5: the full family-by-metric matrix for one run. Every family in
    // the suite appears as a row. A family the run never evaluated is a
    // "not evaluated" row; an evaluated family with a null metric is
    // "withheld". Neither state is ever dropped or blanked.
    const matrixCell = (evaluated, value, fmt) => {
      if (!evaluated) return '<span class="missing-label">not evaluated</span>';
      if (value === null || value === undefined) return 'withheld';
      return fmt(value);
    };
    const renderMatrix = (run) => {
      if (!matrixEl) return;
      const fams = [...famList()].sort();
      const pfAll = (run && run.metrics.per_family) || {};
      matrixAdapterEl.textContent = run ? runLabel(run) : '';
      matrixCovEl.textContent = run
        ? coverageCell(run) + ' families evaluated. Families with no cases in this run stay in the table and are marked, never dropped.'
        : '';
      let html = '<table class="board" style="min-width:780px"><thead><tr>' +
        '<th class="no-sort">Family</th><th class="no-sort">Conditional ASR</th>' +
        '<th class="no-sort">Refusal rate</th><th class="no-sort">Eligible cases</th>' +
        '</tr></thead><tbody>';
      for (const f of fams) {
        const pf = pfAll[f];
        const evaluated = familyEvaluated(pf);
        html += '<tr><td class="mono">' + esc(f) + '</td>' +
          '<td class="num">' + matrixCell(evaluated, evaluated ? pf.asr : null,
            (v) => pct(v) + '<span class="ci">' + ciText(pf.asr_ci95) + '</span>') + '</td>' +
          '<td class="num">' + matrixCell(evaluated, evaluated ? pf.refusal_rate : null, (v) => pct(v)) + '</td>' +
          '<td class="num">' + matrixCell(evaluated, evaluated ? pf.n_eligible : null,
            (v) => num(v) + '<span class="ci">of ' + num(pf.n) + ' cases</span>') + '</td></tr>';
      }
      html += '</tbody></table>';
      matrixEl.innerHTML = html;
      matrixNoteEl.textContent = MOCK ? 'Mock values.' : '';
    };

    const render = () => {
      const suiteRuns = runsForSuite(state.suite);
      if (!suiteRuns.some((r) => runId(r) === state.adapter)) state.adapter = suiteRuns.length ? runId(suiteRuns[0]) : '';
      if (!famList().includes(state.family)) state.family = famList()[0] || '';

      selAdapter.innerHTML = suiteRuns.map((r) =>
        `<option value="${esc(runId(r))}"${runId(r) === state.adapter ? ' selected' : ''}>${esc(runLabel(r))}</option>`).join('');

      // heatmap: rows = families, columns = runs
      const fams = [...famList()].sort();
      const colCount = suiteRuns.length;
      gridEl.style.gridTemplateColumns = `200px repeat(${colCount}, 1fr) 64px`;
      let html = '<div class="fam faint" style="font-family:var(--sans);font-size:11px;text-transform:uppercase;letter-spacing:0.07em">Family</div>';
      for (const r of suiteRuns) html += `<div class="faint" style="font-size:11px;text-align:center" title="${esc(r.adapter_name)}">${esc(shortName(r.adapter_name))}</div>`;
      html += '<div></div>';
      for (const f of fams) {
        html += `<div class="fam" data-family="${esc(f)}" style="cursor:pointer">${esc(f)}</div>`;
        let worst = null;
        for (const r of suiteRuns) {
          const pf = (r.metrics.per_family || {})[f];
          const evaluated = familyEvaluated(pf);
          const v = evaluated ? pf.asr : null;
          if (v !== null && (worst === null || v > worst)) worst = v;
          const cellCls = evaluated ? (v === null ? 'cell withheld' : 'cell') : 'cell missing';
          const cellTitle = evaluated ? `${esc(f)} · ${esc(shortName(r.adapter_name))} · ${pct(v)}`
            : `${esc(f)} · ${esc(shortName(r.adapter_name))} · not evaluated in this run`;
          html += `<div class="${cellCls}" data-family="${esc(f)}" style="cursor:pointer" title="${cellTitle}"><i style="width:${v === null ? 0 : Math.min(100, v * 100).toFixed(1)}%;background:${heatColor(v)}"></i></div>`;
        }
        html += `<div class="val">${pct(worst)}</div>`;
      }
      gridEl.innerHTML = html;
      gridEl.querySelectorAll('[data-family]').forEach((n) => n.addEventListener('click', () => {
        state.family = n.dataset.family; writeState(state); render();
      }));

      // detail for selected family + adapter
      const run = findRun(state.adapter);
      let dHtml = '';
      if (run) {
        const pf = (run.metrics.per_family || {})[state.family] || {};
        const evaluated = familyEvaluated(pf);
        const dirs = pf.flip_direction_counts || {};
        const dirKeys = Object.keys(dirs).sort();
        dHtml = (evaluated ? '' : '<p class="note"><span class="missing-label">not evaluated</span> This run had no cases in this family, so the cards below are empty by construction.</p>') +
          '<div class="cards">' +
          `<div class="card"><div class="k">Conditional ASR</div><div class="v">${pct(pf.asr)}</div><div class="sub">${ciText(pf.asr_ci95)}</div></div>` +
          `<div class="card"><div class="k">Refusal rate</div><div class="v">${pct(pf.refusal_rate)}</div><div class="sub">${ciText(pf.refusal_rate_ci95)}</div></div>` +
          `<div class="card"><div class="k">Eligible cases</div><div class="v">${num(pf.n_eligible)}</div><div class="sub">of ${num(pf.n)} cases in family</div></div></div>` +
          '<h3 style="margin:18px 0 8px">Flip directions, eligible cases</h3>' +
          '<div class="table-scroll"><table class="board" style="min-width:420px"><thead><tr><th class="no-sort">Direction</th><th class="no-sort">Count</th></tr></thead><tbody>' +
          dirKeys.map((k) => `<tr><td class="mono">${esc(k)}</td><td class="num">${num(dirs[k])}</td></tr>`).join('') +
          '</tbody></table></div>' +
          '<p class="note">Family ' + esc(state.family) + ', adapter ' + esc(runLabel(run)) + '. ' + (MOCK ? 'Mock values.' : '') + '</p>';

        root.__csvRows = () => {
          const rows = [['family', 'family_evaluated', 'adapter', 'adapter_version', 'suite', 'asr', 'asr_ci95_lo', 'asr_ci95_hi',
            'refusal_rate', 'refusal_rate_ci95_lo', 'refusal_rate_ci95_hi', 'n', 'n_eligible', 'flip_direction_counts_json']];
          for (const f of fams) for (const rr of suiteRuns) {
            const pfAll = rr.metrics.per_family || {};
            const p = pfAll[f] || {};
            rows.push([f, familyEvaluated(pfAll[f]), rr.adapter_name, rr.adapter_version, rr.suite, p.asr,
              p.asr_ci95 && p.asr_ci95[0], p.asr_ci95 && p.asr_ci95[1],
              p.refusal_rate, p.refusal_rate_ci95 && p.refusal_rate_ci95[0], p.refusal_rate_ci95 && p.refusal_rate_ci95[1],
              p.n, p.n_eligible, JSON.stringify(p.flip_direction_counts || {})]);
          }
          return rows;
        };
      }
      detailEl.innerHTML = dHtml;
      root.querySelector('#fam-name').textContent = state.family;
      renderMatrix(run);
    };

    bindSuiteToggle(root, state, render);
    selAdapter.addEventListener('change', (e) => { state.adapter = e.target.value; writeState(state); render(); });
    bindExport(root, () => null, () => 'peira-families-' + state.suite);
    copyLink(root);
    render();
  };

  /* ================= calibration ================= */
  const calibration = () => {
    const root = document.querySelector('[data-page="calibration"]');
    const state = readState({ suite: 'public', adapter: '' });
    const selAdapter = root.querySelector('#sel-adapter');
    const cardsEl = root.querySelector('#cal-cards');
    const svgWrap = root.querySelector('#cal-charts');

    const render = () => {
      const suiteRuns = runsForSuite(state.suite);
      if (!suiteRuns.some((r) => runId(r) === state.adapter)) state.adapter = suiteRuns.length ? runId(suiteRuns[0]) : '';
      selAdapter.innerHTML = suiteRuns.map((r) =>
        `<option value="${esc(runId(r))}"${runId(r) === state.adapter ? ' selected' : ''}>${esc(runLabel(r))}</option>`).join('');
      const run = findRun(state.adapter);
      if (!run) { cardsEl.innerHTML = ''; svgWrap.innerHTML = ''; return; }
      const m = run.metrics;
      const cal = m.calibration || {};
      const db = cal.delta_brier || {};

      cardsEl.innerHTML = '<div class="cards">' +
        `<div class="card"><div class="k">ECE, benign arm</div><div class="v">${num(cal.benign && cal.benign.ece, 4)}</div><div class="sub">expected calibration error, lower is better</div></div>` +
        `<div class="card"><div class="k">ECE, attacked arm</div><div class="v">${num(cal.attacked && cal.attacked.ece, 4)}</div><div class="sub">expected calibration error, lower is better</div></div>` +
        `<div class="card"><div class="k">Delta Brier, attacked minus benign</div><div class="v">${num(db.delta, 4)}</div><div class="sub">${ciText(db.ci95, false)}</div></div>` +
        `<div class="card"><div class="k">Confidence coverage</div><div class="v">${pct(cal.confidence_coverage)}</div><div class="sub">share of calls carrying a confidence value</div></div></div>`;

      const blocks = [
        ['Benign arm', (cal.reliability_bins || {}).benign],
        ['Attacked arm', (cal.reliability_bins || {}).attacked],
      ];
      svgWrap.innerHTML = '';
      const W = 560, H = 460, pad = { l: 56, r: 20, t: 16, b: 48 };
      for (const [title, block] of blocks) {
        const wrap = document.createElement('div');
        wrap.className = 'chart-wrap';
        const h = document.createElement('h3');
        h.textContent = 'Reliability diagram, ' + title.toLowerCase();
        const hint = document.createElement('p');
        hint.className = 'hint';
        hint.textContent = 'Each bubble is one equal-mass bin. Bubble area grows with bin size. Points on the diagonal are perfectly calibrated.';
        wrap.appendChild(h); wrap.appendChild(hint);
        if (!block || !block.sufficient || !block.bins) {
          const p = document.createElement('p');
          p.className = 'note';
          p.textContent = 'Withheld, fewer than 30 observations in this arm.';
          wrap.appendChild(p);
        } else {
          const svg = el('svg', { class: 'chart', width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': h.textContent }, wrap);
          const X = (x) => pad.l + x * (W - pad.l - pad.r);
          const Y = (y) => H - pad.b - y * (H - pad.t - pad.b);
          for (const g of [0, 0.25, 0.5, 0.75, 1]) {
            el('line', { x1: X(g), y1: Y(0), x2: X(g), y2: Y(1), class: 'grid' }, svg);
            el('line', { x1: X(0), y1: Y(g), x2: X(1), y2: Y(g), class: 'grid' }, svg);
            txt(svg, X(g), H - pad.b + 18, g.toFixed(2), { class: 'tick-label', 'text-anchor': 'middle' });
            txt(svg, pad.l - 10, Y(g) + 4, g.toFixed(2), { class: 'tick-label', 'text-anchor': 'end' });
          }
          const diag = el('line', { x1: X(0), y1: Y(0), x2: X(1), y2: Y(1), stroke: '#e8a33d', 'stroke-dasharray': '6 5', 'stroke-width': 1.5, opacity: 0.7 }, svg);
          diag.appendChild(document.createElementNS(NS, 'title')).textContent = 'Perfect calibration';
          const maxN = Math.max(...block.bins.map((b) => b.n), 1);
          for (const b of block.bins) {
            const c = el('circle', {
              cx: X(b.mean_forecast), cy: Y(b.mean_outcome),
              r: 5 + 16 * Math.sqrt(b.n / maxN),
              fill: '#7aa5e8', opacity: 0.75, stroke: '#101014', 'stroke-width': 1,
            }, svg);
            const t = document.createElementNS(NS, 'title');
            t.textContent = `forecast ${b.mean_forecast.toFixed(3)}, outcome ${b.mean_outcome.toFixed(3)}, n ${b.n}`;
            c.appendChild(t);
          }
          txt(svg, (W - pad.r + pad.l) / 2, H - 8, 'Mean forecast confidence', { class: 'axis-label', 'text-anchor': 'middle' });
          txt(svg, 14, (H - pad.b + pad.t) / 2, 'Mean outcome', { class: 'axis-label', 'text-anchor': 'middle', transform: `rotate(-90 14 ${(H - pad.b + pad.t) / 2})` });
        }
        svgWrap.appendChild(wrap);
      }

      root.__csvRows = () => {
        const rows = [['arm', 'adapter', 'adapter_version', 'suite', 'ece', 'bin_n', 'mean_forecast', 'mean_outcome', 'edge_lo', 'edge_hi']];
        for (const [arm, key] of [['benign', 'benign'], ['attacked', 'attacked']]) {
          const b = (cal.reliability_bins || {})[key] || {};
          const bins = b.bins || [];
          if (!bins.length) rows.push([arm, run.adapter_name, run.adapter_version, run.suite, cal[key] && cal[key].ece, '', '', '', '', '']);
          for (const bin of bins) rows.push([arm, run.adapter_name, run.adapter_version, run.suite, cal[key] && cal[key].ece, bin.n, bin.mean_forecast, bin.mean_outcome, bin.edge_lo, bin.edge_hi]);
        }
        return rows;
      };
    };

    bindSuiteToggle(root, state, render);
    selAdapter.addEventListener('change', (e) => { state.adapter = e.target.value; writeState(state); render(); });
    bindExport(root, () => svgWrap.querySelector('svg.chart'), () => 'peira-calibration-' + state.suite);
    copyLink(root);
    render();
  };

  /* ================= frontier ================= */
  const frontier = () => {
    const root = document.querySelector('[data-page="frontier"]');
    const state = readState({ suite: 'public', logx: '1' });
    const chartEl = root.querySelector('#frontier-chart');
    const noteEl = root.querySelector('#frontier-note');

    const render = () => {
      const suiteRuns = runsForSuite(state.suite);
      const pts = suiteRuns.map((r) => ({
        run: r,
        x: r.metrics.cost && r.metrics.cost.cost_per_1k_decisions,
        y: r.metrics.asr_conditional,
        size: r.metrics.latency_ms && r.metrics.latency_ms.overall && r.metrics.latency_ms.overall.p99,
      }));
      const usable = pts.filter((p) => p.x !== null && p.x !== undefined && p.y !== null && p.y !== undefined && p.x > 0);
      chartEl.innerHTML = '';

      const W = 860, H = 520, pad = { l: 64, r: 24, t: 20, b: 56 };
      const svg = el('svg', { class: 'chart', width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Cost versus robustness frontier' }, chartEl);
      const logx = state.logx === '1';
      const xs = usable.map((p) => p.x), ys = usable.map((p) => p.y);
      if (!usable.length) {
        noteEl.textContent = 'No runs in this suite carry cost data, so the frontier cannot be drawn. Cost appears once artifacts include pricing-table usage records.';
        root.__csvRows = () => [['adapter', 'adapter_version', 'suite', 'cost_per_1k_usd', 'asr_conditional', 'p99_latency_ms']];
        return;
      }
      noteEl.textContent = 'Lower and left is better. Lower attack success rate at lower cost. Bubble area grows with p99 latency.';
      const xMin = Math.min(...xs), xMax = Math.max(...xs);
      const yMin = 0, yMax = Math.max(...ys) * 1.15 || 1;
      const X = (x) => {
        const t = logx ? (Math.log10(x) - Math.log10(xMin)) / (Math.log10(xMax) - Math.log10(xMin) || 1)
                       : (x - xMin) / ((xMax - xMin) || 1);
        return pad.l + t * (W - pad.l - pad.r);
      };
      const Y = (y) => H - pad.b - ((y - yMin) / ((yMax - yMin) || 1)) * (H - pad.t - pad.b);
      const maxSize = Math.max(...usable.map((p) => p.size || 0), 1);

      const ticks = 5;
      for (let i = 0; i <= ticks; i++) {
        const frac = i / ticks;
        const xv = logx ? xMin * Math.pow(xMax / xMin, frac) : xMin + frac * (xMax - xMin);
        const yv = yMin + frac * (yMax - yMin);
        el('line', { x1: X(xv), y1: Y(yMin), x2: X(xv), y2: Y(yMax), class: 'grid' }, svg);
        el('line', { x1: X(xMin), y1: Y(yv), x2: X(xMax), y2: Y(yv), class: 'grid' }, svg);
        txt(svg, X(xv), H - pad.b + 18, logx ? (xv >= 1000 ? (xv / 1000).toFixed(1) + 'k' : xv.toFixed(2)) : xv.toFixed(2), { class: 'tick-label', 'text-anchor': 'middle' });
        txt(svg, pad.l - 10, Y(yv) + 4, (yv * 100).toFixed(0) + '%', { class: 'tick-label', 'text-anchor': 'end' });
      }
      txt(svg, (W + pad.l - pad.r) / 2, H - 8, 'Cost per 1,000 decisions (USD)' + (logx ? ', log scale' : ''), { class: 'axis-label', 'text-anchor': 'middle' });
      txt(svg, 16, (H - pad.b + pad.t) / 2, 'Conditional ASR', { class: 'axis-label', 'text-anchor': 'middle', transform: `rotate(-90 16 ${(H - pad.b + pad.t) / 2})` });

      usable.forEach((p, i) => {
        const color = PALETTE[i % PALETTE.length];
        const c = el('circle', {
          cx: X(p.x), cy: Y(p.y),
          r: 8 + 20 * Math.sqrt((p.size || 0) / maxSize),
          fill: color, opacity: 0.7, stroke: '#101014', 'stroke-width': 1.5,
        }, svg);
        const t = document.createElementNS(NS, 'title');
        t.textContent = `${runLabel(p.run)}, cost $${p.x.toFixed(2)} per 1k, ASR ${pct(p.y)}, p99 ${ms(p.size)}`;
        c.appendChild(t);
        txt(svg, X(p.x), Y(p.y) - 14 - 20 * Math.sqrt((p.size || 0) / maxSize), shortName(p.run.adapter_name), { class: 'point-label', 'text-anchor': 'middle' });
      });

      root.__csvRows = () => {
        const rows = [['adapter', 'adapter_version', 'suite', 'cost_per_1k_usd', 'asr_conditional', 'asr_ci95_lo', 'asr_ci95_hi', 'p99_latency_ms']];
        for (const p of pts) rows.push([p.run.adapter_name, p.run.adapter_version, p.run.suite, p.x, p.y,
          p.run.metrics.asr_ci95 && p.run.metrics.asr_ci95[0], p.run.metrics.asr_ci95 && p.run.metrics.asr_ci95[1], p.size]);
        return rows;
      };
    };

    bindSuiteToggle(root, state, render);
    const logChk = root.querySelector('#logx');
    logChk.checked = state.logx === '1';
    logChk.addEventListener('change', (e) => { state.logx = e.target.checked ? '1' : '0'; writeState(state); render(); });
    bindExport(root, () => chartEl.querySelector('svg.chart'), () => 'peira-frontier-' + state.suite);
    copyLink(root);
    render();
  };

  /* ================= compare ================= */
  const compare = () => {
    const root = document.querySelector('[data-page="compare"]');
    const state = readState({ suite: 'public', a: '', b: '' });
    const selA = root.querySelector('#sel-a');
    const selB = root.querySelector('#sel-b');
    const outEl = root.querySelector('#compare-out');

    const fillSelects = (suiteRuns) => {
      const opts = suiteRuns.map((r) => `<option value="${esc(runId(r))}">${esc(runLabel(r))}</option>`).join('');
      selA.innerHTML = opts; selB.innerHTML = opts;
      if (!suiteRuns.some((r) => runId(r) === state.a)) state.a = suiteRuns[0] ? runId(suiteRuns[0]) : '';
      if (!suiteRuns.some((r) => runId(r) === state.b)) state.b = suiteRuns[1] ? runId(suiteRuns[1]) : state.a;
      selA.value = state.a; selB.value = state.b;
    };

    const render = () => {
      const suiteRuns = runsForSuite(state.suite);
      fillSelects(suiteRuns);
      const ra = findRun(state.a), rb = findRun(state.b);
      if (!ra || !rb) { outEl.innerHTML = '<p class="note">Pick two runs to compare.</p>'; return; }
      const ma = ra.metrics, mb = rb.metrics;

      const mapB = new Map((rb.cases || []).map((c) => [c.case_id, c]));
      let both = 0, aOnly = 0, bOnly = 0, neither = 0, n = 0;
      const discord = [];
      for (const ca of ra.cases || []) {
        const cb = mapB.get(ca.case_id);
        if (!cb) continue;
        n++;
        const fa = !!ca.flipped, fb = !!cb.flipped;
        if (fa && fb) both++;
        else if (fa) { aOnly++; discord.push([ca, cb, 'A']); }
        else if (fb) { bOnly++; discord.push([ca, cb, 'B']); }
        else neither++;
      }
      const agree = n ? (both + neither) / n : null;
      const dAsr = (ma.asr_conditional !== null && mb.asr_conditional !== null)
        ? ma.asr_conditional - mb.asr_conditional : null;

      let html = '<div class="cards">' +
        `<div class="card"><div class="k">Shared cases</div><div class="v">${num(n)}</div><div class="sub">joined on case id</div></div>` +
        `<div class="card"><div class="k">Flip agreement</div><div class="v">${pct(agree)}</div><div class="sub">cases where both runs agree on flipped or not</div></div>` +
        `<div class="card"><div class="k">Both flipped</div><div class="v">${num(both)}</div><div class="sub">A only ${num(aOnly)}, B only ${num(bOnly)}</div></div>` +
        `<div class="card"><div class="k">ASR delta, A minus B</div><div class="v">${dAsr === null ? 'withheld' : (dAsr >= 0 ? '+' : '') + (dAsr * 100).toFixed(1) + ' pts'}</div><div class="sub">A ${pct(ma.asr_conditional)} ${ciText(ma.asr_ci95)} · B ${pct(mb.asr_conditional)} ${ciText(mb.asr_ci95)}</div></div></div>`;

      const shown = discord.slice(0, 200);
      html += '<h3 style="margin:20px 0 8px">Discordant cases' + (discord.length > 200 ? ', first 200 of ' + discord.length : '') + '</h3>' +
        '<div class="table-scroll"><table class="board" style="min-width:860px"><thead><tr>' +
        '<th class="no-sort">Case</th><th class="no-sort">Family</th><th class="no-sort">Severity</th>' +
        '<th class="no-sort">A flipped</th><th class="no-sort">B flipped</th><th class="no-sort">A benign to attacked</th><th class="no-sort">B benign to attacked</th>' +
        '</tr></thead><tbody>' +
        shown.map(([ca, cb]) =>
          `<tr><td class="mono">${esc(ca.case_id)}</td><td class="mono">${esc(ca.family)}</td><td>${esc(ca.severity)}</td>` +
          `<td>${ca.flipped ? '<span class="badge warn">flipped</span>' : 'no'}</td>` +
          `<td>${cb.flipped ? '<span class="badge warn">flipped</span>' : 'no'}</td>` +
          `<td class="mono">${esc(ca.benign_decision)} to ${esc(ca.attacked_decision)}</td>` +
          `<td class="mono">${esc(cb.benign_decision)} to ${esc(cb.attacked_decision)}</td></tr>`).join('') +
        '</tbody></table></div>' +
        '<p class="note">Positive ASR delta means run A flips more often than run B. ' + (MOCK ? 'Mock values.' : '') + '</p>';
      outEl.innerHTML = html;

      root.__csvRows = () => {
        const rows = [['case_id', 'family', 'severity', 'a_flipped', 'b_flipped', 'a_benign_decision', 'a_attacked_decision', 'b_benign_decision', 'b_attacked_decision']];
        for (const [ca, cb] of discord) rows.push([ca.case_id, ca.family, ca.severity, ca.flipped, cb.flipped, ca.benign_decision, ca.attacked_decision, cb.benign_decision, cb.attacked_decision]);
        return rows;
      };
    };

    bindSuiteToggle(root, state, render);
    selA.addEventListener('change', (e) => { state.a = e.target.value; writeState(state); render(); });
    selB.addEventListener('change', (e) => { state.b = e.target.value; writeState(state); render(); });
    // Bound once: render() only refreshes root.__csvRows, so a single
    // click listener can never stack into duplicate downloads.
    bindExport(root, () => null, () => 'peira-compare-' + state.suite);
    copyLink(root);
    render();
  };

  /* ================= cases ================= */
  const casesPage = () => {
    const root = document.querySelector('[data-page="cases"]');
    const state = readState({ suite: 'public', run: '', q: '', family: '', severity: '', flipped: '', eligible: '', p: '1' });
    const PER_PAGE = 50;
    const selRun = root.querySelector('#sel-run');
    const qEl = root.querySelector('#q');
    const famEl = root.querySelector('#sel-family');
    const sevEl = root.querySelector('#sel-severity');
    const flipEl = root.querySelector('#sel-flipped');
    const eligEl = root.querySelector('#sel-eligible');
    const outEl = root.querySelector('#cases-out');
    const pagerEl = root.querySelector('#cases-pager');

    const render = () => {
      const suiteRuns = runsForSuite(state.suite);
      if (!suiteRuns.some((r) => runId(r) === state.run)) state.run = suiteRuns.length ? runId(suiteRuns[0]) : '';
      selRun.innerHTML = suiteRuns.map((r) =>
        `<option value="${esc(runId(r))}"${runId(r) === state.run ? ' selected' : ''}>${esc(runLabel(r))}</option>`).join('');
      const run = findRun(state.run);
      const cases = (run && run.cases) || [];

      const fams = [...new Set(cases.map((c) => c.family))].sort();
      const sevs = [...new Set(cases.map((c) => c.severity))].sort();
      const fill = (sel, values, cur) => {
        sel.innerHTML = '<option value="">All</option>' + values.map((v) => `<option${v === cur ? ' selected' : ''}>${esc(v)}</option>`).join('');
      };
      fill(famEl, fams, state.family);
      fill(sevEl, sevs, state.severity);
      if (!['', 'yes', 'no'].includes(state.flipped)) state.flipped = '';
      if (!['', 'yes', 'no'].includes(state.eligible)) state.eligible = '';
      flipEl.value = state.flipped; eligEl.value = state.eligible;
      qEl.value = state.q;

      const q = state.q.trim().toLowerCase();
      const filtered = cases.filter((c) =>
        (!state.family || c.family === state.family) &&
        (!state.severity || c.severity === state.severity) &&
        (!state.flipped || String(!!c.flipped) === String(state.flipped === 'yes')) &&
        (!state.eligible || String(!!c.eligible) === String(state.eligible === 'yes')) &&
        (!q || c.case_id.toLowerCase().includes(q)));

      const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));
      let p = Math.max(1, Math.min(totalPages, parseInt(state.p, 10) || 1));
      const slice = filtered.slice((p - 1) * PER_PAGE, p * PER_PAGE);

      outEl.innerHTML = '<div class="table-scroll"><table class="board" style="min-width:980px"><thead><tr>' +
        '<th class="no-sort">Case</th><th class="no-sort">Family</th><th class="no-sort">Severity</th><th class="no-sort">Primitive</th>' +
        '<th class="no-sort">Benign</th><th class="no-sort">Attacked</th><th class="no-sort">Flipped</th><th class="no-sort">Eligible</th>' +
        '</tr></thead><tbody>' +
        slice.map((c) =>
          `<tr><td class="mono">${esc(c.case_id)}</td><td class="mono">${esc(c.family)}</td><td>${esc(c.severity)}</td>` +
          `<td class="mono">${esc(c.primitive || '')}</td><td class="mono">${esc(c.benign_decision)}</td><td class="mono">${esc(c.attacked_decision)}</td>` +
          `<td>${c.flipped ? '<span class="badge warn">yes</span>' : 'no'}</td>` +
          `<td>${c.eligible ? 'yes' : '<span class="faint">no</span>'}</td></tr>`).join('') +
        '</tbody></table></div>';
      pagerEl.innerHTML = `<button class="btn" id="pg-prev"${p <= 1 ? ' disabled' : ''}>Previous</button>` +
        `<span>Page ${p} of ${totalPages}, ${filtered.length.toLocaleString('en-US')} cases</span>` +
        `<button class="btn" id="pg-next"${p >= totalPages ? ' disabled' : ''}>Next</button>`;
      const prev = pagerEl.querySelector('#pg-prev'), next = pagerEl.querySelector('#pg-next');
      if (prev) prev.addEventListener('click', () => { state.p = String(p - 1); writeState(state); render(); });
      if (next) next.addEventListener('click', () => { state.p = String(p + 1); writeState(state); render(); });

      root.__csvRows = () => {
        const rows = [['case_id', 'family', 'severity', 'primitive', 'benign_decision', 'attacked_decision', 'flipped', 'eligible', 'adapter', 'adapter_version', 'suite']];
        for (const c of filtered) rows.push([c.case_id, c.family, c.severity, c.primitive, c.benign_decision, c.attacked_decision, c.flipped, c.eligible, run.adapter_name, run.adapter_version, run.suite]);
        return rows;
      };
    };

    const debounced = (() => {
      let t; return (fn) => { clearTimeout(t); t = setTimeout(fn, 220); };
    })();
    const onFilter = () => {
      state.q = qEl.value; state.family = famEl.value; state.severity = sevEl.value;
      state.flipped = flipEl.value; state.eligible = eligEl.value; state.p = '1';
      writeState(state); render();
    };
    bindSuiteToggle(root, state, render);
    selRun.addEventListener('change', (e) => { state.run = e.target.value; state.p = '1'; writeState(state); render(); });
    qEl.addEventListener('input', () => debounced(onFilter));
    [famEl, sevEl, flipEl, eligEl].forEach((s) => s.addEventListener('change', onFilter));
    // Bound once: render() only refreshes root.__csvRows, so a single
    // click listener can never stack into duplicate downloads.
    bindExport(root, () => null, () => 'peira-cases-' + state.suite);
    copyLink(root);
    render();
  };

  /* ================= dispatch ================= */
  // Deferred-module safe: run exactly once, whether the script executed
  // during parsing or after (Astro bundles this as a deferred module).
  const pages = { leaderboard, families, calibration, frontier, compare, cases: casesPage };
  if (pages[page]) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', pages[page], { once: true });
    else pages[page]();
  }
})();
