import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  getDirectoryConfig,
  saveDirectoryConfig,
  testDirectoryConnection,
  type DirectoryConfig,
} from "../api/twins";

type ProviderType = "microsoft" | "google";

interface MicrosoftCreds {
  tenant_id: string;
  client_id: string;
  client_secret: string;
}

interface GoogleCreds {
  service_account_key: string;
  delegated_admin: string;
}

const emptyMicrosoft: MicrosoftCreds = { tenant_id: "", client_id: "", client_secret: "" };
const emptyGoogle: GoogleCreds = { service_account_key: "", delegated_admin: "" };

export default function SettingsPage() {
  const [config, setConfig] = useState<DirectoryConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [provider, setProvider] = useState<ProviderType | null>(null);
  const [microsoftCreds, setMicrosoftCreds] = useState<MicrosoftCreds>({ ...emptyMicrosoft });
  const [googleCreds, setGoogleCreds] = useState<GoogleCreds>({ ...emptyGoogle });

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ passed: boolean; message: string } | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<{ ok: boolean; message: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDirectoryConfig()
      .then((data) => {
        if (cancelled) return;
        setConfig(data);
        if (data.provider) setProvider(data.provider);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "Failed to load config");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  function buildCredentials(): Record<string, string> {
    if (provider === "microsoft") {
      return { ...microsoftCreds };
    }
    const creds: Record<string, string> = { service_account_key: googleCreds.service_account_key };
    if (googleCreds.delegated_admin.trim()) {
      creds.delegated_admin = googleCreds.delegated_admin.trim();
    }
    return creds;
  }

  async function handleTest() {
    if (!provider) return;
    setTesting(true);
    setTestResult(null);
    setSaveResult(null);
    try {
      const result = await testDirectoryConnection({ provider, credentials: buildCredentials() });
      setTestResult({
        passed: result.test_passed,
        message: result.test_passed ? "Connection successful" : (result.message ?? "Connection failed"),
      });
    } catch (err) {
      setTestResult({ passed: false, message: err instanceof Error ? err.message : "Test failed" });
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    if (!provider) return;
    setSaving(true);
    setSaveResult(null);
    setTestResult(null);
    try {
      const updated = await saveDirectoryConfig({ provider, credentials: buildCredentials() });
      setConfig(updated);
      setSaveResult({ ok: true, message: "Configuration saved successfully" });
      // Clear credential fields after successful save (Req 8.3)
      setMicrosoftCreds({ ...emptyMicrosoft });
      setGoogleCreds({ ...emptyGoogle });
    } catch (err) {
      setSaveResult({ ok: false, message: err instanceof Error ? err.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  function handleProviderChange(p: ProviderType) {
    setProvider(p);
    setTestResult(null);
    setSaveResult(null);
  }

  const busy = testing || saving;
  const noProvider = !provider;

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <svg className="h-5 w-5 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading settings…
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-slate-200/60 bg-white">
        <div className="px-8 py-5">
          <nav className="flex items-center gap-1.5 text-sm text-slate-500">
            <Link to="/" className="hover:text-brand-600 transition-colors">Dashboard</Link>
            <svg className="h-4 w-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            <span className="font-medium text-slate-900">Settings</span>
          </nav>
          <h1 className="mt-1.5 text-xl font-bold text-slate-900">Directory Provider Settings</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Configure the directory provider used for employee lookups
          </p>
        </div>
      </header>

      <div className="px-8 py-6">
        <div className="mx-auto max-w-2xl space-y-6">
          {/* Load error */}
          {loadError && (
            <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
              {loadError}
            </div>
          )}

          {/* Current status */}
          {config && (
            <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-slate-900">Current Configuration</h2>
              <div className="mt-3 flex items-center gap-4 text-sm">
                <span className="text-slate-500">Provider:</span>
                <span className="font-medium text-slate-900">
                  {config.provider === "microsoft" && "Microsoft Entra ID"}
                  {config.provider === "google" && "Google Workspace"}
                  {!config.provider && "Not configured"}
                </span>
              </div>
              <div className="mt-1.5 flex items-center gap-4 text-sm">
                <span className="text-slate-500">Credentials:</span>
                {config.credentials_configured ? (
                  <span className="inline-flex items-center gap-1.5 text-emerald-700">
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Configured
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-amber-700">
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                    </svg>
                    Not configured
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Provider selector */}
          <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-900">Provider</h2>
            <p className="mt-0.5 text-xs text-slate-500">Select the directory provider for employee lookups</p>

            <fieldset className="mt-4">
              <legend className="sr-only">Directory provider</legend>
              <div className="flex gap-4">
                {([
                  { value: "microsoft" as const, label: "Microsoft Entra ID" },
                  { value: "google" as const, label: "Google Workspace" },
                ]).map((opt) => (
                  <label
                    key={opt.value}
                    className={`flex flex-1 cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 text-sm transition-colors ${
                      provider === opt.value
                        ? "border-brand-500 bg-brand-50 text-brand-700"
                        : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                    }`}
                  >
                    <input
                      type="radio"
                      name="provider"
                      value={opt.value}
                      checked={provider === opt.value}
                      onChange={() => handleProviderChange(opt.value)}
                      className="h-4 w-4 border-slate-300 text-brand-600 focus:ring-brand-500"
                    />
                    <span className="font-medium">{opt.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>

          {/* Credential fields */}
          {provider && (
            <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-slate-900">Credentials</h2>
              <p className="mt-0.5 text-xs text-slate-500">
                {provider === "microsoft"
                  ? "Enter your Microsoft Entra ID app registration credentials"
                  : "Paste your Google Workspace service account JSON key"}
              </p>

              <div className="mt-4 space-y-4">
                {provider === "microsoft" && (
                  <>
                    <label className="block">
                      <span className="text-sm font-medium text-slate-700">Tenant ID</span>
                      <input
                        type="text"
                        value={microsoftCreds.tenant_id}
                        onChange={(e) => setMicrosoftCreds((c) => ({ ...c, tenant_id: e.target.value }))}
                        placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                        className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                      />
                    </label>
                    <label className="block">
                      <span className="text-sm font-medium text-slate-700">Client ID</span>
                      <input
                        type="text"
                        value={microsoftCreds.client_id}
                        onChange={(e) => setMicrosoftCreds((c) => ({ ...c, client_id: e.target.value }))}
                        placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                        className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                      />
                    </label>
                    <label className="block">
                      <span className="text-sm font-medium text-slate-700">Client Secret</span>
                      <input
                        type="password"
                        value={microsoftCreds.client_secret}
                        onChange={(e) => setMicrosoftCreds((c) => ({ ...c, client_secret: e.target.value }))}
                        placeholder="••••••••"
                        autoComplete="off"
                        className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                      />
                    </label>
                  </>
                )}

                {provider === "google" && (
                  <>
                    <label className="block">
                      <span className="text-sm font-medium text-slate-700">Service Account Key (JSON)</span>
                      <textarea
                        value={googleCreds.service_account_key}
                        onChange={(e) => setGoogleCreds((c) => ({ ...c, service_account_key: e.target.value }))}
                        placeholder='{"type": "service_account", ...}'
                        rows={6}
                        autoComplete="off"
                        className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 font-mono text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                        style={{ WebkitTextSecurity: "disc" } as React.CSSProperties}
                      />
                    </label>
                    <label className="block">
                      <span className="text-sm font-medium text-slate-700">
                        Delegated Admin Email <span className="font-normal text-slate-400">(optional)</span>
                      </span>
                      <input
                        type="email"
                        value={googleCreds.delegated_admin}
                        onChange={(e) => setGoogleCreds((c) => ({ ...c, delegated_admin: e.target.value }))}
                        placeholder="admin@company.com"
                        className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm transition-colors focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none"
                      />
                    </label>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Alerts */}
          {testResult && (
            <div
              className={`rounded-xl px-4 py-3 text-sm ${
                testResult.passed
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-red-50 text-red-700"
              }`}
              role="status"
            >
              {testResult.passed && (
                <span className="mr-1.5 inline-flex items-center">
                  <svg className="mr-1 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                </span>
              )}
              {testResult.message}
            </div>
          )}

          {saveResult && (
            <div
              className={`rounded-xl px-4 py-3 text-sm ${
                saveResult.ok
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-red-50 text-red-700"
              }`}
              role="status"
            >
              {saveResult.message}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={handleTest}
              disabled={noProvider || busy}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-300 px-5 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {testing && (
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              {testing ? "Testing…" : "Test Connection"}
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={noProvider || busy}
              className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving && (
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
