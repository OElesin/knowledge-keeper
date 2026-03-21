import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useTwins, useCreateTwin } from "../hooks/useTwins";
import { useIngestionStatus } from "../hooks/useIngestionStatus";
import TwinStatusBadge from "../components/TwinStatusBadge";
import type { CreateTwinPayload, Twin } from "../api/twins";

const emptyForm: CreateTwinPayload = {
  employeeId: "",
  name: "",
  email: "",
  role: "",
  department: "",
  offboardDate: "",
  provider: "google",
};

export default function AdminDashboard() {
  const { data: twins, isLoading, error } = useTwins();
  const pollingQuery = useIngestionStatus();
  const createTwin = useCreateTwin();
  const [form, setForm] = useState<CreateTwinPayload>({ ...emptyForm });
  const [showForm, setShowForm] = useState(false);

  // Prefer polling data when available (has fresher status), fall back to initial query
  const displayTwins: Twin[] = pollingQuery.data ?? twins ?? [];

  function handleChange(e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    createTwin.mutate(form, {
      onSuccess: () => {
        setForm({ ...emptyForm });
        setShowForm(false);
      },
    });
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-6xl px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">KnowledgeKeeper</h1>
            <p className="mt-1 text-sm text-gray-500">Digital twin management &amp; offboarding</p>
          </div>
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            {showForm ? "Cancel" : "New Offboarding"}
          </button>
        </div>

        {/* Offboarding Form */}
        {showForm && (
          <form
            onSubmit={handleSubmit}
            className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm"
          >
            <h2 className="mb-4 text-lg font-semibold text-gray-900">Offboard Employee</h2>

            {createTwin.isError && (
              <div className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
                {(createTwin.error as Error).message}
              </div>
            )}
            {createTwin.isSuccess && (
              <div className="mb-4 rounded-md bg-green-50 p-3 text-sm text-green-700" role="status">
                Twin created successfully. Ingestion has started.
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <label className="block">
                <span className="text-sm font-medium text-gray-700">Employee ID</span>
                <input
                  name="employeeId"
                  value={form.employeeId}
                  onChange={handleChange}
                  required
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                  placeholder="emp_123"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700">Full Name</span>
                <input
                  name="name"
                  value={form.name}
                  onChange={handleChange}
                  required
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                  placeholder="Jane Doe"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700">Email</span>
                <input
                  name="email"
                  type="email"
                  value={form.email}
                  onChange={handleChange}
                  required
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                  placeholder="jane@company.com"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700">Role</span>
                <input
                  name="role"
                  value={form.role}
                  onChange={handleChange}
                  required
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                  placeholder="Senior Engineer"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700">Department</span>
                <input
                  name="department"
                  value={form.department}
                  onChange={handleChange}
                  required
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                  placeholder="Engineering"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700">Offboard Date</span>
                <input
                  name="offboardDate"
                  type="date"
                  value={form.offboardDate}
                  onChange={handleChange}
                  required
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700">Email Provider</span>
                <select
                  name="provider"
                  value={form.provider}
                  onChange={handleChange}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                >
                  <option value="google">Google Workspace</option>
                  <option value="microsoft">Microsoft 365</option>
                  <option value="upload">File Upload (.mbox)</option>
                </select>
              </label>
            </div>

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={createTwin.isPending}
                className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {createTwin.isPending ? "Creating…" : "Start Offboarding"}
              </button>
            </div>
          </form>
        )}

        {/* Twin List Table */}
        <div className="mt-8 overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Employee
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Status
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Offboard Date
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Chunks
                </th>
                <th scope="col" className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {isLoading && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-sm text-gray-500">
                    Loading twins…
                  </td>
                </tr>
              )}

              {error && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-sm text-red-600">
                    Failed to load twins: {(error as Error).message}
                  </td>
                </tr>
              )}

              {!isLoading && !error && displayTwins.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-sm text-gray-500">
                    No digital twins yet. Click "New Offboarding" to get started.
                  </td>
                </tr>
              )}

              {displayTwins.map((twin) => (
                <tr key={twin.employeeId} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div className="text-sm font-medium text-gray-900">{twin.name}</div>
                    <div className="text-xs text-gray-500">{twin.email}</div>
                  </td>
                  <td className="px-6 py-4">
                    <TwinStatusBadge status={twin.status} />
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-700">
                    {twin.offboardDate}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-700">
                    {twin.chunkCount.toLocaleString()}
                  </td>
                  <td className="px-6 py-4 text-right text-sm">
                    <Link
                      to={`/twins/${twin.employeeId}`}
                      className="font-medium text-indigo-600 hover:text-indigo-800"
                    >
                      View
                    </Link>
                    {twin.status === "active" && (
                      <Link
                        to={`/twins/${twin.employeeId}/query`}
                        className="ml-4 font-medium text-indigo-600 hover:text-indigo-800"
                      >
                        Query
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
