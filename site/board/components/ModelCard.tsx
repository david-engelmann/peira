import {
  shortName,
  wireWords,
  displayCi,
  modelSlug,
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
  shortHash,
  versionForProvenance,
} from "@/lib/cards";
import VendorLogo from "./VendorLogo";

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
  const carried = familyKeys
    .map((key) => ({ key, fam: fams.get(key) }))
    .filter((e) => e.fam && e.fam.asr !== null);
  const worst = carried.length
    ? Math.max(...carried.map((e) => e.fam!.asr as number))
    : null;
  const taxed = row.robustness_tax !== null && row.robustness_tax !== undefined;
  const atkEce = arms?.attacked.ece ?? row.ece_attacked;
  const atkBrier = arms?.attacked.brier ?? null;
  const benEce = arms?.benign.ece ?? null;
  const benBrier = arms?.benign.brier ?? null;
  const coverage = arms?.coverageAttacked ?? null;

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
            {row.asr_conditional !== null ? fmtPct(row.asr_conditional) : <NotMeasured />}
          </span>
          {ci !== null && (
            <span className="hl-sub num">95% CI {fmtCi(ci)}</span>
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
      <div className="spark-list">
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
                <span className="spark-track">
                  <span className="spark-slot">·</span>
                </span>
                <span className="spark-value">·</span>
              </div>
            );
          }
          const isWorst = worst !== null && fam.asr === worst && worst > 0;
          return (
            <div
              className="spark-row"
              key={key}
              data-family={key}
              data-asr={fam.asr}
            >
              <span className="spark-name">{familyFullName(key)}</span>
              <span className="spark-track">
                <span
                  className={`spark-fill${isWorst ? " worst" : ""}`}
                  style={{ width: `${Math.min(100, fam.asr * 100)}%` }}
                />
              </span>
              <span className={`spark-value num${isWorst ? " worst" : ""}`}>
                {fmtCellPct(fam.asr)}
              </span>
            </div>
          );
        })}
      </div>

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
          Robustness tax {fmtTax(row.robustness_tax as number)}. The tax
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
          {prov.seed ?? "·"} · manifest{" "}
          {prov.manifestSha256 ? shortHash(prov.manifestSha256) : "·"}
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
