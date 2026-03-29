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
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <svg className="h-5 w-5 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading…
        </div>
      </div>
    );
  }

  if (!twin) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-red-600">Twin not found</p>
          <Link to="/" className="mt-2 inline-block text-sm font-medium text-brand-600 hover:text-brand-700">
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  const isActive = twin.status === "active";

  const initials = twin.name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <header className="border-b border-slate-200/60 bg-white">
        <div className="flex items-center justify-between px-8 py-4">
          <div className="min-w-0">
            <nav className="flex items-center gap-1.5 text-sm text-slate-500">
              <Link to="/" className="hover:text-brand-600 transition-colors">Dashboard</Link>
              <svg className="h-4 w-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
              <Link to={`/twins/${twin.employeeId}`} className="hover:text-brand-600 transition-colors">{twin.name}</Link>
              <svg className="h-4 w-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
              <span className="font-medium text-slate-900">Query</span>
            </nav>
            <div className="mt-1.5 flex items-center gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-xs font-bold text-white">
                {initials}
              </div>
              <div>
                <h1 className="text-base font-bold text-slate-900">
                  Ask {twin.name}'s Knowledge Base
                </h1>
                <p className="text-xs text-slate-500">
                  {twin.role} · {twin.department} · {twin.chunkCount.toLocaleString()} chunks indexed
                </p>
              </div>
            </div>
          </div>
          <TwinStatusBadge status={twin.status} />
        </div>
      </header>

      {/* Chat area */}
      <div className="flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto max-w-3xl space-y-6">
          {!isActive && (
            <div className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800" role="alert">
              This twin is not yet active for querying. Current status: <span className="font-medium">{twin.status}</span>
            </div>
          )}

          {history.length === 0 && isActive && (
            <div className="py-20 text-center">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50">
                <svg className="h-7 w-7 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                </svg>
              </div>
              <p className="mt-4 text-sm font-medium text-slate-900">
                Ask a question about {twin.name}'s work
              </p>
              <p className="mt-1 text-sm text-slate-500">
                Answers are grounded in their email archive with source citations.
              </p>
            </div>
          )}

          {history.map((entry, i) => (
            <div key={i} className="space-y-4">
              {/* User query */}
              <div className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl rounded-br-md bg-brand-600 px-5 py-3 text-sm text-white shadow-sm">
                  {entry.query}
                </div>
              </div>

              {/* Response */}
              {entry.loading && (
                <div className="flex items-center gap-2.5 text-sm text-slate-500">
                  <svg className="h-4 w-4 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Searching knowledge base…
                </div>
              )}

              {entry.error && (
                <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
                  {entry.error}
                </div>
              )}

              {entry.response && (
                <div className="space-y-3 rounded-2xl rounded-bl-md border border-slate-200/60 bg-white p-5 shadow-sm">
                  {entry.response.staleness_warning && (
                    <StalenessWarning message={entry.response.staleness_warning} />
                  )}

                  <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                    {entry.response.answer}
                  </div>

                  <ConfidenceBar score={entry.response.confidence} />

                  {entry.response.sources.length > 0 && (
                    <div className="mt-2">
                      <p className="mb-2 text-xs font-semibold text-slate-500">
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
      <div className="border-t border-slate-200/60 bg-white px-8 py-4">
        <form onSubmit={handleSubmit} className="mx-auto flex max-w-3xl gap-3">
          <label className="sr-only" htmlFor="query-input">Ask a question</label>
          <input
            id="query-input"
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={!isActive}
            placeholder={isActive ? "Ask a question…" : "Twin not active"}
            className="block flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none disabled:bg-slate-100 disabled:text-slate-400"
          />
          <button
            type="submit"
            disabled={!isActive || mutation.isPending || !input.trim()}
            className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-700 disabled:opacity-50"
          >
            {mutation.isPending ? (
              "Asking…"
            ) : (
              <>
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                </svg>
                Ask
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
