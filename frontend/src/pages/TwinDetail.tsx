import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useTwin, useDeleteTwin, useAccess, useGrantAccess, useRevokeAccess } from "../hooks/useTwins";
import TwinStatusBadge from "../components/TwinStatusBadge";
import type { GrantAccessPayload } from "../api/twins";

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

  function handleGrantAccess(e: React.FormEvent) {
    e.preventDefault();
    if (!accessForm.userId.trim()) return;
    grantAccess.mutate(accessForm, {
      onSuccess: () => setAccessForm({ userId: "", role: "viewer" }),
    });
  }

  function handleDelete() {
    deleteTwin.mutate(employeeId!, {
      onSuccess: () => navigate("/"),
    });
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-sm text-gray-500">Loading twin details…</p>
      </div>
    );
  }

  if (error || !twin) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-red-600">{(error as Error)?.message ?? "Twin not found"}</p>
          <Link to="/" className="mt-2 inline-block text-sm text-indigo-600 hover:text-indigo-800">
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-4xl px-4 py-8">
        {/* Breadcrumb */}
        <nav className="mb-6 text-sm text-gray-500">
          <Link to="/" className="hover:text-indigo-600">Dashboard</Link>
          <span className="mx-2">/</span>
          <span className="text-gray-900">{twin.name}</span>
        </nav>

        {/* Twin Metadata */}
        <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">{twin.name}</h1>
              <p className="mt-1 text-sm text-gray-500">{twin.email}</p>
            </div>
            <TwinStatusBadge status={twin.status} />
          </div>

          <dl className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <dt className="text-xs font-medium uppercase text-gray-500">Role</dt>
              <dd className="mt-1 text-sm text-gray-900">{twin.role}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-gray-500">Department</dt>
              <dd className="mt-1 text-sm text-gray-900">{twin.department}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-gray-500">Offboard Date</dt>
              <dd className="mt-1 text-sm text-gray-900">{twin.offboardDate}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase text-gray-500">Chunks Indexed</dt>
              <dd className="mt-1 text-sm text-gray-900">{twin.chunkCount.toLocaleString()}</dd>
            </div>
          </dl>

          {twin.status === "active" && (
            <div className="mt-6">
              <Link
                to={`/twins/${twin.employeeId}/query`}
                className="inline-flex items-center rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
              >
                Query this Twin
              </Link>
            </div>
          )}
        </div>

        {/* Access Control */}
        <div className="mt-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900">Access Control</h2>
          <p className="mt-1 text-sm text-gray-500">Manage who can query this digital twin.</p>

          {/* Grant Access Form */}
          <form onSubmit={handleGrantAccess} className="mt-4 flex items-end gap-3">
            <label className="block flex-1">
              <span className="text-sm font-medium text-gray-700">User ID</span>
              <input
                value={accessForm.userId}
                onChange={(e) => setAccessForm((f) => ({ ...f, userId: e.target.value }))}
                required
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                placeholder="user_456"
              />
            </label>
            <label className="block w-36">
              <span className="text-sm font-medium text-gray-700">Role</span>
              <select
                value={accessForm.role}
                onChange={(e) => setAccessForm((f) => ({ ...f, role: e.target.value as "admin" | "viewer" }))}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
              >
                <option value="viewer">Viewer</option>
                <option value="admin">Admin</option>
              </select>
            </label>
            <button
              type="submit"
              disabled={grantAccess.isPending}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {grantAccess.isPending ? "Granting…" : "Grant Access"}
            </button>
          </form>

          {grantAccess.isError && (
            <p className="mt-2 text-sm text-red-600" role="alert">{(grantAccess.error as Error).message}</p>
          )}

          {/* Access List Table */}
          <div className="mt-4 overflow-hidden rounded-md border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">User ID</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Role</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {accessLoading && (
                  <tr>
                    <td colSpan={3} className="px-4 py-6 text-center text-sm text-gray-500">Loading access list…</td>
                  </tr>
                )}
                {!accessLoading && (!accessList || accessList.length === 0) && (
                  <tr>
                    <td colSpan={3} className="px-4 py-6 text-center text-sm text-gray-500">No users have access yet.</td>
                  </tr>
                )}
                {accessList?.map((record) => (
                  <tr key={record.userId}>
                    <td className="px-4 py-3 text-sm text-gray-900">{record.userId}</td>
                    <td className="px-4 py-3 text-sm text-gray-700 capitalize">{record.role}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => revokeAccess.mutate(record.userId)}
                        disabled={revokeAccess.isPending}
                        className="text-sm font-medium text-red-600 hover:text-red-800 disabled:opacity-50"
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

        {/* Delete Twin */}
        <div className="mt-8 rounded-lg border border-red-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900">Danger Zone</h2>
          <p className="mt-1 text-sm text-gray-500">
            Permanently delete this digital twin and all associated data. This action cannot be undone.
          </p>

          {!showDeleteConfirm ? (
            <button
              type="button"
              onClick={() => setShowDeleteConfirm(true)}
              className="mt-4 rounded-md border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
            >
              Delete Twin
            </button>
          ) : (
            <div className="mt-4 rounded-md bg-red-50 p-4">
              <p className="text-sm text-red-800">
                Are you sure you want to delete <span className="font-semibold">{twin.name}</span>'s digital twin?
                This will remove all vectors, access records, and raw archives.
              </p>
              <div className="mt-3 flex gap-3">
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleteTwin.isPending}
                  className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {deleteTwin.isPending ? "Deleting…" : "Yes, Delete"}
                </button>
                <button
                  type="button"
                  onClick={() => setShowDeleteConfirm(false)}
                  className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
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
