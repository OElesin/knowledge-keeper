import type { Twin } from "../api/twins";

const statusConfig: Record<Twin["status"], { label: string; className: string }> = {
  ingesting: { label: "Ingesting", className: "bg-blue-100 text-blue-800" },
  processing: { label: "Processing", className: "bg-yellow-100 text-yellow-800" },
  embedding: { label: "Embedding", className: "bg-purple-100 text-purple-800" },
  active: { label: "Active", className: "bg-green-100 text-green-800" },
  error: { label: "Error", className: "bg-red-100 text-red-800" },
  deleted: { label: "Deleted", className: "bg-gray-100 text-gray-500" },
};

export default function TwinStatusBadge({ status }: { status: Twin["status"] }) {
  const config = statusConfig[status] ?? { label: status, className: "bg-gray-100 text-gray-800" };

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${config.className}`}
    >
      {config.label}
    </span>
  );
}
