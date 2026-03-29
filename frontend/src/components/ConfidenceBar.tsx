function getColor(score: number): string {
  if (score >= 0.75) return "bg-emerald-500";
  if (score >= 0.5) return "bg-amber-500";
  return "bg-red-500";
}

function getLabel(score: number): string {
  if (score >= 0.75) return "High";
  if (score >= 0.5) return "Medium";
  return "Low";
}

export default function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs font-medium text-slate-500">Confidence</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`Confidence: ${pct}%`}>
        <div className={`h-full rounded-full transition-all ${getColor(score)}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-semibold text-slate-700">{pct}% — {getLabel(score)}</span>
    </div>
  );
}
