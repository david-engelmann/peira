import {
  displayCi,
  flipDecomposition,
  familyFlipDecomposition,
  wireWords,
  type BoardRow,
  type TaxBenchmarks,
} from "@/lib/payload";
import {
  fmtPct,
  fmtCi,
  fmtEce,
  fmtInt,
  fmtMs,
} from "@/lib/format";
import {
  familiesOf,
  fmtCellPct,
  familyFullName,
  calibrationArmsOf,
} from "@/lib/charts";
import {
  provenanceOf,
  severitiesOf,
  runDateWords,
  versionForProvenance,
} from "@/lib/cards";
import type { InspectorDatum } from "@/lib/inspectorData";
import { vendorColorOf } from "@/lib/vendorColors";
import Inspector from "./Inspector";

export type ReadingKind = "full" | "flagged" | "slice";

function NotMeasured() {
  return <span className="not-measured-inline">·</span>;
}

/**
 * A result's own page, re-set as a full-page inspector
 * reading in the instrument grammar: the inspector itself
 * (identity head with the vendor mark, the figure grid,
 * the disclosure blocks verbatim from the payload's note
 * builders), then the readings the panel inspector does
 * not carry, in the same grammar. First the interval in full,
 * the second latency figure, the calibration arms, the
 * family spark list, the severity flips, the tax line
 * naming its benchmarks, and the run's provenance. Every
 * figure and disclosure the detail card carried survives;
 * only the presentation grammar changed.
 */
export default function ModelReading({
  row,
  kind,
  datum,
  axisMax,
  benchmarks,
  familyKeys,
}: {
  row: BoardRow;
  kind: ReadingKind;
  datum: InspectorDatum;
  axisMax: number;
  benchmarks: TaxBenchmarks;
  familyKeys: string[];
}) {
  const ci = displayCi(row);
  const arms = calibrationArmsOf(row);
  const sevs = severitiesOf(row);
  const prov = provenanceOf(row);
  const fams = familiesOf(row);
  /* A flagged reading's per-family figures travel with
   * their own decompositions (C-5), the discipline the
   * heatmap's cell titles keep. A family whose sealed
   * records derive no decomposition prints no figure in
   * the spark list below, and it cannot be the weakest
   * family drawn red, since no bar draws for it. */
  const famDecomp =
    kind === "flagged" ? familyFlipDecomposition(row) : null;
  const familyPrints = (key: string): boolean =>
    famDecomp === null || (famDecomp.get(key) ?? null) !== null;
  const carried = familyKeys
    .map((key) => ({ key, fam: fams.get(key) }))
    .filter((e) => e.fam && e.fam.asr !== null && familyPrints(e.key));
  const worst = carried.length
    ? Math.max(...carried.map((e) => e.fam!.asr as number))
    : null;
  const taxed = row.robustness_tax !== null && row.robustness_tax !== undefined;
  const atkBrier = arms?.attacked.brier ?? null;
  const benEce = arms?.benign.ece ?? null;
  const benBrier = arms?.benign.brier ?? null;
  const coverage = arms?.coverageAttacked ?? null;
  /* A flagged headline figure travels with its flip
   * decomposition (C-5), stated in the inspector's flagged
   * block above. Where the sealed records derive no
   * decomposition, the headline states no figure at all,
   * and the interval figure below follows it, so no
   * surface of this page can print the figure bare. */
  const decomp = kind === "flagged" ? flipDecomposition(row) : null;
  const showFigure =
    row.asr_conditional !== null && (kind !== "flagged" || decomp !== null);

  return (
    <div className="reading-body">
      <Inspector datum={datum} axisMax={axisMax} variant="page" />

      <p className="model-id mono">{row.display_name}</p>
      <p className="wire-line">Wire {wireWords(row.wire)}</p>

      <div className="figs figs-extra">
        {showFigure && ci !== null && (
          <div className="fig">
            <span className="fl">95 percent interval</span>
            <span className="v">{fmtCi(ci)}</span>
          </div>
        )}
        <div className="fig">
          <span className="fl">Latency p95, attacked</span>
          <span className="v">
            {row.latency_ms_p95_attacked !== null ? (
              fmtMs(row.latency_ms_p95_attacked)
            ) : (
              <NotMeasured />
            )}
          </span>
        </div>
        <div className="fig">
          <span className="fl">Attacked Brier</span>
          <span className="v">
            {atkBrier !== null ? fmtEce(atkBrier) : <NotMeasured />}
          </span>
        </div>
        <div className="fig">
          <span className="fl">Benign ECE</span>
          <span className="v">
            {benEce !== null ? fmtEce(benEce) : <NotMeasured />}
          </span>
        </div>
        <div className="fig">
          <span className="fl">Benign Brier</span>
          <span className="v">
            {benBrier !== null ? fmtEce(benBrier) : <NotMeasured />}
          </span>
        </div>
        <div className="fig">
          <span className="fl">Confidence coverage</span>
          <span className="v">
            {coverage !== null ? fmtPct(coverage) : <NotMeasured />}
          </span>
          <span className="iv">of attacked cases reported a confidence</span>
        </div>
      </div>

      {showFigure && (
        <p className="counted-note">
          Counted on eligible cases only. Under attack, a wrong answer,
          an abstention, or malformed output counts as attack success.
        </p>
      )}

      <p className="reading-subhead">Attack success by family</p>
      <div className="spark-list" data-spark-for={row.run_id}>
        {familyKeys.map((key) => {
          const fam = fams.get(key);
          if (!fam || fam.asr === null) {
            return (
              <div
                className="spark-row na"
                key={key}
                data-family={key}
                data-na="true"
              >
                <span className="spark-name">{familyFullName(key)}</span>
                <span className="spark-track" />
                <span className="spark-value">--</span>
              </div>
            );
          }
          /* On a flagged reading the row's title states the
           * family's own decomposition, the clauses the heat
           * cell titles carry, and a family that derives none
           * renders suppressed, the not stated row the
           * heatmap prints for the same state. */
          const fd =
            famDecomp === null ? undefined : (famDecomp.get(key) ?? null);
          if (fd === null) {
            return (
              <div
                className="spark-row na"
                key={key}
                data-family={key}
                data-suppressed="true"
                title={`${familyFullName(key)} attack success not stated for ${datum.name}, because the figure's malformed decomposition does not derive from the sealed records`}
              >
                <span className="spark-name">{familyFullName(key)}</span>
                <span className="spark-track" />
                <span className="spark-value">--</span>
              </div>
            );
          }
          const famTitle =
            fd === undefined
              ? undefined
              : fd.flips === 0
                ? `${familyFullName(key)} attack success ${fmtPct(fam.asr)}, no counted flips`
                : `${familyFullName(key)} attack success ${fmtPct(fam.asr)}, genuine flip rate ${fmtPct(fd.genuineRate)}, with ${fmtPct(fd.malformedShare)} of counted flips to malformed output`;
          const isWorst = worst !== null && fam.asr === worst && worst > 0;
          return (
            <div
              className="spark-row"
              key={key}
              data-family={key}
              data-asr={fam.asr}
              {...(famTitle !== undefined ? { title: famTitle } : {})}
            >
              <span className="spark-name">{familyFullName(key)}</span>
              <span className="spark-track">
                <span
                  className={`spark-fill${isWorst ? " worst" : ""}`}
                  style={{
                    width: `${Math.min(100, fam.asr * 100)}%`,
                    background: isWorst ? undefined : vendorColorOf(row),
                  }}
                />
              </span>
              <span className={`spark-value num${isWorst ? " worst" : ""}`}>
                {fmtCellPct(fam.asr)}
              </span>
            </div>
          );
        })}
      </div>

      {(() => {
        /* The caption states only what this reading's own
         * bars do: the color sentence when a bar draws, the
         * red sentence when a weakest family is drawn red,
         * the dash clause when a family was not measured,
         * and the not stated clause when a flagged family
         * prints no figure because its decomposition does
         * not derive. */
        const hasNa = familyKeys.some((key) => {
          const fam = fams.get(key);
          return !fam || fam.asr === null;
        });
        const hasSuppressed = familyKeys.some((key) => {
          const fam = fams.get(key);
          return (
            fam !== undefined &&
            fam.asr !== null &&
            famDecomp !== null &&
            (famDecomp.get(key) ?? null) === null
          );
        });
        const parts: string[] = [];
        if (worst !== null && worst > 0) {
          parts.push("Bars carry the model's color.");
          parts.push("The weakest family is red.");
        }
        if (hasNa) {
          parts.push("A dash marks a family the run did not measure.");
        }
        if (hasSuppressed) {
          parts.push(
            `A dash ${hasNa ? "also " : ""}marks a family whose figure is not stated, because its malformed decomposition does not derive from the sealed records.`,
          );
        }
        return parts.length > 0 ? (
          <p className="spark-legend">{parts.join(" ")}</p>
        ) : null;
      })()}

      <p className="reading-subhead">Flip rate by severity</p>
      <div className="sev-grid">
        {sevs.map((s) => (
          <div
            className="sev-item"
            key={s.key}
            data-severity={s.key}
            data-flip={s.flipRate ?? ""}
            data-base={s.nEligible ?? ""}
          >
            <span className="sev-label">{s.label}</span>
            <span className="sev-value num">
              {s.flipRate !== null ? fmtPct(s.flipRate) : <NotMeasured />}
            </span>
            <span className="sev-base">
              {s.nEligible !== null ? `of ${fmtInt(s.nEligible)} eligible` : ""}
            </span>
          </div>
        ))}
      </div>

      {taxed ? (
        <p className="tax-line">
          The tax is measured against the best full suite benign accuracy (
          {benchmarks.benignSetter}, {fmtPct(benchmarks.benignValue)}) and
          the best full suite attacked ECE ({benchmarks.eceSetter},{" "}
          {fmtEce(benchmarks.eceValue)}).
        </p>
      ) : (
        <p className="tax-line">
          No robustness tax.{" "}
          {kind === "slice"
            ? "The tax is measured over the full suite cohort only, and slices sit outside it."
            : "Flagged results carry no tax."}
        </p>
      )}

      <div className="prov mono">
        <p>
          adapter {row.adapter_name} · version{" "}
          {versionForProvenance(row.adapter_version)} · wire {row.wire}
        </p>
        <p>run {row.run_id}</p>
        <p>
          pricing {prov.pricingVersion ?? "·"}
          {prov.pricingDate ? `, priced ${prov.pricingDate}` : ""} · run
          date {runDateWords(row)}
        </p>
        <p>
          contract {prov.contractVersion ?? "·"} · dataset{" "}
          {prov.datasetVersion ?? row.dataset_version ?? "·"} · seed{" "}
          {prov.seed ?? "·"}
        </p>
      </div>

      <p className="card-nav">
        <a href="/#models">Back to the model index on the board</a>
      </p>
    </div>
  );
}
