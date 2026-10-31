import {
  shortName,
  wireWords,
  displayCi,
  modelSlug,
  flipDecomposition,
  familyFlipDecomposition,
  type BoardRow,
  type TaxBenchmarks,
} from "@/lib/payload";
import {
  fmtPct,
  fmtCi,
  fmtEce,
  fmtInt,
  fmtMs,
  fmtTax,
  fmtUsd,
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
  costStateOf,
  runDateWords,
  versionForProvenance,
} from "@/lib/cards";
import VendorLogo from "./VendorLogo";
import { vendorColorOf } from "@/lib/vendorColors";

/**
 * The full detail card for one result, design system section
 * 4.5. One fixed anatomy for all 36 results, so a reader learns
 * the order once: header statement and model ID, headline
 * figures, the stat grid, family spark bars, the severity line,
 * the tax line, and the provenance block. The same body renders
 * inside the board's collapsed index and on the result's own
 * page, so the two can never disagree.
 *
 * Benchmark names on the tax line come from the tax derivation
 * itself (lib/payload taxBenchmarks, over the full suite ranked
 * cohort only), never from prose, so a card cannot name a
 * benchmark its tax was not computed against.
 */

export type CardKind = "full" | "flagged" | "slice";

function NotMeasured() {
  return <span className="not-measured-inline">·</span>;
}

function rankStatement(
  kind: CardKind,
  rank: number | null,
  groupSize: number,
): string {
  if (kind === "flagged") return "Flagged";
  if (kind === "slice") {
    return `Rank ${rank} of ${groupSize} on the guardrail slice`;
  }
  return `Rank ${rank} of ${groupSize} in the full suite`;
}

export default function ModelCard({
  row,
  rank,
  kind,
  groupSize,
  benchmarks,
  familyKeys,
  allRows,
  standalone,
}: {
  row: BoardRow;
  rank: number | null;
  kind: CardKind;
  groupSize: number;
  benchmarks: TaxBenchmarks;
  familyKeys: string[];
  allRows: BoardRow[];
  standalone: boolean;
}) {
  const ci = displayCi(row);
  const cost = costStateOf(row);
  const arms = calibrationArmsOf(row);
  const sevs = severitiesOf(row);
  const prov = provenanceOf(row);
  const fams = familiesOf(row);
  /* A flagged card's per-family figures travel with their
   * own decompositions (C-5), the discipline the heatmap's
   * cell titles and the compare family lines already keep.
   * A family whose sealed records derive no decomposition
   * prints no figure in the spark list below, and it cannot
   * be the weakest family drawn red, since no bar draws
   * for it. */
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
  const atkEce = arms?.attacked.ece ?? row.ece_attacked;
  const atkBrier = arms?.attacked.brier ?? null;
  const benEce = arms?.benign.ece ?? null;
  const benBrier = arms?.benign.brier ?? null;
  const coverage = arms?.coverageAttacked ?? null;
  /* A flagged card's headline figure travels with its flip
   * decomposition (C-5), stated in the reason paragraph
   * above. Where the sealed records derive no decomposition,
   * the headline states no figure at all, the suppression
   * the compare section follows, so the card body cannot
   * print the figure bare even if the render law regresses. */
  const decomp = kind === "flagged" ? flipDecomposition(row) : null;
  const showFigure =
    row.asr_conditional !== null && (kind !== "flagged" || decomp !== null);

  return (
    <div className="card-body">
      <div className="card-head">
        <div className="card-head-top">
          <VendorLogo row={row} size="card" />
          <div>
            <p className="card-statement">
              {rankStatement(kind, rank, groupSize)}
            </p>
            <p className="card-model-id mono">{row.display_name}</p>
            <p className="card-wire">Wire {wireWords(row.wire)}</p>
          </div>
        </div>
        {kind === "flagged" && row.malformed_rate !== null && (
          <p className="card-reason flagged">
            Its malformed response rate of {fmtPct(row.malformed_rate)} is
            over the 5 percent admission limit, so it keeps every number
            and is not ranked.
            {decomp !== null && (
              <>
                {" "}
                Genuine flip rate {fmtPct(decomp.genuineRate)}, with{" "}
                {fmtPct(decomp.malformedShare)} of counted flips to
                malformed output.
              </>
            )}
          </p>
        )}
        {kind === "slice" && (
          <p className="card-reason">
            A guardrail slice result, measured on the abstain subset
            rather than the full suite, so its rates are not comparable
            to full suite results.
          </p>
        )}
      </div>

      <div className="card-headline">
        <div className="hl-fig">
          <span className="hl-label">Attack success</span>
          <span className="hl-value num">
            {showFigure ? fmtPct(row.asr_conditional!) : <NotMeasured />}
          </span>
          {ci !== null && showFigure && (
            <span className="hl-sub num">95% CI {fmtCi(ci)}</span>
          )}
          {showFigure && (
            <span className="hl-sub">
              Counted on eligible cases only. Under attack, a wrong
              answer, an abstention, or malformed output counts as
              attack success.
            </span>
          )}
        </div>
        <div className="hl-fig">
          <span className="hl-label">Benign accuracy</span>
          <span className="hl-value num">
            {row.benign_accuracy !== null ? fmtPct(row.benign_accuracy) : <NotMeasured />}
          </span>
        </div>
        <div className="hl-fig">
          <span className="hl-label">Malformed rate</span>
          <span className="hl-value num">
            {row.malformed_rate !== null ? fmtPct(row.malformed_rate) : <NotMeasured />}
          </span>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat">
          <span className="stat-label">Cost per run</span>
          <span className="stat-value num">
            {cost.kind === "amount" && fmtUsd(cost.value)}
            {cost.kind === "lower-bound" && <>≥ {fmtUsd(cost.value)}</>}
            {cost.kind === "local" && fmtUsd(0)}
            {cost.kind === "unrecorded" && <NotMeasured />}
          </span>
          <span className="stat-sub">
            {cost.kind === "lower-bound" &&
              "a lower bound, some calls went unpriced"}
            {cost.kind === "local" && "served locally, no API cost"}
            {cost.kind === "unrecorded" && "no cost recorded"}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Latency p50, attacked</span>
          <span className="stat-value num">
            {row.latency_ms_p50_attacked !== null ? (
              fmtMs(row.latency_ms_p50_attacked)
            ) : (
              <NotMeasured />
            )}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Latency p95, attacked</span>
          <span className="stat-value num">
            {row.latency_ms_p95_attacked !== null ? (
              fmtMs(row.latency_ms_p95_attacked)
            ) : (
              <NotMeasured />
            )}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Attacked ECE</span>
          <span className="stat-value num">
            {atkEce !== null ? fmtEce(atkEce) : <NotMeasured />}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Attacked Brier</span>
          <span className="stat-value num">
            {atkBrier !== null ? fmtEce(atkBrier) : <NotMeasured />}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Benign ECE</span>
          <span className="stat-value num">
            {benEce !== null ? fmtEce(benEce) : <NotMeasured />}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Benign Brier</span>
          <span className="stat-value num">
            {benBrier !== null ? fmtEce(benBrier) : <NotMeasured />}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Confidence coverage</span>
          <span className="stat-value num">
            {coverage !== null ? fmtPct(coverage) : <NotMeasured />}
          </span>
          <span className="stat-sub">
            of attacked cases reported a confidence
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Robustness tax</span>
          <span className="stat-value num">
            {taxed ? fmtTax(row.robustness_tax as number) : <NotMeasured />}
          </span>
        </div>
      </div>

      <p className="card-subhead">Attack success by family</p>
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
                <span className="spark-name">
                  {familyFullName(key)}
                </span>
                <span className="spark-track" />
                <span className="spark-value">--</span>
              </div>
            );
          }
          /* On a flagged card the row's title states the
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
                title={`${familyFullName(key)} attack success not stated for ${shortName(row)}, because the figure's malformed decomposition does not derive from the sealed records`}
              >
                <span className="spark-name">
                  {familyFullName(key)}
                </span>
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
        /* The caption states only what this card's own bars do
           (cycle 6, C6-13): the color sentence when a bar draws,
           the red sentence when a weakest family is drawn red,
           the dash clause when a family was not measured, and
           the not stated clause when a flagged family prints
           no figure because its decomposition does not derive. */
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

      <p className="card-subhead">Flip rate by severity</p>
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
              {s.nEligible !== null
                ? `of ${fmtInt(s.nEligible)} eligible`
                : ""}
            </span>
          </div>
        ))}
      </div>

      {taxed ? (
        <p className="tax-line">
          The tax
          is measured against the best full suite benign accuracy (
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
        {standalone ? (
          <a href="/#models">Back to the model index on the board</a>
        ) : (
          <>
            <a href="#models">Back to the top of the model index</a>
            <a href={`/models/${modelSlug(row, allRows)}/`}>
              This result on its own page
            </a>
          </>
        )}
      </p>
    </div>
  );
}
