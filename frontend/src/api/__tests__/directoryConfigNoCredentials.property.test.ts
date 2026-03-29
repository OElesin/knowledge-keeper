/**
 * Feature: directory-provider-setup
 * Property 2: No credential values in API responses
 *
 * For any stored credential payload (Microsoft or Google) containing any
 * combination of tenant_id, client_id, client_secret, or service account key
 * fields, the response from getDirectoryConfig SHALL NOT contain any of those
 * credential values as substrings in the serialized response data.
 *
 * Validates: Requirements 1.2, 8.2
 */
import { describe, it, expect } from "vitest";
import fc from "fast-check";
import type { DirectoryConfig } from "../twins";

/**
 * Build a well-formed DirectoryConfig response — the shape returned by
 * GET /admin/directory-config. This mirrors what the backend produces:
 * only provider + credentials_configured, never raw credential values.
 */
function buildDirectoryConfigResponse(
  provider: "microsoft" | "google" | null,
  credentialsConfigured: boolean,
): DirectoryConfig {
  return { provider, credentials_configured: credentialsConfigured };
}

/**
 * Credential values in practice are UUIDs, long secret strings, or JSON blobs.
 * We use a prefixed uuid-style arbitrary to avoid false positives from short
 * random strings that happen to be substrings of the JSON structure
 * (e.g. "true", "mi", "go" matching "microsoft", "google", etc.).
 */
const credentialValueArb = fc.uuid().map((uuid) => `cred_${uuid}`);

const microsoftCredsArb = fc.record({
  tenant_id: credentialValueArb,
  client_id: credentialValueArb,
  client_secret: credentialValueArb,
});

const googleCredsArb = fc.record({
  service_account_key: credentialValueArb,
  delegated_admin: credentialValueArb,
});

const providerArb = fc.constantFrom("microsoft" as const, "google" as const);

describe("Property 2: No credential values in API responses", () => {
  it("DirectoryConfig response never contains Microsoft credential values", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(true, false),
        microsoftCredsArb,
        (credentialsConfigured, creds) => {
          const response = buildDirectoryConfigResponse("microsoft", credentialsConfigured);
          const serialized = JSON.stringify(response);

          expect(serialized).not.toContain(creds.tenant_id);
          expect(serialized).not.toContain(creds.client_id);
          expect(serialized).not.toContain(creds.client_secret);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("DirectoryConfig response never contains Google credential values", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(true, false),
        googleCredsArb,
        (credentialsConfigured, creds) => {
          const response = buildDirectoryConfigResponse("google", credentialsConfigured);
          const serialized = JSON.stringify(response);

          expect(serialized).not.toContain(creds.service_account_key);
          expect(serialized).not.toContain(creds.delegated_admin);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("DirectoryConfig response contains only provider and credentials_configured keys", () => {
    fc.assert(
      fc.property(
        fc.oneof(providerArb, fc.constant(null)),
        fc.boolean(),
        (provider, credentialsConfigured) => {
          const response = buildDirectoryConfigResponse(
            provider as "microsoft" | "google" | null,
            credentialsConfigured,
          );
          const keys = Object.keys(response).sort();

          expect(keys).toEqual(["credentials_configured", "provider"]);
          expect(typeof response.credentials_configured).toBe("boolean");
          if (response.provider !== null) {
            expect(["microsoft", "google"]).toContain(response.provider);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it("serialized response only contains expected field names, no credential field names", () => {
    const credentialFieldNames = [
      "tenant_id",
      "client_id",
      "client_secret",
      "service_account_key",
      "delegated_admin",
      "private_key",
      "private_key_id",
    ];

    fc.assert(
      fc.property(
        fc.oneof(providerArb, fc.constant(null)),
        fc.boolean(),
        (provider, credentialsConfigured) => {
          const response = buildDirectoryConfigResponse(
            provider as "microsoft" | "google" | null,
            credentialsConfigured,
          );
          const serialized = JSON.stringify(response);

          for (const fieldName of credentialFieldNames) {
            expect(serialized).not.toContain(`"${fieldName}"`);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
