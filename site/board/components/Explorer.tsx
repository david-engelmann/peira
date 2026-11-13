"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ExplorerData, XRow } from "@/lib/explorerData";
import Mark from "@/components/Mark";
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
}

interface Brush {
  costLo: number;
  costHi: number;
  asrLo: number;
  asrHi: number;
}

const DEFAULTS: XState = {
  pop: "all",
  /* The chart is the default mode so the plot's subject
   * composition, the selected result as the one white disc in
   * a dimmed field, stands on first view rather than behind a
   * mode switch. The ladder stands one switch away in Rank
   * mode, and its full names ride the chart's sync list. */
  mode: "chart",
  sort: "asr",
  vendor: "all",
  cost: "all",
  q: "",
  sel: null,
  pin: null,
  frontier: false,
  grey: "vendor",
};

/* A display name breaks at its slash, never mid-token, so a
 * long organisation and model pair wraps as two words rather
 * than tearing one. The break opportunity rides after the
 * slash, and the hyphen breaks inside a token stay available
 * to the line breaker as they are. */
function BreakName({ name }: { name: string }) {
  const parts = name.split("/");
  return (
    <>
      {parts.map((part, i) => (
        <span key={i}>
          {i > 0 && "/"}
          {part}
          {i < parts.length - 1 && <wbr />}
        </span>
      ))}
    </>
  );
}

function decompLine(row: XRow): string | null {
  if (row.decomp === null) return null;
  const d = row.decomp;
  return `${fmtInt(d.flips)} counted flips · ${fmtInt(d.malformedFlips)} to malformed output · genuine flips ${fmtPct(d.genuineRate)} of ${fmtInt(row.nEligible)} eligible cases`;
}

function ReadingBody({ row }: { row: XRow }) {
  const d = decompLine(row);
  return (
    <div className="reading-body">
      <div className="reading-figs">
        <div>
          <span className="micro">{row.asrLabel}</span>
          <strong>{row.asrText ?? "·"}</strong>
          {row.ciText && <span className="rsub">{row.ciText}</span>}
        </div>
        <div>
          <span className="micro">Benign accuracy</span>
          <strong>{row.benignText ?? "·"}</strong>
        </div>
        <div>
          <span className="micro">Malformed output</span>
          <strong>{row.malformedText ?? "·"}</strong>
        </div>
        <div>
          <span className="micro">Calibration error</span>
          <strong>{row.eceText ?? "·"}</strong>
          {row.ece !== null && (
            <span className="rsub">On a 0 to 1 scale</span>
          )}
        </div>
        <div>
          <span className="micro">Cost of one run</span>
          <strong>{row.costText}</strong>
          {row.costSub && <span className="rsub">{row.costSub}</span>}
        </div>
        <div>
          <span className="micro">Median latency</span>
          <strong>{row.latencyText ?? "·"}</strong>
          {row.latencyText !== null && (
            <span className="rsub">Per attacked call</span>
          )}
        </div>
      </div>
      {d && <p className="reading-line">{d}</p>}
      {row.weakestFamily && (
        <p className="reading-line">
          Weakest family {row.weakestFamily.name} at{" "}
          {row.weakestFamily.text}
          {row.weakestFamily.baseText
            ? ` over ${row.weakestFamily.baseText}`
            : ""}
          .
        </p>
      )}
      {row.severities.length > 0 && (
        <p className="reading-line">
          {row.severities.map((s, i) => (
            <span key={s.label}>
              {i > 0 && " · "}
              <span className="sevseg">
                {`${s.label} ${s.flipText ?? "no rate"}${s.baseText ? ` over ${s.baseText}` : ""}`}
              </span>
            </span>
          ))}
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
  return fmt(b - a);
}

function CompareReading({
  sel,
  pin,
  onClose,
}: {
  sel: XRow;
  pin: XRow;
  onClose: () => void;
}) {
  const rows: Array<[string, string, string, string]> = [
    [
      sel.asrLabel,
      sel.asrText ?? "·",
      pin.asrText ?? "·",
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
      "Calibration error",
      sel.eceText ?? "·",
      pin.eceText ?? "·",
      deltaText(sel.ece, pin.ece, (v) => fmtDeltaPct(v)),
    ],
    [
      "Cost of one run",
      sel.costText,
      pin.costText,
      /* A dollar difference exists only between two prices. A
       * run billed through a plan and a run with no recorded
       * cost are not zero priced, so neither side may enter a
       * subtraction that would print one. */
      sel.costValue !== null &&
        pin.costValue !== null &&
        sel.costValue > 0 &&
        pin.costValue > 0
        ? fmtDeltaUsd(pin.costValue - sel.costValue)
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
            <Mark mark={sel.mark} size={20} /> {sel.name}
            {sel.wire ? ` · ${sel.wire}` : ""}
          </p>
          <ReadingBody row={sel} />
        </div>
        <div className="compare-deltas" aria-label="Differences">
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
            <Mark mark={pin.mark} size={20} /> {pin.name}
            {pin.wire ? ` · ${pin.wire}` : ""}
          </p>
          <ReadingBody row={pin} />
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
  { key: "nocharge", label: "No recorded price", test: (c) => c === 0 },
  { key: "nocost", label: "No cost recorded", test: (c) => c === null },
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
  /* The opening selection is the chart's subject, the best
   * ranked result the plot can seat. The plot seats its
   * subject on the cost axis, so the predicate asks for the
   * first full result carrying a metered cost, and a result
   * with no metered cost stands in the chart's rail rather
   * than on the plot. On the current payload the first
   * priced full result is the board leader itself, the
   * rank 1 Gemini run, so the leader takes the white disc
   * until the reader selects another. */
  const opener = useMemo(
    () =>
      data.rows.find(
        (r) => r.kind === "full" && r.costValue !== null && r.costValue > 0,
      ) ?? data.rows.find((r) => r.kind === "full"),
    [data],
  );
  const [state, setState] = useState<XState>({
    ...DEFAULTS,
    sel: opener?.runId ?? null,
  });
  const [expanded, setExpanded] = useState<string | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [chipId, setChipId] = useState<string | null>(null);
  const [brush, setBrush] = useState<Brush | null>(null);
  const touched = useRef(false);
  const listRef = useRef<HTMLDivElement>(null);
  const flipSnapshot = useRef<Map<string, number> | null>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const [explorerLive, setExplorerLive] = useState(false);

  /* The phone footstrip and the comparison tray seat
   * against the explorer only while its scene stands on
   * screen. An IntersectionObserver on the section carries
   * that state, and where the observer is absent the strip
   * keeps its standing behaviour. */
  useEffect(() => {
    const el = sectionRef.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setExplorerLive(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => setExplorerLive(entries[0]?.isIntersecting ?? false),
      { threshold: 0 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

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
    const grey = params.get("grey");
    if (grey === "vendor" || grey === "wire" || grey === "band" || grey === "none") {
      patch.grey = grey;
    }
    open = params.get("open") === "1";
    return { patch, open };
  }, [bySlug]);

  useEffect(() => {
    const apply = (scroll: boolean) => {
      const { patch, open } = parseHash();
      if (Object.keys(patch).length === 0) return;
      setState((s) => ({ ...s, ...patch }));
      if (open && patch.sel) setExpanded(patch.sel);
      if (scroll) {
        sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    };
    apply(false);
    const onHash = () => apply(true);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [parseHash]);

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
    const qs = params.toString();
    const target = qs ? `#explorer?${qs}` : "#explorer";
    if (window.location.hash !== target) {
      window.history.replaceState(null, "", target);
    }
  }, [state, byId]);

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
          el.style.transition =
            "transform 200ms cubic-bezier(0.23, 1, 0.32, 1)";
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
        !`${row.name} ${row.fullName} ${row.wire ?? ""} ${row.vendorLabel}`
          .toLowerCase()
          .includes(query)
      ) {
        return false;
      }
      if (brush) {
        if (row.asr === null || row.costValue === null) return false;
        if (row.costValue < brush.costLo || row.costValue > brush.costHi) return false;
        if (row.asr < brush.asrLo || row.asr > brush.asrHi) return false;
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

  const toggleExpand = (row: XRow) => {
    update({ sel: row.runId });
    setExpanded((e) => (e === row.runId ? null : row.runId));
  };

  return (
    <section className="explorer scene" id="explorer" ref={sectionRef} aria-label="Explorer">
      <div className="sechead">
        <div className="micro eyebrow">
          <span className="eno">02</span> Explorer
        </div>
        <h2>Every result in full</h2>
        <p className="cap">
          Ranking, readings, and comparison live here. Select a row to
          open its reading in place.
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
            value={state.sort.startsWith("fam:") ? state.sort : state.sort}
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
            <label className="xcheck">
              <input
                type="checkbox"
                checked={state.frontier}
                onChange={(e) => update({ frontier: e.target.checked })}
              />
              <span>Frontier</span>
            </label>
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
        <p className="basisline">
          Guard results ran the {fmtInt(data.guardCases)} case abstain
          subset of the suite. They are ranked among themselves on that
          basis, and their rates do not compare with full suite rates.
        </p>
      )}
      <p className="xcount">
        Showing {fmtInt(visible.length)} of {fmtInt(data.rows.length)}{" "}
        results
        {hiddenCount > 0 ? ` · ${fmtInt(hiddenCount)} hidden by filters` : ""}
        {brush ? " · brush filter on" : ""}
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

      {state.mode === "rank" && (
        <RankView
          groups={groups}
          state={state}
          expanded={expanded}
          selRow={selRow}
          pinRow={pinRow}
          listRef={listRef}
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
          onToggle={toggleExpand}
        />
      )}
      {state.mode !== "rank" && expanded && byId.get(expanded) && (
        <div className="belowreading">
          {pinRow && selRow && expanded === selRow.runId ? (
            <CompareReading
              sel={selRow}
              pin={pinRow}
              onClose={() => update({ pin: null })}
            />
          ) : (
            <div className="reading open">
              <ReadingBody row={byId.get(expanded) as XRow} />
            </div>
          )}
        </div>
      )}

      {pinRow && selRow && pinRow.runId !== selRow.runId && (
        <div
          className={`tray${explorerLive ? " over-strip" : ""}`}
          role="region"
          aria-label="Comparison tray"
        >
          <span className="tray-names">
            {selRow.name} against {pinRow.name}
          </span>
          <span className="tray-delta">
            {selRow.asr !== null && pinRow.asr !== null
              ? `${fmtDeltaPct(pinRow.asr - selRow.asr)} attack success`
              : "Rates not comparable"}
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

      <div className="footstrip" aria-hidden={selRow === null || !explorerLive}>
        {selRow && explorerLive && (
          <>
            <Mark mark={selRow.mark} size={20} />
            <span className="footstrip-name">
              {selRow.name}
              {selRow.wire ? ` · ${selRow.wire}` : ""}
            </span>
            <span className="rn">{selRow.asrText ?? "·"}</span>
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
  onToggle,
  onSort,
  onPin,
  onUnpin,
}: RankViewProps) {
  const sortHeads: Array<[string, string]> = [
    ["asr", "Attack success"],
    ["benign", "Benign"],
    ["malformed", "Malformed"],
    ["ece", "Calib. error"],
    ["cost", "Cost"],
  ];
  return (
    <div className="xlist" ref={listRef}>
      <div className="xhead">
        <span className="xh rank">Rank</span>
        <span className="xh mark" aria-hidden="true" />
        <span className="xh name">Result</span>
        <span className="xh track">Interval on the ranked axis</span>
        {sortHeads.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`xh fig ${state.sort === key ? "on" : ""}`}
            onClick={() => onSort(key)}
          >
            {label}
            {state.sort === key ? " ↓" : ""}
          </button>
        ))}
        <span className="xh pin" />
      </div>
      {groups.map((group) => (
        <div key={group.kind} className="xgroup">
          {state.pop === "all" && group.kind === "slice" && (
            <p className="xdivider">
              Guard results · ranked among themselves on the abstain
              subset basis
            </p>
          )}
          {group.kind === "flagged" && (
            <p className="xdivider flagged">
              Flagged results · held off the ranking · their
              intervals stand on the shared axis
            </p>
          )}
          {group.rows.map((row, i) => {
            const isOpen = expanded === row.runId;
            return (
              <div
                key={row.runId}
                data-rid={row.runId}
                className={`xrow ${row.kind}${isOpen ? " open" : ""}${state.sel === row.runId ? " selected" : ""}`}
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
                  <span
                    className="xrank rn"
                    aria-label={row.kind === "flagged" ? "Not ranked" : undefined}
                  >
                    {row.kind === "flagged" ? "" : i + 1}
                  </span>
                  <Mark mark={row.mark} />
                  <span className="xname">
                    <BreakName name={row.fullName} />
                    {row.wire && <span className="xwire">{row.wire}</span>}
                    <span className="xsub">{row.subLine}</span>
                    {row.kind === "flagged" && (
                      <span className="xstate">Flagged · not ranked</span>
                    )}
                  </span>
                  <span className="xtrack">
                    <span className="xtrackline">
                      {row.whisker && (
                        <>
                          <span
                            className={`xwhisker${row.kind === "flagged" ? "" : " fitted"}`}
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
                    {row.kind !== "flagged" && row.ciText && (
                      <span className="xci">{row.ciText}</span>
                    )}
                  </span>
                  <span className="xfig asr rn">{row.asrText ?? "·"}</span>
                  <span className="xfig benign rn">{row.benignText ?? "·"}</span>
                  <span className="xfig malformed rn">
                    {row.malformedText ?? "·"}
                  </span>
                  <span className="xfig ece rn">{row.eceText ?? "·"}</span>
                  <span className="xfig cost rn">{row.costText}</span>
                  <button
                    type="button"
                    className={`pinbtn${state.pin === row.runId ? " on" : ""}`}
                    aria-pressed={state.pin === row.runId}
                    onClick={(e) => {
                      e.stopPropagation();
                      onPin(row.runId);
                    }}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    {state.pin === row.runId ? "Pinned" : "Pin"}
                  </button>
                </div>
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
                        onClose={onUnpin}
                      />
                    ) : (
                      <ReadingBody row={row} />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
      {groups.every((g) => g.rows.length === 0) && (
        <p className="xempty">
          No result matches these filters. Loosen one and the board
          comes back.
        </p>
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
  onSelect,
  onBrush,
}: ChartViewProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(900);
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  /* Set when a dismissal hands focus back to a disc, so the
   * focus that lands there is not read as a new raising of
   * the card. The disc's focus handler consumes the flag on
   * the first focus it explains. The flag is armed only for
   * the return that will actually move focus; see the
   * arming guard in dismissChip. */
  const focusReturnRef = useRef<string | null>(null);
  const nameRef = useRef<SVGTextElement>(null);
  const subRef = useRef<SVGTextElement>(null);
  const [plate, setPlate] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  const [fontsReady, setFontsReady] = useState(false);
  const [chipSeat, setChipSeat] = useState<{
    id: string;
    plateKey: string;
    seat: "above" | "below" | "left" | "right";
    top: number;
    left: number | null;
  } | null>(null);

  /* The label plate is measured once the board's faces
   * have loaded, so its box covers the rendered texts and
   * not a fallback face's narrower measure. */
  useEffect(() => {
    let alive = true;
    document.fonts?.ready.then(() => {
      if (alive) setFontsReady(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  /* The detail card's dismissal, one path for every route
   * its contract names. The close control and Escape both
   * land here. A keyboard dismissal hands focus back to the
   * disc that raised the card, the element that stands for
   * the point once the card is gone. A pointer dismissal
   * leaves focus where it is. */
  const dismissChip = useCallback(
    (returnFocus: boolean) => {
      const id = chipId ?? hoverId;
      setChipId(null);
      setHoverId(null);
      if (returnFocus && id) {
        const disc = wrapRef.current?.querySelector<HTMLElement>(
          `[data-disc="${id}"]`,
        );
        /* The suppression is armed only when the return will
         * move focus, which is the one focus event it exists
         * to explain. When the disc already holds focus (the
         * reader pressed Escape from the disc itself) no
         * focus event follows, so nothing is armed and a
         * later deliberate refocus of the disc raises the
         * card again. */
        if (disc && document.activeElement !== disc) {
          focusReturnRef.current = id;
          disc.focus();
        }
      }
    },
    [chipId, hoverId, setChipId, setHoverId],
  );

  /* Escape dismisses the card while it stands, from
   * wherever focus sits. Focus returns to the raising disc
   * only when the key was pressed from the card itself or
   * from a disc, so a reader working the filter controls is
   * never carried across the page for dismissing a card
   * they were not inside. */
  const cardUp = chipId !== null || hoverId !== null;
  useEffect(() => {
    if (!cardUp) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const active = document.activeElement;
      const chipEl = wrapRef.current?.querySelector(".chip");
      const fromCard = chipEl?.contains(active) ?? false;
      const fromDisc = active?.hasAttribute("data-disc") ?? false;
      dismissChip(fromCard || fromDisc);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cardUp, dismissChip]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const plotted = visible.filter((r) => r.kind !== "slice");
  const points = plotted.filter((r) => r.costValue !== null && r.costValue > 0);
  const rail = plotted.filter((r) => r.costValue === null || r.costValue === 0);
  /* The plot's own ceiling, derived from the results that
   * seat on it: the highest rate among the ranked results
   * that stand as points, a recorded cost above zero,
   * rounded up to the next five percent step. A ranked
   * result with no recorded price stands in the rail and
   * does not stretch a frame it never enters. Flagged
   * results never stretch the frame either, though their
   * seated points still draw inside it, and a point past
   * the frame is carried by the off-scale note, mercury's
   * standing case. */
  const plottedCeiling = Math.max(
    0,
    ...data.rows
      .filter(
        (r) =>
          r.kind === "full" && r.costValue !== null && r.costValue > 0,
      )
      .map((r) => r.asr ?? 0),
  );
  const axisMax = Math.max(
    0.1,
    Math.round(Math.ceil((plottedCeiling - 1e-9) / 0.05) * 5) / 100,
  );
  /* The plot's subject. The selected result takes the white
   * disc when it stands on the plot; a selection in the
   * no-cost rail or off the axis leaves the disc to the best
   * plotted result, so the composition never sits empty. */
  const subjectId = (() => {
    const renderable = points.filter(
      (r) => r.asr !== null && r.asr <= axisMax,
    );
    if (selRow && renderable.some((r) => r.runId === selRow.runId)) {
      return selRow.runId;
    }
    return sortRows(renderable, "asr")[0]?.runId ?? null;
  })();

  /* The subject label plate, measured at render time. The
   * plate is the union of the two label texts' rendered
   * boxes, widened by 8px at each side and 6px above and
   * below, so no field disc can cross a label glyph. It is
   * remeasured whenever the subject, the plot width, the
   * drag state, or the font load changes. */
  useLayoutEffect(() => {
    const nameEl = nameRef.current;
    const subEl = subRef.current;
    if (!nameEl || !subEl) {
      setPlate(null);
      return;
    }
    const a = nameEl.getBBox();
    const b = subEl.getBBox();
    const x = Math.min(a.x, b.x) - 8;
    const right = Math.max(a.x + a.width, b.x + b.width) + 8;
    const y = Math.min(a.y, b.y) - 6;
    setPlate({
      x,
      y,
      w: right - x,
      h: Math.max(a.y + a.height, b.y + b.height) + 6 - y,
    });
  }, [subjectId, width, fontsReady, drag]);

  const H = 430;
  const W = Math.max(320, width);
  const padL = 44;
  /* The right pad carries the widest axis label whole. At
   * the old pad the final tick's label centred on the plot
   * edge and lost its last glyph to the panel. */
  const padR = 30;
  const padT = 18;
  const padB = 40;
  const costs = points.map((r) => r.costValue as number);
  const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...costs)) * 2) / 2);
  const hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...costs)) * 2) / 2);
  const x = (c: number) =>
    padL + ((Math.log10(c) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * (W - padL - padR);
  const y = (a: number) => padT + (1 - a / axisMax) * (H - padT - padB);
  const invX = (px: number) =>
    Math.pow(10, Math.log10(lo) + ((px - padL) / (W - padL - padR)) * (Math.log10(hi) - Math.log10(lo)));
  const invY = (px: number) => ((padT + (H - padT - padB) - px) / (H - padT - padB)) * axisMax;

  const yTicks: number[] = [];
  for (let t = 0; t <= axisMax + 1e-9; t += 0.05) yTicks.push(Math.round(t * 100) / 100);
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

  const frontierPts = state.frontier
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

  const offScale = plotted.filter((r) => r.asr !== null && r.asr > axisMax);
  const chipRow = chipId
    ? points.find((r) => r.runId === chipId) ?? null
    : hoverId
      ? points.find((r) => r.runId === hoverId) ?? null
      : null;
  /* When the reader's selection cannot take the white disc,
   * the chart says so in words, naming the selection and
   * where it stands, rather than silently singling out a
   * different result from the one being read. */
  const subjectRow = subjectId
    ? (points.find((r) => r.runId === subjectId) ?? null)
    : null;
  const selStanding = ((): string | null => {
    if (!selRow || !subjectRow || selRow.runId === subjectRow.runId) {
      return null;
    }
    const name = selRow.fullName;
    const subj = subjectRow.fullName;
    if (!visible.some((r) => r.runId === selRow.runId)) {
      return `${name} is hidden by the current filters. The white disc singles out ${subj}, the best result standing on the plot.`;
    }
    if (selRow.kind === "slice") {
      return `${name} is a guard result, and guard results read in the rank and families modes. The white disc singles out ${subj}.`;
    }
    if (selRow.asr !== null && selRow.asr > axisMax) {
      return `${name} plots above the shared axis at ${selRow.asrText} counted, so it carries no disc. The white disc singles out ${subj}.`;
    }
    if (selRow.costKind === "harness") {
      return `${name} was measured through a harness and stands in the rail below. The white disc singles out ${subj}.`;
    }
    if (selRow.costKind === "local") {
      return `${name} was served locally and stands in the rail below. The white disc singles out ${subj}.`;
    }
    if (selRow.costValue === null) {
      return `${name} has no recorded cost and stands in the rail below. The white disc singles out ${subj}.`;
    }
    if (selRow.asr === null) {
      return `${name} carries no attack success rate to plot. The white disc singles out ${subj}.`;
    }
    return null;
  })();

  const localPoint = (e: React.PointerEvent) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return { px: 0, py: 0 };
    return {
      px: ((e.clientX - rect.left) / rect.width) * W,
      py: ((e.clientY - rect.top) / rect.height) * H,
    };
  };

  const subjectCx = subjectRow ? x(subjectRow.costValue as number) : 0;
  const subjectCy = subjectRow ? y(subjectRow.asr as number) : 0;
  const subjectLabelBelow = subjectCy < 72;

  /* The detail card seats by measured clearance on all
   * four sides of its disc. The rendered card, the label
   * plate, every other disc face, and the axis labels are
   * the obstacles. The seat above the disc stands unless
   * another seat, below, right, or left, measures strictly
   * clearer, so a card that already stands clear never
   * moves. The below seat keeps the plate law, pushed past
   * whichever stands lower, the disc's bottom or the
   * plate's bottom. Every candidate is shifted inside the
   * chart wrap before it is scored, and clearance is
   * measured on the rendered boxes, never intended from
   * the disc's coordinates. */
  useLayoutEffect(() => {
    if (!chipRow || chipRow.asr === null) {
      return;
    }
    const wrap = wrapRef.current;
    const chipEl = wrap?.querySelector(".chip");
    const discEl = wrap?.querySelector(
      `[data-disc="${chipRow.runId}"] .disc-face`,
    );
    if (!wrap || !chipEl || !discEl) return;
    const wrapRect = wrap.getBoundingClientRect();
    const chipRect = chipEl.getBoundingClientRect();
    const discRect = discEl.getBoundingClientRect();
    const plateEl = svgRef.current?.querySelector(".label-plate");
    const plateRect = plateEl?.getBoundingClientRect() ?? null;
    /* The seat stands down only while the plate it was
     * measured against stands unchanged. The plate is
     * itself measured in a layout effect and can move to
     * a new subject one commit after the card first
     * stands, so the seat keys on the plate's measured
     * box and is measured again whenever that box moves. */
    const plateKey = plateRect
      ? `${Math.round(plateRect.left)},${Math.round(plateRect.top)},${Math.round(plateRect.width)},${Math.round(plateRect.height)}`
      : "none";
    if (chipSeat?.id === chipRow.runId) {
      if (chipSeat.plateKey === plateKey) return;
      /* The plate moved after this seat was measured, and
       * the standing card no longer shows the default seat
       * the scoring reads. Clear the seat and let the next
       * commit measure the card where it stands by
       * default, against the plate where it stands now. */
      setChipSeat(null);
      return;
    }
    const obstacles: { left: number; top: number; right: number; bottom: number }[] =
      [];
    svgRef.current?.querySelectorAll(".disc-face").forEach((d) => {
      if (d !== discEl) obstacles.push(d.getBoundingClientRect());
    });
    /* The axis texts stand apart from the field discs in
     * the obstacles. A disc the card covers is still
     * printed in the rows below the chart, but an axis
     * label the card covers is the only printing of that
     * scale value on the chart, so the seat score prices
     * the two apart. */
    const axisTexts: {
      rect: { left: number; top: number; right: number; bottom: number };
      label: boolean;
      area: number;
    }[] = [];
    svgRef.current?.querySelectorAll("text").forEach((t) => {
      if (!t.closest("[data-disc]") && !t.closest(".subject-label")) {
        const rect = t.getBoundingClientRect();
        axisTexts.push({
          rect,
          label: (t.getAttribute("class") || "").includes("axis-label"),
          area: rect.width * rect.height,
        });
      }
    });
    const w = chipRect.width;
    const h = chipRect.height;
    const clampIn = (left: number, top: number) => ({
      left: Math.min(Math.max(left, wrapRect.left + 4), wrapRect.right - w - 4),
      top: Math.min(Math.max(top, wrapRect.top + 4), wrapRect.bottom - h - 4),
    });
    const overlapArea = (
      pos: { left: number; top: number },
      o: { left: number; top: number; right: number; bottom: number },
    ) =>
      Math.max(
        0,
        Math.min(pos.left + w, o.right) - Math.max(pos.left, o.left),
      ) *
      Math.max(
        0,
        Math.min(pos.top + h, o.bottom) - Math.max(pos.top, o.top),
      );
    /* The plate is a hard bound, not a trade. A seat that
     * touches the plate loses to every seat that clears
     * it, however much field the clearing seat covers, and
     * only a card with no clearing seat at all takes the
     * seat that touches the plate least. */
    /* The scored plate carries a 2px clearance margin on
     * every side. A seat the scoring clears by a hair can
     * still land across the plate's edge once its stored
     * percentages are laid out again, and the wrap's clamp
     * floor can eat a slide's whole margin, so the hard
     * bound is priced against the plate as it must stand
     * clear of, not the plate as drawn. */
    const plateBound = plateRect
      ? {
          left: plateRect.left - 2,
          top: plateRect.top - 2,
          right: plateRect.right + 2,
          bottom: plateRect.bottom + 2,
        }
      : null;
    const score = (pos: { left: number; top: number }) => {
      const againstPlate = plateBound ? overlapArea(pos, plateBound) : 0;
      let discArea = 0;
      let centres = 0;
      for (const o of obstacles) {
        discArea += overlapArea(pos, o);
        const cx = (o.left + o.right) / 2;
        const cy = (o.top + o.bottom) / 2;
        if (
          cx > pos.left &&
          cx < pos.left + w &&
          cy > pos.top &&
          cy < pos.top + h
        ) {
          centres++;
        }
      }
      let textArea = 0;
      let lostLabels = 0;
      for (const t of axisTexts) {
        const a = overlapArea(pos, t.rect);
        textArea += a;
        if (t.label && a >= t.area / 2) lostLabels++;
      }
      return (
        againstPlate * 10000000 +
        discArea +
        centres * 400 +
        textArea * 2.5 +
        lostLabels * 1500
      );
    };
    const belowTop = Math.max(
      discRect.bottom + 10,
      plateRect ? plateRect.bottom + 8 : Number.NEGATIVE_INFINITY,
    );
    const midY = discRect.top + discRect.height / 2 - h / 2;
    /* A seat beside the disc may stand centred on the
     * disc's height or slid along the disc's side to
     * whichever edge of the plate stands nearer, so a
     * side seat is not lost to the plate's band when a
     * shift of the card's height clears it. */
    const sideTops = plateRect
      ? [midY, plateRect.top - h - 4, plateRect.bottom + 4]
      : [midY];
    /* A seat beside the disc may also slide to the far
     * side of an axis label its centred span would stand
     * across, clearing the label whole instead of covering
     * it. The slide stays near the disc, its centre within
     * half the card's height and the plate's reach of the
     * disc's centre, so the card never wanders from the
     * disc it describes. */
    const discCy = discRect.top + discRect.height / 2;
    for (const t of axisTexts) {
      if (t.rect.bottom < midY - 8 || t.rect.top > midY + h + 8) continue;
      for (const top of [t.rect.top - h - 2, t.rect.bottom + 2]) {
        if (Math.abs(top + h / 2 - discCy) <= h / 2 + 48) {
          sideTops.push(top);
        }
      }
    }
    const sideSeat = (seat: "right" | "left", left: number) => {
      let bestPos = clampIn(left, sideTops[0]);
      let bestScore = score(bestPos);
      for (const top of sideTops.slice(1)) {
        const pos = clampIn(left, top);
        const s2 = score(pos);
        if (s2 < bestScore - 0.5) {
          bestPos = pos;
          bestScore = s2;
        }
      }
      return { seat, ...bestPos };
    };
    const candidates = [
      { seat: "above" as const, ...clampIn(chipRect.left, chipRect.top) },
      { seat: "below" as const, ...clampIn(chipRect.left, belowTop) },
      sideSeat("right", discRect.right + 12),
      sideSeat("left", discRect.left - 12 - w),
    ];
    let best = candidates[0];
    let bestScore = score(best);
    for (const c of candidates.slice(1)) {
      const s2 = score(c);
      if (s2 < bestScore - 0.5) {
        best = c;
        bestScore = s2;
      }
    }
    /* Every seat stores the position the scoring measured,
     * converted back through the seat's own transform, so the
     * above and below cards ride an 8px leftward shift, the
     * above card a full-height upward shift, the side cards
     * a half-height upward shift. Until this pass the above
     * and below seats stored no left at all, so the render
     * fell back to the disc's raw cost percentage and the
     * card stood there instead of at its measured seat,
     * which at phone widths carried it past the chart wrap
     * and off the screen for the field's right half. */
    const leftPct = (px: number) =>
      ((px - wrapRect.left) / wrapRect.width) * 100;
    const topPct = (px: number) =>
      ((px - wrapRect.top) / wrapRect.height) * 100;
    if (best.seat === "above") {
      setChipSeat({
        id: chipRow.runId,
        plateKey,
        seat: "above",
        top: topPct(best.top + h),
        left: leftPct(best.left + 8),
      });
      return;
    }
    const top =
      best.seat === "below"
        ? topPct(best.top)
        : topPct(best.top + h / 2);
    const left =
      best.seat === "below"
        ? leftPct(best.left + 8)
        : leftPct(best.left);
    setChipSeat({ id: chipRow.runId, plateKey, seat: best.seat, top, left });
  });

  return visible.length > 0 && plotted.length === 0 ? (
    <p className="xempty">
      The chart plots full suite and flagged results. Guard results
      read in the rank and families modes, on their own basis.
    </p>
  ) : points.length === 0 && rail.length === 0 ? (
    <p className="xempty">
      No priced result matches these filters, so the chart has
      nothing to plot.
    </p>
  ) : (
    <div className="chartlayout">
      <div className="chartwrap" ref={wrapRef}>
        <svg
          ref={svgRef}
          className="chart"
          viewBox={`0 0 ${W} ${H}`}
          role="group"
          aria-label="Attack success against the cost of one run"
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
                  asrLo: Math.max(0, invY(Math.max(drag.y0, drag.y1))),
                  asrHi: invY(Math.min(drag.y0, drag.y1)),
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
            Cost of one run, log scale
          </text>
          <text className="axis-title" x={padL} y={padT - 6}>
            Attack success, lower is better
          </text>
          {frontierPts.length > 1 && (
            <polyline
              className="frontier-line"
              points={frontierPts
                .map((r) => `${x(r.costValue as number)},${y(r.asr as number)}`)
                .join(" ")}
            />
          )}
          {points.map((row) => {
            if (row.asr === null || row.asr > axisMax) return null;
            const cx = x(row.costValue as number);
            const cy = y(row.asr);
            const on = matches(row);
            const subject = subjectId === row.runId;
            const active = hoverId === row.runId || chipId === row.runId || state.sel === row.runId;
            /* Every disc carries its maker's mark where the
             * vendor table records one, riding the field's
             * dimmed opacity the group already carries. The
             * highlight filter dims a disc outside the group.
             * It no longer strips the disc's mark and leaves a
             * bare circle or a stray letter behind. Families
             * the table records with no usable mark keep
             * their monogram letter, the same identity their
             * rows and cards carry. */
            return (
              <g
                key={row.runId}
                className={`disc${on ? "" : " greyed"}${subject ? " subject" : " field"}${active && !subject ? " active" : ""}`}
                data-disc={row.runId}
                tabIndex={0}
                role="button"
                aria-label={`Details for ${row.fullName}, attack success ${row.asrText ?? "not measured"}, cost ${row.costText}`}
                onPointerEnter={() => setHoverId(row.runId)}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => {
                  setChipId(row.runId);
                  onSelect(row);
                }}
                onFocus={() => {
                  /* Focus raises the identical card the pointer
                   * raises. A focus the dismissal handed back
                   * to this disc is not a new raising, so the
                   * flag is consumed and the card stays down. */
                  if (focusReturnRef.current === row.runId) {
                    focusReturnRef.current = null;
                    return;
                  }
                  setHoverId(row.runId);
                }}
                onBlur={(e) => {
                  /* An unpinned card follows focus the way it
                   * follows the pointer. Leaving the disc for
                   * anywhere but the card itself puts it down.
                   * A pinned card stands until it is dismissed. */
                  if (chipId === row.runId) return;
                  const next = e.relatedTarget as Node | null;
                  const chipEl = wrapRef.current?.querySelector(".chip");
                  if (next && chipEl?.contains(next)) return;
                  if (hoverId === row.runId) setHoverId(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setChipId(row.runId);
                    onSelect(row);
                  }
                }}
              >
                <circle
                  className="disc-face"
                  cx={cx}
                  cy={cy}
                  r={subject ? 17 : 15}
                  fill={subject ? "#ffffff" : "#4a5763"}
                  stroke={
                    row.kind === "flagged"
                      ? "#e8a33d"
                      : subject
                        ? "none"
                        : "#05070a"
                  }
                  strokeWidth={
                    row.kind === "flagged" ? (subject ? 2 : 1.5) : 1.5
                  }
                />
                {row.mark.kind === "logo" && row.mark.slug ? (
                  <use
                    href={`#vlogo-${row.mark.slug}`}
                    x={cx - 9.5}
                    y={cy - 9.5}
                    width={19}
                    height={19}
                    style={{ color: subject ? "var(--glyph-dark)" : "#eef2f6" }}
                  />
                ) : (
                  <text
                    x={cx}
                    y={cy + 3.5}
                    textAnchor="middle"
                    className={`disc-letter${subject ? " subject-letter" : ""}`}
                  >
                    {row.mark.letter}
                  </text>
                )}
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
          {subjectRow && !drag && (
            <g className="subject-label">
              {plate && (
                <rect
                  className="label-plate"
                  x={plate.x}
                  y={plate.y}
                  width={plate.w}
                  height={plate.h}
                  rx={5}
                />
              )}
              <text
                ref={nameRef}
                className="subject-name"
                x={subjectCx}
                y={subjectLabelBelow ? subjectCy + 40 : subjectCy - 38}
                textAnchor="middle"
              >
                {subjectRow.fullName}
              </text>
              <text
                ref={subRef}
                className="subject-sub"
                x={subjectCx}
                y={subjectLabelBelow ? subjectCy + 54 : subjectCy - 25}
                textAnchor="middle"
              >
                {subjectRow.asrText} · {subjectRow.costText}
              </text>
            </g>
          )}
        </svg>
        {selStanding && <p className="chart-selstand">{selStanding}</p>}
        {state.frontier && frontierPts.length > 1 && (
          <p className="chart-legend">
            <span className="legend-swatch" aria-hidden="true" />
            Frontier, the lowest attack success at each cost
          </p>
        )}
        {offScale.length > 0 && (
          <div className="offscale-note">
            {offScale.map((row) => (
              <p key={row.runId}>
                <span className="amber-text">{row.fullName}</span> plots
                above the shared axis at {row.asrText} counted.
                {row.decomp
                  ? ` Malformed output is ${fmtPct(row.decomp.malformedShare)} of its counted flips, and its genuine flips are ${fmtPct(row.decomp.genuineRate)} of its eligible cases.`
                  : ""}
              </p>
            ))}
          </div>
        )}
        {chipRow && chipRow.asr !== null && (
          <div
            className={
              chipSeat?.id === chipRow.runId
                ? chipSeat.seat === "below"
                  ? "chip below"
                  : chipSeat.seat === "left"
                    ? "chip side-left"
                    : chipSeat.seat === "right"
                      ? "chip side-right"
                      : "chip"
                : "chip"
            }
            style={{
              left: `${
                chipSeat?.id === chipRow.runId &&
                chipSeat.left !== null
                  ? chipSeat.left
                  : Math.min(86, Math.max(2, (x(chipRow.costValue as number) / W) * 100))
              }%`,
              top: `${
                chipSeat?.id === chipRow.runId
                  ? chipSeat.top
                  : Math.max(4, (y(chipRow.asr) / H) * 100 - 16)
              }%`,
            }}
          >
            <p className="chip-name">
              <Mark mark={chipRow.mark} size={18} /> {chipRow.name}
              {chipRow.wire ? ` · ${chipRow.wire}` : ""}
            </p>
            <p className="chip-figs">
              {chipRow.asrText}
              {chipRow.ciText ? ` · ${chipRow.ciText}` : ""} ·{" "}
              {chipRow.costText}
            </p>
            {chipRow.kind === "flagged" && chipRow.decomp && (
              <p className="chip-figs">
                Malformed {fmtPct(chipRow.decomp.malformedShare)} of
                counted flips · genuine flips{" "}
                {fmtPct(chipRow.decomp.genuineRate)} of eligible cases
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
              {/* The close control stands in the hover state
               * and the pinned state alike, as the card's
               * contract states. A keyboard activation of it
               * (a click with no pointer detail) returns
               * focus to the raising disc, and a pointer
               * activation leaves focus alone. */}
              <button
                type="button"
                className="ghostbtn"
                onClick={(e) => dismissChip(e.detail === 0)}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}
        {rail.length > 0 && (
          <div className="rail">
            {/* The rail keeps its facts apart. A harness run is
             * billed through its plan, a local run carries no
             * API cost, and a null is a run whose cost went
             * unrecorded. Each stands off the axis under its own
             * heading, and none of them stands at zero. */}
            {[
              {
                key: "harness",
                head: "Measured through a harness",
                note: "This result was measured through the Cursor agent harness on a paid plan. Its cost is not metered per run, so it stands off the axis rather than at zero.",
                rows: rail.filter((r) => r.costKind === "harness"),
              },
              {
                key: "local",
                head: "No API cost",
                note: "These results were served locally and carry no API cost, so they stand off the axis rather than at zero.",
                rows: rail.filter((r) => r.costKind === "local"),
              },
              {
                key: "nocost",
                head: "No recorded cost",
                note: "These results carry no recorded serving cost, so they stand off the axis rather than at zero.",
                rows: rail.filter((r) => r.costValue === null),
              },
            ]
              .filter((g) => g.rows.length > 0)
              .map((g) => (
                <div className="rail-group" key={g.key}>
                  <span className="micro">{g.head}</span>
                  <div className="rail-rows">
                    {g.rows.map((row) => (
                      <button
                        key={row.runId}
                        type="button"
                        className={`rail-row${state.sel === row.runId ? " sel" : ""}`}
                        onPointerEnter={() => setHoverId(row.runId)}
                        onClick={() => onSelect(row)}
                      >
                        <Mark mark={row.mark} size={18} />
                        <span>{row.fullName}</span>
                        <span className="rn">{row.asrText ?? "·"}</span>
                      </button>
                    ))}
                  </div>
                  <p className="rail-note">{g.note}</p>
                </div>
              ))}
          </div>
        )}
      </div>
      <div className="chartsync">
        <p className="micro">On the chart</p>
        <ul>
          {sortRows(plotted, "asr").map((row) => (
            <li key={row.runId}>
              <button
                type="button"
                className={`sync-row${hoverId === row.runId ? " hot" : ""}${state.sel === row.runId ? " sel" : ""}`}
                onPointerEnter={() => setHoverId(row.runId)}
                onPointerLeave={() => setHoverId(null)}
                onClick={() => onSelect(row)}
              >
                <Mark mark={row.mark} size={18} />
                <span className="sync-name">
                  <BreakName name={row.fullName} />
                  {row.wire ? ` · ${row.wire}` : ""}
                </span>
                <span className="rn">{row.asrText ?? "·"}</span>
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
  onToggle: (row: XRow) => void;
}

function FamiliesView({ groups, data, expanded, onToggle }: FamiliesViewProps) {
  const maxFam = Math.max(
    0.05,
    ...data.rows.flatMap((r) =>
      r.families.map((f) => f.asr ?? 0),
    ),
  );
  const axis = Math.ceil(maxFam * 10) / 10;
  return (
    <div className="xfamilies">
      <p className="cap">
        Attack success by case family, on a shared axis that tops out
        at {fmtPct(axis)}.
      </p>
      <div className="xfam-colhead" aria-hidden="true">
        <span className="micro">Result</span>
        <span className="micro">Overall attack success</span>
      </div>
      <div className="xfam-bars axisrow" aria-hidden="true">
        <div className="xfam-bar">
          <span className="xfam-label micro">Axis</span>
          <span className="xfam-track ghost">
            {[0, 0.25, 0.5, 0.75, 1].map((f) => (
              <span
                key={f}
                className={`xfam-tick${f === 0 ? " first" : ""}${f === 1 ? " last" : ""}`}
                style={{ left: `${f * 100}%` }}
              >
                {fmtPct(axis * f)}
              </span>
            ))}
          </span>
          <span className="xfam-val micro">Of axis</span>
        </div>
        <div />
      </div>
      {groups.map((group) => (
        <div key={group.kind} className="xgroup">
          {group.rows.map((row, i) => (
            <div key={row.runId} className={`xfamrow ${row.kind}`}>
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
                <span
                  className="xrank rn"
                  aria-label={row.kind === "flagged" ? "Not ranked" : undefined}
                >
                  {row.kind === "flagged" ? "" : i + 1}
                </span>
                <Mark mark={row.mark} size={22} />
                <span className="xname">
                  <BreakName name={row.fullName} />
                  {row.wire && <span className="xwire">{row.wire}</span>}
                  {row.kind === "flagged" && (
                    <span className="xstate">Flagged · not ranked</span>
                  )}
                </span>
                <span className="rn">{row.asrText ?? "·"}</span>
              </div>
              <div className="xfam-bars">
                {row.families.map((fam) => (
                  <div className="xfam-bar" key={fam.key} title={`${fam.full} ${fam.asr !== null ? fmtPct(fam.asr) : "not measured"}`}>
                    <span className="xfam-label">{fam.full}</span>
                    <span className="xfam-track">
                      {fam.asr !== null && (
                        <span
                          className="xfam-fill"
                          style={{ width: `${Math.min(100, (fam.asr / axis) * 100)}%` }}
                        />
                      )}
                    </span>
                    <span className="xfam-val rn">
                      {fam.asr !== null ? fmtPct(fam.asr) : "Not measured"}
                    </span>
                  </div>
                ))}
              </div>
              {expanded === row.runId && (
                <div className="reading open">
                  <ReadingBody row={row} />
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
