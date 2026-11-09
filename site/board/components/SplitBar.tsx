import { fmtPct } from "@/lib/format";

/**
 * The split bar, one population's counted flips divided into
 * genuine changes of mind and malformed output. In its figured
 * form the malformed share stands large inside the malformed
 * segment itself, the treatment the share card's mercury bar
 * carries, rather than only in the labels under the bar. The
 * bare form renders the track alone for the headline stack,
 * whose own caption states the split in words.
 */
export default function SplitBar({
  label,
  figured,
  malformedShare,
  malformedLabel,
  genuineLabel,
  figuredInBar = false,
  bare = false,
}: {
  label: string;
  figured: string;
  malformedShare: number;
  malformedLabel: string;
  genuineLabel: string;
  figuredInBar?: boolean;
  bare?: boolean;
}) {
  const malformedPct = Math.max(0, Math.min(100, malformedShare * 100));
  return (
    <div className={`splitbar${figuredInBar ? " figured" : ""}`}>
      {!bare && (
        <div className="splitbar-head">
          <span className="micro">{label}</span>
          <span className="splitbar-figured">{figured}</span>
        </div>
      )}
      <div
        className="splitbar-track"
        role="img"
        aria-label={`${malformedLabel}, ${genuineLabel}`}
      >
        <span
          className="seg genuine"
          style={{ width: `${100 - malformedPct}%` }}
        />
        <span className="seg malformed" style={{ width: `${malformedPct}%` }}>
          {figuredInBar && (
            <span className="inbar-fig">{fmtPct(malformedShare)}</span>
          )}
        </span>
      </div>
      {!bare && (
        <div className="splitbar-labels">
          <span>{genuineLabel}</span>
          <span className="amber-text">{malformedLabel}</span>
        </div>
      )}
    </div>
  );
}
