import { useState, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useTwin, useDeleteTwin, useAccess, useGrantAccess, useRevokeAccess } from "../hooks/useTwins";
import TwinStatusBadge from "../components/TwinStatusBadge";
import type { GrantAccessPayload, EmployeeRecord } from "../api/twins";
import { lookupEmployee } from "../api/twins";

export default function TwinDetail() {
  const { employeeId } = useParams<{ employeeId: string }>();
  const navigate = useNavigate();

  const { data: twin, isLoading, error } = useTwin(employeeId!);
  const { data: accessList, isLoading: accessLoading } = useAccess(employeeId!);
  const deleteTwin = useDeleteTwin();
  const grantAccess = useGrantAccess(employeeId!);
  const revokeAccess = useRevokeAccess(employeeId!);

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [accessForm, setAccessForm] = useState<GrantAccessPayload>({ userId: "", role: "viewer" });

  const [lookupQuery, setLookupQuery] = useState("");
  const [lookupResult, setLookupResult] = useState<EmployeeRecord | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookupTimer, setLookupTimer] = useState<ReturnType<typeof setTimeout> | null>(null);

  const debouncedLookup = useCallback((query: string) => {
    if (lookupTimer) clearTimeout(lookupTimer);
    setLookupResult(null);
    setLookupError(null);

    if (query.trim().length < 2) return;

    const timer = setTimeout(async () => {
      setLookupLoading(true);
      try {
        const result = await lookupEmployee(query.trim());
        setLookupResult(result);
        setAccessForm((f) => ({ ...f, userId: result.employeeId }));
      } catch {
        setLookupError("No match found — you can enter a User ID manually below");
      } finally {
        setLookupLoading(false);
      }
    }, 400);
    setLookupTimer(timer);
  }, [lookupTimer]);

  function clearLookup() {
    setLookupQuery("");
    setLookupResult(null);
    setLookupError(null);
    setAccessForm((f) => ({ ...f, userId: "" }));
  }

  function handleGrantAccess(e: React.FormEvent) {
    e.preventDefault();
    if (!accessForm.userId.trim()) return;
    grantAccess.mutate(accessForm, {
      onSuccess: () => {
        setAccessForm({ userId: "", role: "viewer" });
        clearLookup();
      },
    });
  }

  function handleDelete() {
    deleteTwin.mutate(employeeId!, {
      onSuccess: () => navigate("/"),
    });
  }

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <svg className="h-5 w-5 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading twin details…
        </div>
      </div>
    );
  }

  if (error || !twin) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-red-600">{(error as Error)?.message ?? "Twin not found"}</p>
          <Link to="/" className="mt-2 inline-block text-sm font-medium text-brand-600 hover:text-brand-700">
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  const initials = twin.name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div className="min-h-screen">
      {/* Page header */}
      <header className="border-b border-slate-200/60 bg-white">
        <div className="px-8 py-5">
          <nav className="flex items-center gap-1.5 text-sm text-slate-500">
            <Link to="/" className="hover:text-brand-600 transition-colors">Dashboard</Link>
            <svg className="h-4 w-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
            <span className="text-slate-900 font-medium">{twin.name}</span>
          </nav>
        </div>
      </header>

      <div className="px-8 py-6 space-y-6">
        {/* Twin profile card */}
        <div className="rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
          <div className="flex items-start gap-5">
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-lg font-bold text-white">
              {initials}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-bold text-slate-900">{twin.name}</h1>
                <TwinStatusBadge status={twin.status} />
              </div>
              <p className="mt-0.5 text-sm text-slate-500">{twin.email}</p>
            </div>
            {twin.status === "active" && (
              <Link
                to={`/twins/${twin.employeeId}/query`}
                className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-700"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" /></svg>
                Query Twin
              </Link>
            )}
          </div>

          <dl className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
            {([
              { label: "Role", value: twin.role },
              { label: "Department", value: twin.department },
              { label: "Offboard Date", value: twin.offboardDate },
              { label: "Chunks Indexed", value: twin.chunkCount.toLocaleString() },
            ] as const).map((item) => (
              <div key={item.label} className="rounded-xl bg-slate-50 px-4 py-3">
                <dt className="text-xs font-medium text-slate-500">{item.label}</dt>
                <dd className="mt-1 text-sm font-semibold text-slate-900">{item.value}</dd>
              </div>
            ))}
          </dl>
        </div>

        {/* Access Control */}
        <div className="rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">Access Control</h2>
          <p className="mt-0.5 text-sm text-slate-500">Manage who can query this digital twin.</p>

          <form onSubmit={handleGrantAccess} className="mt-4 space-y-3">
            {/* Directory lookup search */}
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Search by email or employee ID</span>
              <div className="relative mt-1.5">
                <input
                  value={lookupQuery}
                  onChange={(e) => {
                    setLookupQuery(e.target.value);
                    debouncedLookup(e.target.value);
                  }}
                  className="block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 pr-10 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                  placeholder="jane.chen@example.com"
                />
                {lookupLoading && (
                  <div className="absolute inset-y-0 right-3 flex items-center">
                    <svg className="h-4 w-4 animate-spin text-slate-400" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  </div>
                )}
              </div>
            </label>

            {/* Lookup result card */}
            {lookupResult && (
              <div className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                <svg className="h-5 w-5 shrink-0 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div className="min-w-0 flex-1 text-sm">
                  <p className="font-medium text-slate-900">{lookupResult.name}</p>
                  <p className="text-slate-500">{lookupResult.email} · {lookupResult.employeeId}</p>
                </div>
                <button type="button" onClick={clearLookup} className="text-xs font-medium text-slate-500 hover:text-slate-700">Clear</button>
              </div>
            )}

            {/* Lookup error — fallback to manual */}
            {lookupError && (
              <p className="text-xs text-amber-600">{lookupError}</p>
            )}

            {/* Manual User ID — always visible so admin can type directly */}
            <div className="flex items-end gap-3">
              <label className="block flex-1">
                <span className="text-sm font-medium text-slate-700">User ID</span>
                <input
                  value={accessForm.userId}
                  onChange={(e) => setAccessForm((f) => ({ ...f, userId: e.target.value }))}
                  required
                  className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                  placeholder="user_456"
                />
              </label>
              <label className="block w-36">
                <span className="text-sm font-medium text-slate-700">Role</span>
                <select
                  value={accessForm.role}
                  onChange={(e) => setAccessForm((f) => ({ ...f, role: e.target.value as "admin" | "viewer" }))}
                  className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                >
                  <option value="viewer">Viewer</option>
                  <option value="admin">Admin</option>
                </select>
              </label>
              <button
                type="submit"
                disabled={grantAccess.isPending}
                className="rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-700 disabled:opacity-50"
              >
                {grantAccess.isPending ? "Granting…" : "Grant Access"}
              </button>
            </div>
          </form>

          {grantAccess.isError && (
            <p className="mt-2 text-sm text-red-600" role="alert">{(grantAccess.error as Error).message}</p>
          )}

          <div className="mt-5 overflow-hidden rounded-xl border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500">User ID</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500">Role</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-semibold text-slate-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {accessLoading && (
                  <tr><td colSpan={3} className="px-4 py-8 text-center text-sm text-slate-500">Loading access list…</td></tr>
                )}
                {!accessLoading && (!accessList || accessList.length === 0) && (
                  <tr><td colSpan={3} className="px-4 py-8 text-center text-sm text-slate-500">No users have access yet.</td></tr>
                )}
                {accessList?.map((record) => (
                  <tr key={record.userId} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 text-sm text-slate-900">{record.userId}</td>
                    <td className="px-4 py-3 text-sm text-slate-600 capitalize">{record.role}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => revokeAccess.mutate(record.userId)}
                        disabled={revokeAccess.isPending}
                        className="text-sm font-medium text-red-600 hover:text-red-700 disabled:opacity-50 transition-colors"
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Danger Zone */}
        <div className="rounded-2xl border border-red-200/60 bg-white p-6 shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">Danger Zone</h2>
          <p className="mt-0.5 text-sm text-slate-500">
            Permanently delete this digital twin and all associated data. This action cannot be undone.
          </p>

          {!showDeleteConfirm ? (
            <button
              type="button"
              onClick={() => setShowDeleteConfirm(true)}
              className="mt-4 rounded-xl border border-red-300 px-4 py-2.5 text-sm font-medium text-red-700 transition-colors hover:bg-red-50"
            >
              Delete Twin
            </button>
          ) : (
            <div className="mt-4 rounded-xl bg-red-50 p-4">
              <p className="text-sm text-red-800">
                Are you sure you want to delete <span className="font-semibold">{twin.name}</span>'s digital twin?
                This will remove all vectors, access records, and raw archives.
              </p>
              <div className="mt-3 flex gap-3">
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleteTwin.isPending}
                  className="rounded-xl bg-red-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-red-700 disabled:opacity-50"
                >
                  {deleteTwin.isPending ? "Deleting…" : "Yes, Delete"}
                </button>
                <button
                  type="button"
                  onClick={() => setShowDeleteConfirm(false)}
                  className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
                >
                  Cancel
                </button>
              </div>
              {deleteTwin.isError && (
                <p className="mt-2 text-sm text-red-600" role="alert">{(deleteTwin.error as Error).message}</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
