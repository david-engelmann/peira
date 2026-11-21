import { boardGroups, boardVersions, dateWords } from "@/lib/payload";
import { explorerData } from "@/lib/explorerData";
import VendorSprite from "@/components/VendorSprite";
import TopBar from "@/components/TopBar";
import ModelGroups from "@/components/ModelGroups";
import { modelProfile } from "@/lib/modelProfile";
import Headline from "@/components/Headline";
import StudyFindings from "@/components/StudyFindings";
import Explorer from "@/components/Explorer";
import MethodStub from "@/components/MethodStub";
import { shareMetadata } from "@/lib/shareMetadata";

export const metadata = shareMetadata({
  title: "Peira | Decision robustness benchmark",
  description: "Compare AI decisions before and after an attack. Explore model rankings, attack families, run costs and the evidence behind each result.",
  path: "/",
  imagePath: "/opengraph-image",
  imageAlt: "Peira decision robustness benchmark. Attack success across the ranked full-suite results, from lowest to highest.",
});

export default function Home() {
  const versions = boardVersions();
  const groups = boardGroups();
  const dates = [...groups.full, ...groups.slices, ...groups.flagged]
    .map(r => r.rerun?.date).filter((d): d is string => typeof d === "string").sort();
  return (
    <main className="page study" id="top">
      <VendorSprite />
      <TopBar />
      <Headline />
      <ModelGroups observations={groups.full.flatMap(row =>
        row.asr_conditional === null ? [] : [{ rate: row.asr_conditional, profile: modelProfile(row) }]
      )} />
      <StudyFindings />
      <Explorer data={explorerData()} />
      <MethodStub />
      <footer className="colophon study-footer">
        <div className="footer-bar">
          <div className="footer-edition"><b>Peira</b><span>Dataset {versions.dataset} · Suite {versions.suite}</span></div>
          <nav aria-label="Project resources">
            <a href="https://github.com/david-engelmann/peira">GitHub <span aria-hidden="true">↗</span></a>
            <a href="https://github.com/david-engelmann/peira/blob/main/docs/Methodology.md">Methodology</a>
            <a href="/payload.json" download>Download JSON <span aria-hidden="true">↓</span></a>
          </nav>
        </div>
        {dates.length > 0 && <details><summary>Run history</summary><p>{dates.length} results link to earlier runs. Their records are dated {dateWords(dates[0])}{dates[0] !== dates[dates.length - 1] && ` through ${dateWords(dates[dates.length - 1])}`}. Each result shows its own measurements and run history in the explorer.</p></details>}
      </footer>
    </main>
  );
}
