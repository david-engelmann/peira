import { boardGroups, boardVersions, dateWords } from "@/lib/payload";
import { explorerData } from "@/lib/explorerData";
import VendorSprite from "@/components/VendorSprite";
import TopBar from "@/components/TopBar";
import Headline from "@/components/Headline";
import StudyFindings from "@/components/StudyFindings";
import Explorer from "@/components/Explorer";
import MethodStub from "@/components/MethodStub";

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
      <StudyFindings />
      <Explorer data={explorerData()} />
      <MethodStub />
      <footer className="colophon study-footer">
        <div><b>Peira</b><span>Dataset {versions.dataset} · Suite {versions.suite}</span><a href="/payload.json" download>Download data (JSON)</a></div>
        {dates.length > 0 && <details><summary>Run history</summary><p>{dates.length} results link to earlier runs. Their records are dated {dateWords(dates[0])}{dates[0] !== dates[dates.length - 1] && ` through ${dateWords(dates[dates.length - 1])}`}. Each result shows its own measurements and run history in the explorer.</p></details>}
      </footer>
    </main>
  );
}
