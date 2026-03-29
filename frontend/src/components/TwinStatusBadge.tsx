import type { Twin } from "../api/twins";

const statusConfig: Record<Twin["status"], { label: string; dot: string; bg: string; text: string }> = {
  ingesting: { label: "Ingesting", dot: "bg-blue-400", bg: "bg-blue-50", text: "text-blue-700" },
  processing: { label: "Processing", dot: "bg-amber-400", bg: "bg-amber-50", text: "text-amber-700" },
  embedding: { label: "Embedding", dot: "bg-violet-400", bg: "bg-violet-50", text: "text-violet-700" },
  active: { label: "Active", dot: "bg-emerald-400", bg: "bg-emerald-50", text: "text-emerald-700" },
  error: { label: "Error", dot: "bg-red-400", bg: "bg-red-50", text: "text-red-700" },
  deleted: { label: "Deleted", dot: "bg-slate-300", bg: "bg-slate-50", text: "text-slate-500" },
};

export default function TwinStatusBadge({ status }: { status: Twin["status"] }) {
  const c = statusConfig[status] ?? { label: status, dot: "bg-slate-300", bg: "bg-slate-50", text: "text-slate-600" };

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${c.bg} ${c.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} aria-hidden="true" />
      {c.label}
    </span>
  );
}
