"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  CHART_X_AXIS_TITLE,
  chartAriaLabelText,
  chartYAxisTitleText,
  countLineText,
  deltaWord,
  EMPTY_CHART_TEXT,
  EMPTY_RANK_TEXT,
  FLAGGED_DIVIDER,
  flagLineLabelText,
  flagNoteText,
  GUARD_DIVIDER,
  offScaleNoteText,
  railNoteText,
  trayDeltaText,
  type ExplorerData,
  type XRow,
} from "@/lib/explorerData";
import { asrAxisFor } from "@/lib/chart";
import {
  fmtDeltaPct,
  fmtDeltaUsd,
  fmtInt,
  fmtPct,
  fmtUsd,
} from "@/lib/format";

/**
 * The explorer. One surface absorbs the board's ranking, models,
 * and compare. Its state lives in the URL hash, so a model
 * address is the explorer opened with its result selected.
 * Charts here are computed in the browser from the payload
 * figures passed in as data. Nothing about the geometry is
 * baked on the server.
 */

type Pop = "all" | "full" | "guards" | "flagged";
type Mode = "rank" | "chart" | "families";
type Measure = "asr" | "malformed";

interface XState {
  pop: Pop;
  mode: Mode;
  sort: string;
  vendor: string;
  cost: string;
  q: string;
  sel: string | null;
  pin: string | null;
  frontier: boolean;
  grey: "vendor" | "wire" | "band" | "none";
  measure: Measure;
}

interface Brush {
  costLo: number;
  costHi: number;
  vLo: number;
  vHi: number;
  field: Measure;
}

const DEFAULTS: XState = {
  pop: "all",
  mode: "rank",
  sort: "asr",
  vendor: "all",
  cost: "all",
  q: "",
  sel: null,
  pin: null,
  frontier: false,
  grey: "vendor",
  measure: "asr",
};

function Mark({ row, size = 26 }: { row: XRow; size?: number }) {
  const m = row.mark;
  return (
    <span
      className="xmark"
      style={{ width: size, height: size, background: m.color }}
      aria-hidden="true"
    >
      {m.kind === "logo" && m.slug ? (
        <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24">
          <use href={`#vlogo-${m.slug}`} style={{ color: m.glyph }} />
        </svg>
      ) : (
        <span className="xmark-letter" style={{ color: m.glyph }}>
          {m.letter}
        </span>
      )}
    </span>
  );
}

/**
 * One result's family bars on the board's shared family axis.
 * A flagged result's family figures carry their own
 * decompositions beside them, and a flagged family whose
 * records derive none prints suppressed and no figure (C-5).
 * Hovering or focusing a bar lights the same family in every
 * reading on the surface.
 */
function FamilyBars({
  row,
  axis,
  famHover,
  setFamHover,
}: {
  row: XRow;
  axis: number;
  famHover: string | null;
  setFamHover: (key: string | null) => void;
}) {
  return (
    <div className="xfam-bars">
      {row.families.map((fam) => (
        <div
          className={`xfam-bar${famHover === fam.key ? " hot" : ""}${
            famHover !== null && famHover !== fam.key ? " dim" : ""
          }`}
          key={fam.key}
          onPointerEnter={() => setFamHover(fam.key)}
          onPointerLeave={() => setFamHover(null)}
        >
          <span className="xfam-label">{fam.short}</span>
          <span className="xfam-track">
            {fam.asr !== null && !fam.suppressed && (
              <span
                className="xfam-fill"
                style={{ width: `${Math.min(100, (fam.asr / axis) * 100)}%` }}
              />
            )}
          </span>
          <span className="xfam-val rn">
            {fam.suppressed
              ? "suppressed"
              : fam.asr !== null
                ? fmtPct(fam.asr)
                : "·"}
          </span>
          {fam.decomp !== null && (
            <span className="xfam-decomp">
              genuine {fam.decomp.genuineText} · malformed {fam.decomp.shareText}{" "}
              of counted flips
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * The reliability plot for one result, drawn from its sealed
 * calibration bins. The diagonal is perfect calibration, and
 * each point is one bin, sized by the bin's case count.
 */
function CalibrationPanel({ row }: { row: XRow }) {
  if (row.calibration === null) return null;
  const cal = row.calibration;
  const S = 148;
  const px = (v: number) => 10 + v * (S - 20);
  const py = (v: number) => S - 10 - v * (S - 20);
  return (
    <div className="calib">
      <p className="micro">Calibration, attacked calls</p>
      <svg
        viewBox={`0 0 ${S} ${S}`}
        className="calib-svg"
        role="img"
        aria-label={`Reliability plot for ${row.name}, forecast against outcome over ${cal.bins.length} bins`}
      >
        <line
          x1={px(0)}
          y1={py(0)}
          x2={px(1)}
          y2={py(1)}
          className="calib-diag"
        />
        {cal.bins.map((b, i) => (
          <circle
            key={i}
            cx={px(Math.min(1, Math.max(0, b.x)))}
            cy={py(Math.min(1, Math.max(0, b.y)))}
            r={2 + Math.min(5, Math.sqrt(Math.max(0, b.n)) / 2)}
            className="calib-dot"
          />
        ))}
      </svg>
      <p className="rsub">
        Error {cal.eceText} · Brier {cal.brierText}
      </p>
    </div>
  );
}

function ReadingBody({
  row,
  famAxis,
  famHover,
  setFamHover,
}: {
  row: XRow;
  famAxis: number;
  famHover: string | null;
  setFamHover: (key: string | null) => void;
}) {
  const d = row.decompLine;
  return (
    <div className="reading-body">
      <p className="reading-rank micro">{row.rankLine}</p>
      <div className="reading-figs">
        <div>
          <span className="micro">{row.asrLabel}</span>
          <strong>{row.suppressed ? "suppressed" : (row.asrText ?? "·")}</strong>
          {row.ciText && <span className="rsub">{row.ciText}</span>}
        </div>
        <div>
          <span className="micro">Benign accuracy</span>
          <strong>{row.benignText ?? "·"}</strong>
          {row.benignBestLine && (
            <span className="rsub">{row.benignBestLine}</span>
          )}
        </div>
        <div>
          <span className="micro">Malformed output</span>
          <strong>{row.malformedText ?? "·"}</strong>
        </div>
        <div>
          <span className="micro">Calibration error</span>
          <strong>{row.eceText ?? "·"}</strong>
        </div>
        <div>
          <span className="micro">Cost of one run</span>
          <strong>{row.costText}</strong>
          {row.costSub && <span className="rsub">{row.costSub}</span>}
        </div>
        <div>
          <span className="micro">Latency</span>
          <strong>{row.latencyText ?? "·"}</strong>
        </div>
      </div>
      {d && <p className="reading-line">{d}</p>}
      <div className="reading-cols">
        <div className="reading-fams">
          <p className="micro">Attack success by family</p>
          <FamilyBars
            row={row}
            axis={famAxis}
            famHover={famHover}
            setFamHover={setFamHover}
          />
        </div>
        <CalibrationPanel row={row} />
      </div>
      {row.weakestLine && (
        <p className="reading-line">{row.weakestLine}</p>
      )}
      {row.severities.length > 0 && (
        <p className="reading-line">
          {row.severities
            .map(
              (s) =>
                `${s.label} ${s.flipText ?? "no rate"}${s.baseText ? ` over ${s.baseText}` : ""}`,
            )
            .join(" · ")}
        </p>
      )}
      {row.taxText && (
        <p className="reading-line">
          Robustness tax <span className="rn">{row.taxText}</span>.{" "}
          {row.taxBenchLine}
        </p>
      )}
      {row.flaggedReason && (
        <p className="reading-line flagged-line">{row.flaggedReason}</p>
      )}
      {row.sliceNote && <p className="reading-line">{row.sliceNote}</p>}
      {row.unanswered && <p className="reading-line">{row.unanswered}</p>}
      {row.singleCall && <p className="reading-line">{row.singleCall}</p>}
      <p className="reading-prov">{row.provenanceLine}</p>
      {row.rerunText && <p className="reading-prov">{row.rerunText}</p>}
    </div>
  );
}

function deltaText(
  a: number | null,
  b: number | null,
  fmt: (v: number) => string,
): string {
  if (a === null || b === null) return "Not comparable";
  const formatted = fmt(b - a);
  return `${formatted} · ${deltaWord(formatted)}`;
}

function CompareReading({
  sel,
  pin,
  famAxis,
  famHover,
  setFamHover,
  onClose,
}: {
  sel: XRow;
  pin: XRow;
  famAxis: number;
  famHover: string | null;
  setFamHover: (key: string | null) => void;
  onClose: () => void;
}) {
  const rows: Array<[string, string, string, string]> = [
    [
      sel.asrLabel,
      sel.suppressed ? "suppressed" : (sel.asrText ?? "·"),
      pin.suppressed ? "suppressed" : (pin.asrText ?? "·"),
      deltaText(sel.asr, pin.asr, (v) => fmtDeltaPct(v)),
    ],
    [
      "Benign accuracy",
      sel.benignText ?? "·",
      pin.benignText ?? "·",
      deltaText(sel.benign, pin.benign, (v) => fmtDeltaPct(v)),
    ],
    [
      "Malformed output",
      sel.malformedText ?? "·",
      pin.malformedText ?? "·",
      deltaText(sel.malformed, pin.malformed, (v) => fmtDeltaPct(v)),
    ],
    [
      "Cost of one run",
      sel.costText,
      pin.costText,
      sel.costValue !== null && pin.costValue !== null
        ? (() => {
            const formatted = fmtDeltaUsd(pin.costValue - sel.costValue);
            return `${formatted} · ${deltaWord(formatted)}`;
          })()
        : "Not comparable",
    ],
  ];
  return (
    <div className="compare-reading">
      <div className="compare-head">
        <span className="micro">Comparison</span>
        <button type="button" className="ghostbtn" onClick={onClose}>
          Unpin
        </button>
      </div>
      <div className="compare-cols">
        <div className="compare-side">
          <p className="compare-name">
            <Mark row={sel} size={20} /> {sel.name}
            {sel.wire ? ` · ${sel.wire}` : ""}
          </p>
          <ReadingBody
            row={sel}
            famAxis={famAxis}
            famHover={famHover}
            setFamHover={setFamHover}
          />
        </div>
        <div className="compare-deltas" aria-label="Differences, pinned result against selected result">
          {rows.map(([label, a, b, delta]) => (
            <div className="delta-row" key={label}>
              <span className="micro">{label}</span>
              <span className="delta-pair">
                {a} → {b}
              </span>
              <strong>{delta}</strong>
            </div>
          ))}
        </div>
        <div className="compare-side">
          <p className="compare-name">
            <Mark row={pin} size={20} /> {pin.name}
            {pin.wire ? ` · ${pin.wire}` : ""}
          </p>
          <ReadingBody
            row={pin}
            famAxis={famAxis}
            famHover={famHover}
            setFamHover={setFamHover}
          />
        </div>
      </div>
    </div>
  );
}

const COST_BANDS: Array<{ key: string; label: string; test: (c: number | null) => boolean }> = [
  { key: "all", label: "Any cost", test: () => true },
  { key: "priced", label: "Priced only", test: (c) => c !== null && c > 0 },
  { key: "under1", label: "Under $1", test: (c) => c !== null && c > 0 && c < 1 },
  { key: "mid", label: "$1 to $10", test: (c) => c !== null && c >= 1 && c < 10 },
  { key: "over10", label: "$10 and up", test: (c) => c !== null && c >= 10 },
  { key: "nocost", label: "No recorded cost", test: (c) => c === null || c === 0 },
];

function sortValue(row: XRow, sort: string): number | null {
  switch (sort) {
    case "asr":
      return row.asr;
    case "benign":
      return row.benign;
    case "malformed":
      return row.malformed;
    case "ece":
      return row.ece;
    case "cost":
      return row.costValue !== null && row.costValue > 0 ? row.costValue : null;
    default:
      if (sort.startsWith("fam:")) {
        const key = sort.slice(4);
        return row.families.find((f) => f.key === key)?.asr ?? null;
      }
      return row.asr;
  }
}

const SORT_DIR: Record<string, 1 | -1> = {
  asr: 1,
  benign: -1,
  malformed: -1,
  ece: 1,
  cost: 1,
};

function sortRows(rows: XRow[], sort: string): XRow[] {
  const dir = sort.startsWith("fam:") ? 1 : (SORT_DIR[sort] ?? 1);
  return [...rows].sort((a, b) => {
    const va = sortValue(a, sort);
    const vb = sortValue(b, sort);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    return (va - vb) * dir;
  });
}

export default function Explorer({ data }: { data: ExplorerData }) {
  const byId = useMemo(
    () => new Map(data.rows.map((r) => [r.runId, r])),
    [data],
  );
  const bySlug = useMemo(
    () => new Map(data.rows.map((r) => [r.slug, r])),
    [data],
  );
  const leader = useMemo(
    () => data.rows.find((r) => r.kind === "full"),
    [data],
  );
  const [state, setState] = useState<XState>({
    ...DEFAULTS,
    sel: leader?.runId ?? null,
  });
  const [expanded, setExpanded] = useState<string | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [chipId, setChipId] = useState<string | null>(null);
  const [brush, setBrush] = useState<Brush | null>(null);
  const [famHover, setFamHover] = useState<string | null>(null);
  const touched = useRef(false);
  const prevVisibleRef = useRef<Set<string> | null>(null);
  const prevModeRef = useRef<Mode | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const flipSnapshot = useRef<Map<string, number> | null>(null);
  const sectionRef = useRef<HTMLElement>(null);

  const parseHash = useCallback((): { patch: Partial<XState>; open: boolean } => {
    const hash = window.location.hash.replace(/^#/, "");
    const patch: Partial<XState> = {};
    let open = false;
    if (hash.startsWith("result=")) {
      const row = bySlug.get(decodeURIComponent(hash.slice(7)));
      if (row) {
        patch.sel = row.runId;
        patch.pop =
          row.kind === "slice" ? "guards" : row.kind === "flagged" ? "flagged" : "full";
        open = true;
      }
      return { patch, open };
    }
    const qIndex = hash.indexOf("?");
    if (qIndex < 0) return { patch, open };
    const params = new URLSearchParams(hash.slice(qIndex + 1));
    const pop = params.get("pop");
    if (pop === "all" || pop === "full" || pop === "guards" || pop === "flagged") {
      patch.pop = pop;
    }
    const mode = params.get("mode");
    if (mode === "rank" || mode === "chart" || mode === "families") {
      patch.mode = mode;
    }
    const sort = params.get("sort");
    if (sort) patch.sort = sort;
    const vendor = params.get("vendor");
    if (vendor) patch.vendor = vendor;
    const cost = params.get("cost");
    if (cost) patch.cost = cost;
    const q = params.get("q");
    if (q !== null) patch.q = q;
    const selSlug = params.get("sel");
    if (selSlug) {
      const row = bySlug.get(selSlug);
      if (row) patch.sel = row.runId;
    }
    const pinSlug = params.get("pin");
    if (pinSlug) {
      const row = bySlug.get(pinSlug);
      if (row) patch.pin = row.runId;
    }
    if (params.get("frontier") === "1") patch.frontier = true;
    const measure = params.get("measure");
    if (measure === "malformed" || measure === "asr") {
      patch.measure = measure;
    }
    const grey = params.get("grey");
    if (grey === "vendor" || grey === "wire" || grey === "band" || grey === "none") {
      patch.grey = grey;
    }
    open = params.get("open") === "1";
    return { patch, open };
  }, [bySlug]);

  useEffect(() => {
    /* A hash application is a landing, not an edit. A finding
     * action and a model address each promise a whole state,
     * so the state they do not name returns to its default,
     * the brush and the chart chip clear, and an expansion
     * stands only where the link itself opens one. The
     * reader's own control changes go through update() and
     * keep their merge behavior. */
    const apply = (scroll: boolean, mount = false) => {
      const { patch, open } = parseHash();
      if (Object.keys(patch).length === 0) return;
      setState({ ...DEFAULTS, sel: leader?.runId ?? null, ...patch });
      setBrush(null);
      setChipId(null);
      setExpanded(open && patch.sel ? patch.sel : null);
      if (scroll || (mount && patch.sel)) {
        sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    };
    apply(false, true);
    const onHash = () => apply(true);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [parseHash, leader]);

  useEffect(() => {
    if (!touched.current) return;
    const params = new URLSearchParams();
    if (state.pop !== DEFAULTS.pop) params.set("pop", state.pop);
    if (state.mode !== DEFAULTS.mode) params.set("mode", state.mode);
    if (state.sort !== DEFAULTS.sort) params.set("sort", state.sort);
    if (state.vendor !== "all") params.set("vendor", state.vendor);
    if (state.cost !== "all") params.set("cost", state.cost);
    if (state.q) params.set("q", state.q);
    const selRow = state.sel ? byId.get(state.sel) : null;
    if (selRow) params.set("sel", selRow.slug);
    const pinRow = state.pin ? byId.get(state.pin) : null;
    if (pinRow) params.set("pin", pinRow.slug);
    if (state.frontier) params.set("frontier", "1");
    if (state.measure !== DEFAULTS.measure) {
      params.set("measure", state.measure);
    }
    if (state.grey !== DEFAULTS.grey) params.set("grey", state.grey);
    if (expanded !== null && expanded === state.sel) {
      params.set("open", "1");
    }
    const qs = params.toString();
    const target = qs ? `#explorer?${qs}` : "#explorer";
    if (window.location.hash !== target) {
      window.history.replaceState(null, "", target);
    }
  }, [state, byId, expanded]);

  const snapshotFlip = useCallback(() => {
    const root = listRef.current;
    if (!root) return;
    const map = new Map<string, number>();
    root.querySelectorAll<HTMLElement>("[data-rid]").forEach((el) => {
      map.set(el.dataset.rid as string, el.getBoundingClientRect().top);
    });
    flipSnapshot.current = map;
  }, []);

  useLayoutEffect(() => {
    const snap = flipSnapshot.current;
    if (!snap || !listRef.current) return;
    flipSnapshot.current = null;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    listRef.current
      .querySelectorAll<HTMLElement>("[data-rid]")
      .forEach((el) => {
        const before = snap.get(el.dataset.rid as string);
        if (before === undefined) return;
        const delta = before - el.getBoundingClientRect().top;
        if (delta === 0) return;
        if (reduce) return;
        el.style.transition = "none";
        el.style.transform = `translateY(${delta}px)`;
        requestAnimationFrame(() => {
          el.style.transition = "transform 200ms ease";
          el.style.transform = "";
        });
      });
  });

  const update = useCallback(
    (patch: Partial<XState>, flip = false) => {
      touched.current = true;
      if (flip) snapshotFlip();
      setState((s) => ({ ...s, ...patch }));
    },
    [snapshotFlip],
  );

  const visible = useMemo(() => {
    const band = COST_BANDS.find((b) => b.key === state.cost) ?? COST_BANDS[0];
    const query = state.q.trim().toLowerCase();
    return data.rows.filter((row) => {
      if (state.pop === "full" && row.kind !== "full") return false;
      if (state.pop === "guards" && row.kind !== "slice") return false;
      if (state.pop === "flagged" && row.kind !== "flagged") return false;
      if (state.vendor !== "all" && row.vendorKey !== state.vendor) return false;
      if (!band.test(row.costValue)) return false;
      if (
        query &&
        !`${row.name} ${row.wire ?? ""} ${row.vendorLabel}`
          .toLowerCase()
          .includes(query)
      ) {
        return false;
      }
      if (brush) {
        const v = brush.field === "malformed" ? row.malformed : row.asr;
        if (v === null || row.costValue === null) return false;
        if (row.costValue < brush.costLo || row.costValue > brush.costHi) return false;
        if (v < brush.vLo || v > brush.vHi) return false;
      }
      return true;
    });
  }, [data, state, brush]);

  const groups = useMemo(() => {
    if (state.pop !== "all") return [{ kind: "one" as const, rows: sortRows(visible, state.sort) }];
    return [
      { kind: "full" as const, rows: sortRows(visible.filter((r) => r.kind === "full"), state.sort) },
      { kind: "slice" as const, rows: sortRows(visible.filter((r) => r.kind === "slice"), state.sort) },
      { kind: "flagged" as const, rows: sortRows(visible.filter((r) => r.kind === "flagged"), state.sort) },
    ].filter((g) => g.rows.length > 0);
  }, [visible, state]);

  const selRow = state.sel ? byId.get(state.sel) ?? null : null;
  const pinRow = state.pin ? byId.get(state.pin) ?? null : null;
  const hiddenCount = data.rows.length - visible.length;

  /* Motion bookkeeping (BUILD-SPEC part 6). Rows entering the
   * view carry the enter class for the commit that admits
   * them, and the mode wrapper animates only on the commit
   * that changes the mode, so first render stands still. */
  if (prevVisibleRef.current === null) {
    prevVisibleRef.current = new Set(data.rows.map((r) => r.runId));
  }
  const freshIds = new Set(
    visible
      .filter((r) => !prevVisibleRef.current!.has(r.runId))
      .map((r) => r.runId),
  );
  useEffect(() => {
    prevVisibleRef.current = new Set(visible.map((r) => r.runId));
  });
  /* The mode tracker adopts the mode the address already
   * names on first render, the same rule the row tracker
   * follows with the full row set above, so a shared link's
   * first paint stands still and only a reader's own switch
   * animates. */
  if (prevModeRef.current === null) {
    let initial: Mode = DEFAULTS.mode;
    if (typeof window !== "undefined") {
      const m = /[?&]mode=(rank|chart|families)/.exec(window.location.hash);
      if (m) initial = m[1] as Mode;
    }
    prevModeRef.current = initial;
  }
  const modeChanged = prevModeRef.current !== state.mode;
  useEffect(() => {
    prevModeRef.current = state.mode;
  }, [state.mode]);

  const toggleExpand = (row: XRow) => {
    update({ sel: row.runId });
    setExpanded((e) => (e === row.runId ? null : row.runId));
  };

  return (
    <section className="explorer" id="explorer" ref={sectionRef} aria-label="Explorer">
      <div className="sechead">
        <div className="micro">Explorer</div>
        <h2>Every result, one surface</h2>
        <p className="cap">
          Ranking, readings, and comparison live here, and a row
          opens its reading in place.
        </p>
      </div>

      <div className="xcontrols">
        <div className="segrow" role="group" aria-label="Population">
          {(
            [
              ["all", "All results"],
              ["full", "Full suite"],
              ["guards", "Guards"],
              ["flagged", "Flagged"],
            ] as Array<[Pop, string]>
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={state.pop === key ? "segbtn on" : "segbtn"}
              onClick={() => update({ pop: key }, true)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="segrow" role="group" aria-label="Mode">
          {(
            [
              ["rank", "Rank"],
              ["chart", "Chart"],
              ["families", "Families"],
            ] as Array<[Mode, string]>
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={state.mode === key ? "segbtn on" : "segbtn"}
              onClick={() => update({ mode: key })}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="xfield">
          <span className="micro">Vendor</span>
          <select
            value={state.vendor}
            onChange={(e) => update({ vendor: e.target.value }, true)}
          >
            <option value="all">All vendors</option>
            {data.vendors.map((v) => (
              <option key={v.key} value={v.key}>
                {v.label}
              </option>
            ))}
          </select>
        </label>
        <label className="xfield">
          <span className="micro">Cost</span>
          <select
            value={state.cost}
            onChange={(e) => update({ cost: e.target.value }, true)}
          >
            {COST_BANDS.map((b) => (
              <option key={b.key} value={b.key}>
                {b.label}
              </option>
            ))}
          </select>
        </label>
        <label className="xfield grow">
          <span className="micro">Search</span>
          <input
            type="search"
            value={state.q}
            placeholder="Model or wire"
            onChange={(e) => update({ q: e.target.value }, true)}
          />
        </label>
        <label className="xfield">
          <span className="micro">Sort</span>
          <select
            value={state.sort}
            onChange={(e) => update({ sort: e.target.value }, true)}
          >
            <option value="asr">Attack success</option>
            <option value="benign">Benign accuracy</option>
            <option value="malformed">Malformed output</option>
            <option value="ece">Calibration error</option>
            <option value="cost">Cost of one run</option>
            {data.familyKeys.map((key) => (
              <option key={key} value={`fam:${key}`}>
                Family · {data.familyNames[key]}
              </option>
            ))}
          </select>
        </label>
        {state.mode === "chart" && (
          <>
            <div className="segrow" role="group" aria-label="Measure">
              {(
                [
                  ["asr", "Attack success"],
                  ["malformed", "Malformed"],
                ] as Array<[Measure, string]>
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={state.measure === key ? "segbtn on" : "segbtn"}
                  onClick={() => update({ measure: key })}
                >
                  {label}
                </button>
              ))}
            </div>
            {state.measure === "asr" && (
              <label className="xcheck">
                <input
                  type="checkbox"
                  checked={state.frontier}
                  onChange={(e) => update({ frontier: e.target.checked })}
                />
                <span>Frontier</span>
              </label>
            )}
            <label className="xfield">
              <span className="micro">Highlight</span>
              <select
                value={state.grey}
                onChange={(e) =>
                  update({ grey: e.target.value as XState["grey"] })
                }
              >
                <option value="vendor">Selection's vendor</option>
                <option value="wire">Selection's wire</option>
                <option value="band">Selection's band</option>
                <option value="none">None</option>
              </select>
            </label>
          </>
        )}
      </div>

      {state.pop === "guards" && (
        <p className="basisline">{data.guardBasis}</p>
      )}
      <p className="xcount">
        {countLineText(visible.length, data.rows.length, hiddenCount, brush !== null)}
      </p>
      {brush && (
        <button
          type="button"
          className="ghostbtn"
          onClick={() => setBrush(null)}
        >
          Clear the brush filter
        </button>
      )}

      <div className={modeChanged ? "xview anim" : "xview"} key={state.mode}>
      {state.mode === "rank" && (
        <RankView
          groups={groups}
          state={state}
          expanded={expanded}
          selRow={selRow}
          pinRow={pinRow}
          listRef={listRef}
          famAxis={data.familiesAxis}
          famHover={famHover}
          setFamHover={setFamHover}
          freshIds={freshIds}
          onToggle={toggleExpand}
          onSort={(sort) => update({ sort }, true)}
          onPin={(id) => update({ pin: state.pin === id ? null : id })}
          onUnpin={() => update({ pin: null })}
        />
      )}
      {state.mode === "chart" && (
        <ChartView
          data={data}
          visible={visible}
          state={state}
          selRow={selRow}
          hoverId={hoverId}
          setHoverId={setHoverId}
          chipId={chipId}
          setChipId={setChipId}
          freshIds={freshIds}
          onSelect={(row) => {
            update({ sel: row.runId });
            setExpanded(row.runId);
          }}
          onBrush={(b) => setBrush(b)}
        />
      )}
      {state.mode === "families" && (
        <FamiliesView
          groups={groups}
          data={data}
          expanded={expanded}
          famHover={famHover}
          setFamHover={setFamHover}
          freshIds={freshIds}
          onToggle={toggleExpand}
          onSort={(sort) => update({ sort }, true)}
        />
      )}
      </div>
      {state.mode === "chart" && expanded && byId.get(expanded) && (
        <div className="belowreading">
          {pinRow && selRow && expanded === selRow.runId ? (
            <CompareReading
              sel={selRow}
              pin={pinRow}
              famAxis={data.familiesAxis}
              famHover={famHover}
              setFamHover={setFamHover}
              onClose={() => update({ pin: null })}
            />
          ) : (
            <div className="reading open">
              <ReadingBody
                row={byId.get(expanded) as XRow}
                famAxis={data.familiesAxis}
                famHover={famHover}
                setFamHover={setFamHover}
              />
            </div>
          )}
        </div>
      )}

      {pinRow && selRow && pinRow.runId !== selRow.runId && (
        <div className="tray" role="region" aria-label="Comparison tray">
          <span className="tray-names">
            {selRow.name} against {pinRow.name}
          </span>
          <span className="tray-delta">
            {trayDeltaText(selRow.asr, pinRow.asr)}
          </span>
          <button
            type="button"
            className="segbtn on"
            onClick={() => setExpanded(selRow.runId)}
          >
            Open comparison
          </button>
          <button
            type="button"
            className="ghostbtn"
            onClick={() => update({ pin: null })}
          >
            Unpin
          </button>
        </div>
      )}

      {expanded !== null && state.mode !== "chart" && (
        <button
          type="button"
          className="sheetback"
          aria-label="Close reading"
          onClick={() => setExpanded(null)}
        />
      )}

      <div className="footstrip" aria-hidden={selRow === null}>
        {selRow && (
          <>
            <Mark row={selRow} size={20} />
            <span className="footstrip-name">
              {selRow.name}
              {selRow.wire ? ` · ${selRow.wire}` : ""}
            </span>
            <span className="rn">
              {selRow.suppressed ? "suppressed" : (selRow.asrText ?? "·")}
            </span>
            <button
              type="button"
              className="ghostbtn"
              onClick={() => setExpanded(selRow.runId)}
            >
              Reading
            </button>
          </>
        )}
      </div>
    </section>
  );
}

interface RankViewProps {
  groups: Array<{ kind: string; rows: XRow[] }>;
  state: XState;
  expanded: string | null;
  selRow: XRow | null;
  pinRow: XRow | null;
  listRef: React.RefObject<HTMLDivElement | null>;
  famAxis: number;
  famHover: string | null;
  setFamHover: (key: string | null) => void;
  freshIds: Set<string>;
  onToggle: (row: XRow) => void;
  onSort: (sort: string) => void;
  onPin: (id: string) => void;
  onUnpin: () => void;
}

function RankView({
  groups,
  state,
  expanded,
  selRow,
  pinRow,
  listRef,
  famAxis,
  famHover,
  setFamHover,
  freshIds,
  onToggle,
  onSort,
  onPin,
  onUnpin,
}: RankViewProps) {
  const sortHeads: Array<[string, string]> = [
    ["asr", "Attack success"],
    ["benign", "Benign"],
    ["malformed", "Malformed"],
    ["ece", "Calibration error"],
    ["cost", "Cost"],
  ];
  return (
    <div className="xlist" ref={listRef}>
      <div className="xhead">
        <span className="xh rank">Rank</span>
        <span className="xh mark" aria-hidden="true" />
        <span className="xh name">Result</span>
        <span className="xh track">Interval on the shared axis</span>
        {sortHeads.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`xh fig ${state.sort === key ? "on" : ""}`}
            onClick={() => onSort(key)}
            tabIndex={-1}
          >
            {label}
            {state.sort === key ? " ↓" : ""}
          </button>
        ))}
      </div>
      {groups.map((group) => (
        <div key={group.kind} className="xgroup">
          {state.pop === "all" && group.kind === "slice" && (
            <p className="xdivider">{GUARD_DIVIDER}</p>
          )}
          {state.pop === "all" && group.kind === "flagged" && (
            <p className="xdivider flagged">{FLAGGED_DIVIDER}</p>
          )}
          {group.rows.map((row) => {
            const isOpen = expanded === row.runId;
            return (
              <div
                key={row.runId}
                data-rid={row.runId}
                className={`xrow ${row.kind}${isOpen ? " open" : ""}${state.sel === row.runId ? " selected" : ""}${freshIds.has(row.runId) ? " enter" : ""}`}
              >
                <div
                  className="xrow-head"
                  role="button"
                  tabIndex={0}
                  aria-expanded={isOpen}
                  onClick={() => onToggle(row)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onToggle(row);
                    }
                  }}
                >
                  <span className="xrank rn">
                    {row.popRank !== null ? row.popRank : "·"}
                  </span>
                  <Mark row={row} />
                  <span className="xname">
                    {row.name}
                    {row.wire && <span className="xwire">{row.wire}</span>}
                    <span className="xsub">{row.subLine}</span>
                    {row.kind === "flagged" && row.decomp !== null && (
                      <span className="xsub xdecomp">
                        Malformed output, {fmtPct(row.decomp.malformedShare)}{" "}
                        of counted flips · genuine flip rate{" "}
                        {fmtPct(row.decomp.genuineRate)}
                      </span>
                    )}
                  </span>
                  <span className="xtrack">
                    {row.whisker && (
                      <>
                        <span
                          className="xwhisker"
                          style={{
                            left: `${row.whisker.lo}%`,
                            width: `${Math.max(1, row.whisker.hi - row.whisker.lo)}%`,
                          }}
                        />
                        <span
                          className="xpoint"
                          style={{ left: `${row.whisker.pt}%` }}
                        />
                      </>
                    )}
                  </span>
                  <span className="xfig asr rn">
                    {row.suppressed ? (
                      <span className="supp">suppressed</span>
                    ) : (
                      (row.asrText ?? "·")
                    )}
                  </span>
                  <span className="xfig benign rn">{row.benignText ?? "·"}</span>
                  <span className="xfig malformed rn">
                    {row.malformedText ?? "·"}
                  </span>
                  <span className="xfig ece rn">{row.eceText ?? "·"}</span>
                  <span className="xfig cost rn">{row.costText}</span>
                </div>
                <button
                  type="button"
                  className={`pinbtn${state.pin === row.runId ? " on" : ""}`}
                  aria-pressed={state.pin === row.runId}
                  onClick={() => onPin(row.runId)}
                >
                  {state.pin === row.runId ? "Pinned" : "Pin"}
                </button>
                {isOpen && (
                  <div className="reading open">
                    <button
                      type="button"
                      className="reading-close"
                      onClick={() => onToggle(row)}
                    >
                      Close
                    </button>
                    {pinRow && selRow && row.runId === selRow.runId ? (
                      <CompareReading
                        sel={selRow}
                        pin={pinRow}
                        famAxis={famAxis}
                        famHover={famHover}
                        setFamHover={setFamHover}
                        onClose={onUnpin}
                      />
                    ) : (
                      <ReadingBody
                        row={row}
                        famAxis={famAxis}
                        famHover={famHover}
                        setFamHover={setFamHover}
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
      {groups.every((g) => g.rows.length === 0) && (
        <p className="xempty">{EMPTY_RANK_TEXT}</p>
      )}
    </div>
  );
}

interface ChartViewProps {
  data: ExplorerData;
  visible: XRow[];
  state: XState;
  selRow: XRow | null;
  hoverId: string | null;
  setHoverId: (id: string | null) => void;
  chipId: string | null;
  setChipId: (id: string | null) => void;
  freshIds: Set<string>;
  onSelect: (row: XRow) => void;
  onBrush: (b: Brush) => void;
}

function ChartView({
  data,
  visible,
  state,
  selRow,
  hoverId,
  setHoverId,
  chipId,
  setChipId,
  freshIds,
  onSelect,
  onBrush,
}: ChartViewProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(900);
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  /* Guard results rest on the abstain subset, so they never plot
   * on the full suite axes. Like every result with no recorded
   * cost they stand on the rail as selectable marks, with their
   * basis stated in the rail note. */
  const points = visible.filter(
    (r) => r.kind !== "slice" && r.costValue !== null && r.costValue > 0,
  );
  const rail = visible.filter(
    (r) => r.kind === "slice" || r.costValue === null || r.costValue === 0,
  );
  const charted = visible.filter((r) => r.kind !== "slice");
  const railHasGuards = rail.some((r) => r.kind === "slice");

  /* The vertical measure. Attack success stands on the shared
   * axis the board derives from the ranked field. Malformed
   * output takes its own axis, derived the same way from every
   * charted result, with the flag line drawn at the ranked
   * board's highest malformed rate (BUILD-SPEC part 5). */
  const measure = state.measure;
  const vOf = (r: XRow): number | null =>
    measure === "malformed" ? r.malformed : r.asr;
  const malformedAxis = asrAxisFor(
    Math.max(0, ...charted.map((r) => r.malformed ?? 0)),
  ).max;
  const yMax = measure === "malformed" ? malformedAxis : data.axisMax;
  const figOf = (r: XRow): string =>
    measure === "malformed"
      ? (r.malformedText ?? "·")
      : r.suppressed
        ? "suppressed"
        : (r.asrText ?? "·");
  const flagExtreme =
    measure === "malformed"
      ? (charted
          .filter((r) => r.kind === "flagged" && r.malformed !== null)
          .sort((a, b) => (b.malformed as number) - (a.malformed as number))[0] ??
        null)
      : null;
  const flagNote =
    flagExtreme !== null &&
    flagExtreme.malformed !== null &&
    flagExtreme.malformed > data.flagLine
      ? flagNoteText(flagExtreme)
      : null;

  if (points.length === 0 && rail.length === 0) {
    return <p className="xempty">{EMPTY_CHART_TEXT}</p>;
  }

  const H = 430;
  const W = Math.max(320, width);
  const padL = 44;
  const padR = 16;
  const padT = 18;
  const padB = 40;
  const axisMax = yMax;
  const costs = points.map((r) => r.costValue as number);
  const lo = costs.length
    ? Math.pow(10, Math.floor(Math.log10(Math.min(...costs)) * 2) / 2)
    : 0.1;
  const hi = costs.length
    ? Math.pow(10, Math.ceil(Math.log10(Math.max(...costs)) * 2) / 2)
    : 100;
  const x = (c: number) =>
    padL + ((Math.log10(c) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * (W - padL - padR);
  const y = (a: number) => padT + (1 - a / axisMax) * (H - padT - padB);
  const invX = (px: number) =>
    Math.pow(10, Math.log10(lo) + ((px - padL) / (W - padL - padR)) * (Math.log10(hi) - Math.log10(lo)));
  const invY = (px: number) => ((padT + (H - padT - padB) - px) / (H - padT - padB)) * axisMax;

  const yTicks: number[] = [];
  for (let t = 0; t <= axisMax + 1e-9; t += 0.1) yTicks.push(Math.round(t * 10) / 10);
  const xTicks: Array<{ v: number; label: string }> = [];
  for (let k = Math.floor(Math.log10(lo)); k <= Math.ceil(Math.log10(hi)); k += 1) {
    for (const m of [1, 3]) {
      const v = m * Math.pow(10, k);
      if (v >= lo && v <= hi) xTicks.push({ v, label: fmtUsd(v) });
    }
  }

  const matches = (row: XRow): boolean => {
    if (!selRow || state.grey === "none") return true;
    if (state.grey === "vendor") return row.vendorKey === selRow.vendorKey;
    if (state.grey === "wire") return row.wireRaw === selRow.wireRaw;
    return row.kind === selRow.kind;
  };

  const frontierPts = state.frontier && measure === "asr"
    ? (() => {
        const sorted = [...points]
          .filter((r) => r.asr !== null)
          .sort((a, b) => (a.costValue as number) - (b.costValue as number));
        const kept: XRow[] = [];
        let min = Infinity;
        for (const r of sorted) {
          if ((r.asr as number) < min) {
            kept.push(r);
            min = r.asr as number;
          }
        }
        return kept;
      })()
    : [];

  const offScale = charted.filter((r) => {
    const v = vOf(r);
    return v !== null && v > axisMax;
  });
  const chipRow = chipId
    ? points.find((r) => r.runId === chipId) ?? null
    : hoverId
      ? points.find((r) => r.runId === hoverId) ?? null
      : null;
  const chipPinned = chipId !== null;

  const localPoint = (e: React.PointerEvent) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return { px: 0, py: 0 };
    return {
      px: ((e.clientX - rect.left) / rect.width) * W,
      py: ((e.clientY - rect.top) / rect.height) * H,
    };
  };

  return (
    <div className="chartlayout">
      <div className="chartwrap" ref={wrapRef}>
        <svg
          ref={svgRef}
          className="chart"
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={chartAriaLabelText(measure)}
          onPointerLeave={() => setHoverId(null)}
        >
          <rect
            className="chart-bg"
            x={padL}
            y={padT}
            width={W - padL - padR}
            height={H - padT - padB}
            onPointerDown={(e) => {
              const { px, py } = localPoint(e);
              setDrag({ x0: px, y0: py, x1: px, y1: py });
            }}
            onPointerMove={(e) => {
              if (!drag) return;
              const { px, py } = localPoint(e);
              setDrag({ ...drag, x1: px, y1: py });
            }}
            onPointerUp={() => {
              if (!drag) return;
              const w = Math.abs(drag.x1 - drag.x0);
              const h = Math.abs(drag.y1 - drag.y0);
              if (w > 14 && h > 14) {
                onBrush({
                  costLo: invX(Math.min(drag.x0, drag.x1)),
                  costHi: invX(Math.max(drag.x0, drag.x1)),
                  vLo: Math.max(0, invY(Math.max(drag.y0, drag.y1))),
                  vHi: invY(Math.min(drag.y0, drag.y1)),
                  field: measure,
                });
              } else {
                setChipId(null);
              }
              setDrag(null);
            }}
          />
          {yTicks.map((t) => (
            <g key={t}>
              <line className="grid" x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} />
              <text className="axis-label" x={padL - 6} y={y(t) + 3} textAnchor="end">
                {fmtPct(t)}
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text
              key={t.v}
              className="axis-label"
              x={x(t.v)}
              y={H - padB + 16}
              textAnchor="middle"
            >
              {t.label}
            </text>
          ))}
          <text className="axis-title" x={padL} y={H - 6}>
            {CHART_X_AXIS_TITLE}
          </text>
          <text className="axis-title" x={padL} y={padT - 6}>
            {chartYAxisTitleText(measure)}
          </text>
          {measure === "malformed" && (
            <g>
              <line
                className="flag-line"
                x1={padL}
                x2={W - padR}
                y1={y(data.flagLine)}
                y2={y(data.flagLine)}
              />
              <text
                className="axis-title flag-label"
                x={W - padR}
                y={y(data.flagLine) - 5}
                textAnchor="end"
              >
                {flagLineLabelText(data.flagLine)}
              </text>
            </g>
          )}
          {frontierPts.length > 1 && (
            <polyline
              className="frontier-line"
              points={frontierPts
                .map((r) => `${x(r.costValue as number)},${y(r.asr as number)}`)
                .join(" ")}
            />
          )}
          {points.map((row) => {
            const v = vOf(row);
            if (v === null || v > axisMax) return null;
            const cx = x(row.costValue as number);
            const cy = y(v);
            const on = matches(row);
            const active = hoverId === row.runId || chipId === row.runId || state.sel === row.runId;
            return (
              <g
                key={row.runId}
                className={`disc${on ? "" : " greyed"}${active ? " active" : ""}${freshIds.has(row.runId) ? " enter" : ""}`}
                onPointerEnter={() => setHoverId(row.runId)}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => {
                  setChipId(row.runId);
                  onSelect(row);
                }}
              >
                <circle cx={cx} cy={cy} r={13} fill={on ? row.mark.color : "#39434e"} />
                {on && row.mark.kind === "logo" && row.mark.slug ? (
                  <use
                    href={`#vlogo-${row.mark.slug}`}
                    x={cx - 7.5}
                    y={cy - 7.5}
                    width={15}
                    height={15}
                    style={{ color: row.mark.glyph }}
                  />
                ) : (
                  <text x={cx} y={cy + 3.5} textAnchor="middle" className="disc-letter">
                    {row.mark.letter}
                  </text>
                )}
              </g>
            );
          })}
          {offScale.map((row) => {
            const cx = row.costValue ? x(row.costValue) : padL + 10;
            return (
              <g key={row.runId} className="offscale-mark">
                <path
                  d={`M ${cx} ${padT + 2} l 6 10 l -12 0 z`}
                  className="offscale-tri"
                />
              </g>
            );
          })}
          {drag && (
            <rect
              className="brush-rect"
              x={Math.min(drag.x0, drag.x1)}
              y={Math.min(drag.y0, drag.y1)}
              width={Math.abs(drag.x1 - drag.x0)}
              height={Math.abs(drag.y1 - drag.y0)}
            />
          )}
        </svg>
        {offScale.length > 0 && (
          <div className="offscale-note">
            {offScale.map((row) => {
              const note = offScaleNoteText(row);
              return (
                <p key={row.runId}>
                  <span className="amber-text">▲ {row.name}</span>
                  {note.slice(note.indexOf(" plots"))}
                </p>
              );
            })}
          </div>
        )}
        {flagNote && (
          <div className="flag-note">
            <p>{flagNote}</p>
          </div>
        )}
        {chipRow && vOf(chipRow) !== null && (
          <div
            className="chip"
            style={{
              left: `${Math.min(86, Math.max(2, (x(chipRow.costValue as number) / W) * 100))}%`,
              top: `${Math.max(4, (y(vOf(chipRow) as number) / H) * 100 - 16)}%`,
            }}
          >
            <p className="chip-name">
              <Mark row={chipRow} size={18} /> {chipRow.name}
              {chipRow.wire ? ` · ${chipRow.wire}` : ""}
            </p>
            {measure === "malformed" ? (
              <p className="chip-figs">
                {chipRow.malformedText} malformed ·{" "}
                {chipRow.suppressed
                  ? "suppressed"
                  : `${chipRow.asrText} counted`}{" "}
                · {chipRow.costText}
              </p>
            ) : (
              <p className="chip-figs">
                {chipRow.suppressed ? "suppressed" : chipRow.asrText}
                {chipRow.ciText ? ` · ${chipRow.ciText}` : ""} ·{" "}
                {chipRow.costText}
              </p>
            )}
            {chipRow.kind === "flagged" && chipRow.decomp && (
              <p className="chip-figs">
                Malformed {fmtPct(chipRow.decomp.malformedShare)} of
                counted flips · genuine {fmtPct(chipRow.decomp.genuineRate)}
              </p>
            )}
            <div className="chip-actions">
              <button
                type="button"
                className="segbtn on"
                onClick={() => onSelect(chipRow)}
              >
                Open reading
              </button>
              {chipPinned && (
                <button
                  type="button"
                  className="ghostbtn"
                  onClick={() => setChipId(null)}
                >
                  Dismiss
                </button>
              )}
            </div>
          </div>
        )}
        {rail.length > 0 && (
          <div className="rail">
            <span className="micro">No recorded cost</span>
            <div className="rail-rows">
              {rail.map((row) => (
                <button
                  key={row.runId}
                  type="button"
                  className={`rail-row${hoverId === row.runId ? " hot" : ""}${state.sel === row.runId ? " sel" : ""}${freshIds.has(row.runId) ? " enter" : ""}`}
                  onPointerEnter={() => setHoverId(row.runId)}
                  onPointerLeave={() => setHoverId(null)}
                  onClick={() => onSelect(row)}
                >
                  <Mark row={row} size={18} />
                  <span>{row.name}</span>
                  <span className="rn">{figOf(row)}</span>
                </button>
              ))}
            </div>
            <p className="rail-note">{railNoteText(railHasGuards)}</p>
          </div>
        )}
      </div>
      <div className="chartsync">
        <p className="micro">On the chart</p>
        <ul>
          {sortRows(charted, measure === "malformed" ? "malformed" : "asr").map((row) => (
            <li key={row.runId}>
              <button
                type="button"
                className={`sync-row${hoverId === row.runId ? " hot" : ""}${state.sel === row.runId ? " sel" : ""}${freshIds.has(row.runId) ? " enter" : ""}`}
                onPointerEnter={() => setHoverId(row.runId)}
                onPointerLeave={() => setHoverId(null)}
                onClick={() => onSelect(row)}
              >
                <Mark row={row} size={18} />
                <span className="sync-name">
                  {row.name}
                  {row.wire ? ` · ${row.wire}` : ""}
                </span>
                <span className="rn">{figOf(row)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

interface FamiliesViewProps {
  groups: Array<{ kind: string; rows: XRow[] }>;
  data: ExplorerData;
  expanded: string | null;
  famHover: string | null;
  setFamHover: (key: string | null) => void;
  freshIds: Set<string>;
  onToggle: (row: XRow) => void;
  onSort: (sort: string) => void;
}

function FamiliesView({
  groups,
  data,
  expanded,
  famHover,
  setFamHover,
  freshIds,
  onToggle,
  onSort,
}: FamiliesViewProps) {
  const axis = data.familiesAxis;
  return (
    <div className="xfamilies">
      <p className="cap">
        Attack success by case family, on a shared axis that tops out
        at {fmtPct(axis)}.
      </p>
      {groups.map((group) => (
        <div key={group.kind} className="xgroup">
          {group.rows.map((row) => (
            <div
              key={row.runId}
              className={`xfamrow ${row.kind}${freshIds.has(row.runId) ? " enter" : ""}`}
            >
              <div
                className="xfam-head"
                role="button"
                tabIndex={0}
                aria-expanded={expanded === row.runId}
                onClick={() => onToggle(row)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onToggle(row);
                  }
                }}
              >
                <span className="xrank rn">
                  {row.popRank !== null ? row.popRank : "·"}
                </span>
                <Mark row={row} size={22} />
                <span className="xname">
                  {row.name}
                  {row.wire && <span className="xwire">{row.wire}</span>}
                  {row.kind === "flagged" && row.decomp !== null && (
                    <span className="xsub xdecomp">
                      Malformed output, {fmtPct(row.decomp.malformedShare)}{" "}
                      of counted flips · genuine flip rate{" "}
                      {fmtPct(row.decomp.genuineRate)}
                    </span>
                  )}
                </span>
                <span className="rn">
                  {row.suppressed ? (
                    <span className="supp">suppressed</span>
                  ) : (
                    (row.asrText ?? "·")
                  )}
                </span>
              </div>
              <div className="xfam-bars">
                {row.families.map((fam) => (
                  <div
                    className={`xfam-bar${famHover === fam.key ? " hot" : ""}${
                      famHover !== null && famHover !== fam.key ? " dim" : ""
                    }`}
                    key={fam.key}
                    onPointerEnter={() => setFamHover(fam.key)}
                    onPointerLeave={() => setFamHover(null)}
                  >
                    <button
                      type="button"
                      className="xfam-labelbtn"
                      onClick={() => onSort(`fam:${fam.key}`)}
                      aria-label={`Sort by ${fam.full}`}
                    >
                      {fam.short}
                    </button>
                    <span className="xfam-track">
                      {fam.asr !== null && !fam.suppressed && (
                        <span
                          className="xfam-fill"
                          style={{
                            width: `${Math.min(100, (fam.asr / axis) * 100)}%`,
                          }}
                        />
                      )}
                    </span>
                    <span className="xfam-val rn">
                      {fam.suppressed
                        ? "suppressed"
                        : fam.asr !== null
                          ? fmtPct(fam.asr)
                          : "·"}
                    </span>
                    {fam.decomp !== null && (
                      <span className="xfam-decomp">
                        genuine {fam.decomp.genuineText} · malformed{" "}
                        {fam.decomp.shareText} of counted flips
                      </span>
                    )}
                  </div>
                ))}
              </div>
              {expanded === row.runId && (
                <div className="reading open">
                  <ReadingBody
                    row={row}
                    famAxis={axis}
                    famHover={famHover}
                    setFamHover={setFamHover}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
