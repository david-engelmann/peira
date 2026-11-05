import {
  boardGroups,
  boardVersions,
  modelCounts,
} from "@/lib/payload";
import { explorerData } from "@/lib/explorerData";

/** The hero range prints at one decimal, as the published board's does. */
function pct1(v: number): string {
  return `${(Math.round(v * 1000) / 10).toFixed(1)}%`;
}
import VendorSprite from "@/components/VendorSprite";
import Findings from "@/components/Findings";
import Explorer from "@/components/Explorer";
import MethodStub from "@/components/MethodStub";

/**
 * The redesigned board, as a live prototype on the published
 * payload. The findings open the page and the explorer follows
 * as their evidence. Method stands in its diet form. Nothing
 * here is the published board.
 */

export default function Home() {
  const groups = boardGroups();
  const versions = boardVersions();
  const counts = modelCounts();
  const full = groups.full;
  const best = full[0]?.asr_conditional ?? null;
  const worst = full[full.length - 1]?.asr_conditional ?? null;
  const data = explorerData();

  return (
    <main className="page">
      <VendorSprite />
      <div className="proto-banner" role="note">
        Design prototype. This page rebuilds the board's opening on the
        live payload so the redesign can be judged by clicking it. It
        is not the published board, and the published board is
        unchanged.
      </div>
      <header className="masthead">
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
      </header>

      <section className="hero" id="top" aria-label="The board">
        <p className="micro">Paired measurement · Benign and attacked</p>
        <h1>Decision models, measured under attack</h1>
        <p className="hero-lede">
          Attack success counts a case only when the benign answer was
          right and the attacked side answered wrong, abstained, or
          produced malformed output.
          {best !== null && worst !== null && (
            <>
              {" "}
              On the full suite, attack success runs from{" "}
              {pct1(best)} to {pct1(worst)}.
            </>
          )}
        </p>
        <p className="hero-counts">{counts.sentence}</p>
      </section>

      <Findings />
      <Explorer data={data} />
      <MethodStub />

      <footer className="colophon">
        <p>
          Dataset {versions.dataset} · Suite {versions.suite} ·{" "}
          {counts.sentence} The figures derive from the sealed runs in
          the payload this page links.
        </p>
        <p>
          Prototype build of the board redesign. The published board
          stands unchanged at its own address.
        </p>
      </footer>
    </main>
  );
}
