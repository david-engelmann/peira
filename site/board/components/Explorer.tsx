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

function decompLine(row: XRow): string | null {
  if (row.decomp === null) return null;
  const d = row.decomp;
  return `${fmtInt(d.flips)} counted flips · ${fmtInt(d.malformedFlips)} to malformed output · genuine flips ${fmtPct(d.genuineRate)} of eligible cases`;
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
      {row.weakestFamily && (
        <p className="reading-line">
          Weakest family {row.weakestFamily.name} at{" "}
          {row.weakestFamily.text}.
        </p>
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
            <Mark row={sel} size={20} /> {sel.name}
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
            <Mark row={pin} size={20} /> {pin.name}
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
   * ranked result the plot can seat. The board leader ran
   * through the Cursor harness, whose cost is billed through
   * a paid plan and not metered per run, so it stands in the
   * chart's rail rather than on the plot, and the best priced
   * result takes the white disc until the reader selects
   * another. */
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
        <div className="tray" role="region" aria-label="Comparison tray">
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

      <div className="footstrip" aria-hidden={selRow === null}>
        {selRow && (
          <>
            <Mark row={selRow} size={20} />
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
          {state.pop === "all" && group.kind === "flagged" && (
            <p className="xdivider flagged">
              Flagged results · held off the ranking
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
                  <span className="xrank rn">
                    {row.kind === "flagged" ? "—" : i + 1}
                  </span>
                  <Mark row={row} />
                  <span className="xname">
                    {row.fullName}
                    {row.wire && <span className="xwire">{row.wire}</span>}
                    <span className="xsub">{row.subLine}</span>
                    {row.kind === "flagged" && (
                      <span className="xstate">Flagged · not ranked</span>
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
  /* The plot's subject. The selected result takes the white
   * disc when it stands on the plot; a selection in the
   * no-cost rail or off the axis leaves the disc to the best
   * plotted result, so the composition never sits empty. */
  const subjectId = (() => {
    const renderable = points.filter(
      (r) => r.asr !== null && r.asr <= data.axisMax,
    );
    if (selRow && renderable.some((r) => r.runId === selRow.runId)) {
      return selRow.runId;
    }
    return sortRows(renderable, "asr")[0]?.runId ?? null;
  })();

  if (visible.length > 0 && plotted.length === 0) {
    return (
      <p className="xempty">
        The chart plots full suite and flagged results. Guard results
        read in the rank and families modes, on their own basis.
      </p>
    );
  }
  if (points.length === 0 && rail.length === 0) {
    return (
      <p className="xempty">
        No priced result matches these filters, so the chart has
        nothing to plot.
      </p>
    );
  }

  const H = 430;
  const W = Math.max(320, width);
  const padL = 44;
  const padR = 16;
  const padT = 18;
  const padB = 40;
  const axisMax = data.axisMax;
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
            const labelBelow = cy < 72;
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
                onPointerEnter={() => setHoverId(row.runId)}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => {
                  setChipId(row.runId);
                  onSelect(row);
                }}
              >
                <circle
                  cx={cx}
                  cy={cy}
                  r={subject ? 15 : 13}
                  fill={subject ? "#ffffff" : "#39434e"}
                  stroke={row.kind === "flagged" ? "#e8a33d" : "none"}
                  strokeWidth={row.kind === "flagged" ? (subject ? 2 : 1.5) : 0}
                />
                {row.mark.kind === "logo" && row.mark.slug ? (
                  <use
                    href={`#vlogo-${row.mark.slug}`}
                    x={cx - 7.5}
                    y={cy - 7.5}
                    width={15}
                    height={15}
                    style={{ color: subject ? "var(--glyph-dark)" : "#aebcc7" }}
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
                {subject && !drag && (
                  <>
                    <text
                      className="subject-name"
                      x={cx}
                      y={labelBelow ? cy + 32 : cy - 30}
                      textAnchor="middle"
                    >
                      {row.fullName}
                    </text>
                    <text
                      className="subject-sub"
                      x={cx}
                      y={labelBelow ? cy + 46 : cy - 17}
                      textAnchor="middle"
                    >
                      {row.asrText} · {row.costText}
                    </text>
                  </>
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
        </svg>
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
            className="chip"
            style={{
              left: `${Math.min(86, Math.max(2, (x(chipRow.costValue as number) / W) * 100))}%`,
              top: `${Math.max(4, (y(chipRow.asr) / H) * 100 - 16)}%`,
            }}
          >
            <p className="chip-name">
              <Mark row={chipRow} size={18} /> {chipRow.name}
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
                        className="rail-row"
                        onPointerEnter={() => setHoverId(row.runId)}
                        onClick={() => onSelect(row)}
                      >
                        <Mark row={row} size={18} />
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
                <Mark row={row} size={18} />
                <span className="sync-name">
                  {row.fullName}
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
                <span className="xrank rn">
                  {row.kind === "flagged" ? "—" : i + 1}
                </span>
                <Mark row={row} size={22} />
                <span className="xname">
                  {row.fullName}
                  {row.wire && <span className="xwire">{row.wire}</span>}
                  {row.kind === "flagged" && (
                    <span className="xstate">Flagged · not ranked</span>
                  )}
                </span>
                <span className="rn">{row.asrText ?? "·"}</span>
              </div>
              <div className="xfam-bars">
                {row.families.map((fam) => (
                  <div className="xfam-bar" key={fam.key} title={`${fam.full} ${fam.asr !== null ? fmtPct(fam.asr) : "no rate"}`}>
                    <span className="xfam-label">{fam.short}</span>
                    <span className="xfam-track">
                      {fam.asr !== null && (
                        <span
                          className="xfam-fill"
                          style={{ width: `${Math.min(100, (fam.asr / axis) * 100)}%` }}
                        />
                      )}
                    </span>
                    <span className="xfam-val rn">
                      {fam.asr !== null ? fmtPct(fam.asr) : "·"}
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
