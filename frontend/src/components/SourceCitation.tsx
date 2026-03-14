import { useState } from "react";
import type { ChunkSource } from "../api/twins";

export default function SourceCitation({ source }: { source: ChunkSource }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-md border border-gray-200 bg-white">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm hover:bg-gray-50"
        aria-expanded={expanded}
      >
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-gray-900">{source.subject || "No subject"}</p>
          <p className="mt-0.5 text-xs text-gray-500">{source.date}</p>
        </div>
        <svg
          className={`ml-3 h-4 w-4 shrink-0 text-gray-400 transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded && (
        <div className="border-t border-gray-200 px-4 py-3">
          <p className="whitespace-pre-wrap text-sm text-gray-700">{source.content}</p>
        </div>
      )}
    </div>
  );
}
