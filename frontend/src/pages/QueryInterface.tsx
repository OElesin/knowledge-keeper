import { useState, useRef, useEffect, type FormEvent } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { useTwin } from "../hooks/useTwins";
import { queryTwin, type QueryResponse } from "../api/twins";
import TwinStatusBadge from "../components/TwinStatusBadge";
import SourceCitation from "../components/SourceCitation";
import ConfidenceBar from "../components/ConfidenceBar";
import StalenessWarning from "../components/StalenessWarning";

interface ChatEntry {
  query: string;
  response: QueryResponse | null;
  error: string | null;
  loading: boolean;
}

export default function QueryInterface() {
  const { employeeId } = useParams<{ employeeId: string }>();
  const { data: twin, isLoading: twinLoading } = useTwin(employeeId!);

  const [input, setInput] = useState("");
  const [history, setHistory] = useState<ChatEntry[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  const mutation = useMutation({
    mutationFn: (query: string) => queryTwin(employeeId!, query),
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const query = input.trim();
    if (!query || mutation.isPending) return;

    const idx = history.length;
    setHistory((h) => [...h, { query, response: null, error: null, loading: true }]);
    setInput("");

    mutation.mutate(query, {
      onSuccess: (response) => {
        setHistory((h) =>
          h.map((entry, i) => (i === idx ? { ...entry, response, loading: false } : entry)),
        );
      },
      onError: (err) => {
        setHistory((h) =>
          h.map((entry, i) =>
            i === idx ? { ...entry, error: (err as Error).message, loading: false } : entry,
          ),
        );
      },
    });
  }

  if (twinLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <p className="text-sm text-gray-500">Loading…</p>
      </div>
    );
  }

  if (!twin) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-center">
          <p className="text-sm text-red-600">Twin not found</p>
          <Link to="/" className="mt-2 inline-block text-sm text-indigo-600 hover:text-indigo-800">
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  const isActive = twin.status === "active";

  return (
    <div className="flex min-h-screen flex-col bg-gray-50">
      {/* Header */}
      <header className="border-b border-gray-200 bg-white px-4 py-4">
        <div className="mx-auto flex max-w-4xl items-center justify-between">
          <div className="min-w-0">
            <nav className="text-sm text-gray-500">
              <Link to="/" className="hover:text-indigo-600">Dashboard</Link>
              <span className="mx-2">/</span>
              <Link to={`/twins/${twin.employeeId}`} className="hover:text-indigo-600">{twin.name}</Link>
              <span className="mx-2">/</span>
              <span className="text-gray-900">Query</span>
            </nav>
            <h1 className="mt-1 text-lg font-bold text-gray-900">
              Ask {twin.name}'s Knowledge Base
            </h1>
            <p className="text-xs text-gray-500">
              {twin.role} · {twin.department} · {twin.chunkCount.toLocaleString()} chunks indexed
            </p>
          </div>
          <TwinStatusBadge status={twin.status} />
        </div>
      </header>

      {/* Chat area */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto max-w-4xl space-y-6">
          {!isActive && (
            <div className="rounded-md bg-yellow-50 px-4 py-3 text-sm text-yellow-800" role="alert">
              This twin is not yet active for querying. Current status: <span className="font-medium">{twin.status}</span>
            </div>
          )}

          {history.length === 0 && isActive && (
            <div className="py-16 text-center">
              <p className="text-sm text-gray-500">
                Ask a question about {twin.name}'s work, decisions, or communications.
              </p>
              <p className="mt-1 text-xs text-gray-400">
                Answers are grounded in their email archive with source citations.
              </p>
            </div>
          )}

          {history.map((entry, i) => (
            <div key={i} className="space-y-4">
              {/* User query */}
              <div className="flex justify-end">
                <div className="max-w-[80%] rounded-lg bg-indigo-600 px-4 py-3 text-sm text-white">
                  {entry.query}
                </div>
              </div>

              {/* Response */}
              {entry.loading && (
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <svg className="h-4 w-4 animate-spin text-indigo-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Searching knowledge base…
                </div>
              )}

              {entry.error && (
                <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
                  {entry.error}
                </div>
              )}

              {entry.response && (
                <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
                  {entry.response.staleness_warning && (
                    <StalenessWarning message={entry.response.staleness_warning} />
                  )}

                  <div className="whitespace-pre-wrap text-sm text-gray-800">
                    {entry.response.answer}
                  </div>

                  <ConfidenceBar score={entry.response.confidence} />

                  {entry.response.sources.length > 0 && (
                    <div className="mt-2">
                      <p className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-500">
                        Sources ({entry.response.sources.length})
                      </p>
                      <div className="space-y-2">
                        {entry.response.sources.map((src) => (
                          <SourceCitation key={src.key} source={src} />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input bar */}
      <div className="border-t border-gray-200 bg-white px-4 py-4">
        <form onSubmit={handleSubmit} className="mx-auto flex max-w-4xl gap-3">
          <label className="sr-only" htmlFor="query-input">Ask a question</label>
          <input
            id="query-input"
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={!isActive}
            placeholder={isActive ? "Ask a question…" : "Twin not active"}
            className="block flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500 disabled:bg-gray-100 disabled:text-gray-400"
          />
          <button
            type="submit"
            disabled={!isActive || mutation.isPending || !input.trim()}
            className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {mutation.isPending ? "Asking…" : "Ask"}
          </button>
        </form>
      </div>
    </div>
  );
}
