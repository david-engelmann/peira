import {
  boardDateWords,
  boardGroups,
  boardVersions,
  modelCounts,
  multiResultModels,
} from "@/lib/payload";
import { fmtInt, fmtPct } from "@/lib/format";
import { explorerData } from "@/lib/explorerData";
import Findings from "@/components/Findings";
import Explorer from "@/components/Explorer";
import Method from "@/components/Method";

/**
 * The board. The findings open the page and state what the
 * numbers mean, the one explorer follows as their evidence,
 * and Method states the rules once in its diet form. The nine
 * numbered sections of the previous board are gone, and no
 * surface repeats a figure another surface already carries
 * outside the recorded reasons in the build spec.
 */

export default function Home() {
  const groups = boardGroups();
  const versions = boardVersions();
  const counts = modelCounts();
  const multi = multiResultModels();
  const updated = boardDateWords();
  const total =
    groups.full.length + groups.slices.length + groups.flagged.length;
  const countsFirst =
    `The board holds ${fmtInt(total)} results from ${fmtInt(counts.tested)} models.`;
  const countsRest =
    ` ${fmtInt(counts.ranked)} models are ranked and ${fmtInt(counts.flagged)} are flagged.` +
    (multi.length === 1
      ? " One model was measured on two wires, so it appears as two results."
      : multi.length > 1
        ? ` ${fmtInt(multi.length)} models were measured on two wires, so each appears as two results.`
        : "");
  const full = groups.full;
  const best = full[0]?.asr_conditional ?? null;
  const worst = full[full.length - 1]?.asr_conditional ?? null;
  const data = explorerData();

  return (
    <main className="page" id="main">
      <header className="masthead">
        <div className="masthead-row">
          <a className="brand" href="#top" aria-label="peira, back to the top">
            <svg viewBox="0 0 64 64" width="26" height="26" aria-hidden="true">
              <rect width="64" height="64" rx="12" fill="#0A0C0F" />
              <rect x="14" y="34" width="9" height="16" fill="#E9EEF3" />
              <rect x="27" y="24" width="9" height="26" fill="#E9EEF3" />
              <rect x="40" y="14" width="9" height="36" fill="#2FBF71" />
            </svg>
            <span className="brand-name">peira</span>
          </a>
          <nav className="mastnav" aria-label="Page">
            <a href="#findings">Findings</a>
            <a href="#explorer">Explorer</a>
            <a href="#method">Method</a>
            <a href="/payload.json">Payload</a>
          </nav>
        </div>
        <p className="stamp">
          dataset {versions.dataset}, suite {versions.suite}, updated{" "}
          {updated}
        </p>
      </header>

      <section className="hero" id="top" aria-label="The board">
        <p className="micro">Paired measurement · Benign and attacked</p>
        <h1>Decision models, measured under attack</h1>
        <p className="hero-lead">
          Every model decided the same paired cases, each case in a
          benign form and an attacked form.
        </p>
        <p className="hero-lede">
          Attack success counts a case only when the benign answer was
          right and the attacked side answered wrong, abstained, or
          produced malformed output.
        </p>
        {best !== null && worst !== null && (
          <p className="hero-range">
            On the full suite, attack success runs from {fmtPct(best)} to{" "}
            {fmtPct(worst)}.
          </p>
        )}
        <p className="hero-counts">
          {countsFirst}
          <span className="counts-rest">{countsRest}</span>
        </p>
      </section>

      <Findings />
      <Explorer data={data} />
      <Method />

      <footer className="colophon">
        <p>
          Engelmann, D. Peira decision robustness board. Dataset{" "}
          {versions.dataset}, suite {versions.suite}, updated {updated}.
          Corrections land by republishing the payload, with the
          change recorded.{" "}
          <a href="https://github.com/david-engelmann/peira">
            Code and method on GitHub
          </a>{" "}
          · <a href="/payload.json">Payload behind this page</a>
        </p>
      </footer>
    </main>
  );
}
