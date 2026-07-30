import type { AtsScore } from "../api";

export function AtsScoreBadge({ label, score }: { label: string; score: AtsScore }) {
  return (
    <div className="ats-score">
      <span className="ats-label">{label} keyword match (heuristic estimate)</span>
      <span className="ats-value">
        {score.original}% <span aria-hidden="true">→</span> {score.tailored}%
      </span>
    </div>
  );
}
