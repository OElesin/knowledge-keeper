import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useTwins, useCreateTwin } from "../hooks/useTwins";
import { useIngestionStatus } from "../hooks/useIngestionStatus";
import TwinStatusBadge from "../components/TwinStatusBadge";
import type { CreateTwinPayload, Twin } from "../api/twins";
import { lookupEmployee } from "../api/twins";
import { applyLookup } from "../utils/applyLookup";

const emptyForm: CreateTwinPayload = {
  employeeId: "",
  name: "",
  email: "",
  role: "",
  department: "",
  offboardDate: "",
  provider: "google",
};

/* ── Stat card ── */
function StatCard({ label, value, icon }: { label: string; value: string | number; icon: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
          {icon}
        </div>
        <div>
          <p className="text-2xl font-bold text-slate-900">{value}</p>
          <p className="text-xs font-medium text-slate-500">{label}</p>
        </div>
      </div>
    </div>
  );
}

/* ── Twin card ── */
function TwinCard({ twin }: { twin: Twin }) {
  const initials = twin.name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className="group rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start gap-4">
        {/* Avatar */}
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-bold text-white">
          {initials}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <Link
              to={`/twins/${twin.employeeId}`}
              className="truncate text-sm font-semibold text-slate-900 group-hover:text-brand-600 transition-colors"
            >
              {twin.name}
            </Link>
            <TwinStatusBadge status={twin.status} />
          </div>
          <p className="mt-0.5 truncate text-xs text-slate-500">{twin.email}</p>
          <div className="mt-3 flex items-center gap-4 text-xs text-slate-500">
            <span className="flex items-center gap-1">
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m8 0H8m8 0a2 2 0 012 2v6a2 2 0 01-2 2H8a2 2 0 01-2-2V8a2 2 0 012-2" /></svg>
              {twin.role}
            </span>
            <span className="flex items-center gap-1">
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" /></svg>
              {twin.department}
            </span>
            <span className="flex items-center gap-1">
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" /></svg>
              {twin.chunkCount.toLocaleString()} chunks
            </span>
          </div>
        </div>
      </div>
      {/* Actions */}
      <div className="mt-4 flex items-center gap-2 border-t border-slate-100 pt-3">
        <Link
          to={`/twins/${twin.employeeId}`}
          className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 transition-colors"
        >
          Details
        </Link>
        {twin.status === "active" && (
          <Link
            to={`/twins/${twin.employeeId}/query`}
            className="rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-100 transition-colors"
          >
            Query Twin
          </Link>
        )}
      </div>
    </div>
  );
}

/* ── Main dashboard ── */
export default function AdminDashboard() {
  const { data: twins, isLoading, error } = useTwins();
  const pollingQuery = useIngestionStatus();
  const createTwin = useCreateTwin();
  const [form, setForm] = useState<CreateTwinPayload>({ ...emptyForm });
  const [showForm, setShowForm] = useState(false);
  const [, setArchiveFile] = useState<File | null>(null);
  const [lookupQuery, setLookupQuery] = useState("");
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);

  const displayTwins: Twin[] = pollingQuery.data ?? twins ?? [];

  const activeCount = displayTwins.filter((t) => t.status === "active").length;
  const ingestingCount = displayTwins.filter((t) =>
    ["ingesting", "processing", "embedding"].includes(t.status),
  ).length;
  const totalChunks = displayTwins.reduce((sum, t) => sum + t.chunkCount, 0);

  function handleChange(e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  async function handleLookup() {
    const trimmed = lookupQuery.trim();
    if (!trimmed) return;
    setLookupLoading(true);
    setLookupError(null);
    try {
      const record = await lookupEmployee(trimmed);
      setForm((prev) => applyLookup(prev, record));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Lookup failed";
      if (message.includes("EMPLOYEE_NOT_FOUND") || message.toLowerCase().includes("not found")) {
        setLookupError("No employee found. You can fill in the fields manually.");
      } else {
        setLookupError(message);
      }
    } finally {
      setLookupLoading(false);
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    createTwin.mutate(form, {
      onSuccess: () => {
        setForm({ ...emptyForm });
        setArchiveFile(null);
        setShowForm(false);
      },
    });
  }

  return (
    <div className="min-h-screen">
      {/* Page header */}
      <header className="border-b border-slate-200/60 bg-white">
        <div className="flex items-center justify-between px-8 py-5">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Dashboard</h1>
            <p className="mt-0.5 text-sm text-slate-500">Manage digital twins and offboarding</p>
          </div>
          <div className="flex items-center gap-3">
          <Link
            to="/settings"
            className="inline-flex items-center gap-2 rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            Settings
          </Link>
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-700"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            {showForm ? "Cancel" : "New Offboarding"}
          </button>
          </div>
        </div>
      </header>

      <div className="px-8 py-6">
        {/* Stats row */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Total Twins"
            value={displayTwins.length}
            icon={<svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" /></svg>}
          />
          <StatCard
            label="Active"
            value={activeCount}
            icon={<svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
          />
          <StatCard
            label="In Progress"
            value={ingestingCount}
            icon={<svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>}
          />
          <StatCard
            label="Total Chunks"
            value={totalChunks.toLocaleString()}
            icon={<svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" /></svg>}
          />
        </div>

        {/* Offboarding Form */}
        {showForm && (
          <form
            onSubmit={handleSubmit}
            className="mt-6 rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm"
          >
            <h2 className="text-base font-semibold text-slate-900">Offboard Employee</h2>
            <p className="mt-0.5 text-sm text-slate-500">Start the knowledge preservation process for a departing team member.</p>

            {createTwin.isError && (
              <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
                {(createTwin.error as Error).message}
              </div>
            )}
            {createTwin.isSuccess && (
              <div className="mt-4 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700" role="status">
                Twin created successfully. Ingestion has started.
              </div>
            )}

            {/* Directory Lookup */}
            <div className="mt-5 flex items-end gap-3">
              <label className="block flex-1">
                <span className="text-sm font-medium text-slate-700">Lookup Employee</span>
                <input
                  value={lookupQuery}
                  onChange={(e) => setLookupQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleLookup(); } }}
                  className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                  placeholder="Email or employee ID"
                />
              </label>
              <button
                type="button"
                onClick={handleLookup}
                disabled={lookupLoading || !lookupQuery.trim()}
                className="rounded-xl bg-slate-800 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-900 disabled:opacity-50"
              >
                {lookupLoading ? "Looking up…" : "Lookup"}
              </button>
            </div>
            {lookupError && (
              <div className="mt-3 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800" role="alert">
                {lookupError}
              </div>
            )}

            <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {([
                { name: "employeeId", label: "Employee ID", placeholder: "emp_123", type: "text" },
                { name: "name", label: "Full Name", placeholder: "Jane Doe", type: "text" },
                { name: "email", label: "Email", placeholder: "jane@company.com", type: "email" },
                { name: "role", label: "Role", placeholder: "Senior Engineer", type: "text" },
                { name: "department", label: "Department", placeholder: "Engineering", type: "text" },
                { name: "offboardDate", label: "Offboard Date", placeholder: "", type: "date" },
              ] as const).map((field) => (
                <label key={field.name} className="block">
                  <span className="text-sm font-medium text-slate-700">{field.label}</span>
                  <input
                    name={field.name}
                    type={field.type}
                    value={form[field.name]}
                    onChange={handleChange}
                    required
                    placeholder={field.placeholder}
                    className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                  />
                </label>
              ))}

              <label className="block">
                <span className="text-sm font-medium text-slate-700">Email Provider</span>
                <select
                  name="provider"
                  value={form.provider}
                  onChange={handleChange}
                  className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                >
                  <option value="google">Google Workspace</option>
                  <option value="microsoft">Microsoft 365</option>
                  <option value="upload">File Upload (.mbox)</option>
                </select>
              </label>

              {form.provider === "upload" && (
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Archive File</span>
                  <input
                    type="file"
                    accept=".mbox,.eml"
                    onChange={(e) => setArchiveFile(e.target.files?.[0] ?? null)}
                    className="mt-1.5 block w-full text-sm text-slate-500 file:mr-4 file:rounded-lg file:border-0 file:bg-brand-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100"
                  />
                  <p className="mt-1 text-xs text-slate-500">
                    Upload a .mbox or .eml file from the departing employee's mailbox export.
                  </p>
                </label>
              )}
            </div>

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={createTwin.isPending}
                className="rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-700 disabled:opacity-50"
              >
                {createTwin.isPending ? "Creating…" : "Start Offboarding"}
              </button>
            </div>
          </form>
        )}

        {/* Twin grid */}
        <div className="mt-6">
          <h2 className="text-sm font-semibold text-slate-900">Digital Twins</h2>

          {isLoading && (
            <div className="mt-4 flex items-center justify-center rounded-2xl border border-slate-200/60 bg-white py-16">
              <div className="flex items-center gap-3 text-sm text-slate-500">
                <svg className="h-5 w-5 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Loading twins…
              </div>
            </div>
          )}

          {error && (
            <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-6 py-8 text-center text-sm text-red-600">
              Failed to load twins: {(error as Error).message}
            </div>
          )}

          {!isLoading && !error && displayTwins.length === 0 && (
            <div className="mt-4 flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white py-16">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-50">
                <svg className="h-6 w-6 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
                </svg>
              </div>
              <p className="mt-3 text-sm font-medium text-slate-900">No digital twins yet</p>
              <p className="mt-1 text-sm text-slate-500">Click "New Offboarding" to get started.</p>
            </div>
          )}

          {!isLoading && !error && displayTwins.length > 0 && (
            <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
              {displayTwins.map((twin) => (
                <TwinCard key={twin.employeeId} twin={twin} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
