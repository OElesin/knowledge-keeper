# Implementation Plan: LDAP Directory Lookup

## Overview

Add LDAP as a third directory provider to KnowledgeKeeper. Extends the directory lookup Lambda with `_lookup_ldap()` and `_normalize_ldap()` using the `ldap3` library, extends the admin Lambda to validate/save/test LDAP credentials with defaults for port and search filter template, updates the frontend Settings page with an LDAP provider option and credential fields, and adds `ldap3` to Lambda requirements.txt files.

## Tasks

- [ ] 1. Add LDAP lookup logic to directory lookup Lambda
  - [x] 1.1 Implement `_normalize_ldap` in `lambdas/query/directory_lookup/logic.py`
    - Map LDAP attributes to Employee_Record: `uid` → `employeeId`, `cn` → `name`, `mail` → `email`, `title` → `role`, `departmentNumber` → `department`
    - Missing, `None`, or empty attributes map to `""` (empty string)
    - All five output fields must be of type `str`
    - _Requirements: 1.4, 1.5_

  - [x] 1.2 Implement `_lookup_ldap` in `lambdas/query/directory_lookup/logic.py`
    - Retrieve LDAP credentials from Secrets Manager (server_url, port, bind_dn, bind_password, search_base_dn, search_filter_template)
    - Validate that `search_filter_template` contains `{query}` — if not, return 500 `PROVIDER_NOT_CONFIGURED`
    - Substitute `{query}` in the filter template with the lookup query value
    - Connect to LDAP server using `ldap3.Server` and `ldap3.Connection` with simple bind and 10-second `receive_timeout`
    - Search under `search_base_dn` using the substituted filter
    - Return first matching entry normalized via `_normalize_ldap`, or 404 `EMPLOYEE_NOT_FOUND` if no results
    - Handle `LDAPBindError` → 502 `DIRECTORY_AUTH_ERROR`, `LDAPSocketOpenError` → 502 `DIRECTORY_UNAVAILABLE`, timeout → 504 `DIRECTORY_TIMEOUT`
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4_

  - [x] 1.3 Extend `lookup_employee` provider dispatch in `lambdas/query/directory_lookup/logic.py`
    - Add `"ldap"` to the valid provider check
    - Route to `_lookup_ldap` when provider is `"ldap"`
    - _Requirements: 5.2, 5.3_

  - [ ]* 1.4 Write property test: LDAP field mapping with null handling
    - **Property 1: LDAP field mapping with null handling**
    - File: `lambdas/query/directory_lookup/tests/test_ldap_property.py`
    - Generate dicts with optional None/missing/empty values for `uid`, `cn`, `mail`, `title`, `departmentNumber`
    - Assert all five output fields are `str`, nulls become `""`, present values are preserved
    - **Validates: Requirements 1.4, 1.5**

  - [ ]* 1.5 Write property test: filter template substitution
    - **Property 4: Filter template substitution**
    - File: `lambdas/query/directory_lookup/tests/test_ldap_property.py`
    - Generate random filter templates containing `{query}` and random non-empty query strings
    - Assert the resulting filter has `{query}` replaced and does not contain the literal `{query}`
    - **Validates: Requirements 1.3**

  - [ ]* 1.6 Write property test: invalid filter template rejection
    - **Property 5: Invalid filter template rejection**
    - File: `lambdas/query/directory_lookup/tests/test_ldap_property.py`
    - Generate random strings that do not contain `{query}`
    - Mock Secrets Manager to return credentials with the invalid template
    - Assert `_lookup_ldap` returns error with `PROVIDER_NOT_CONFIGURED`
    - **Validates: Requirements 2.4**

  - [ ]* 1.7 Write property test: LDAP error classification
    - **Property 6: LDAP error classification**
    - File: `lambdas/query/directory_lookup/tests/test_ldap_property.py`
    - Generate LDAP exception types (LDAPBindError, LDAPSocketOpenError, timeout)
    - Assert correct error code mapping: bind failure → `DIRECTORY_AUTH_ERROR`, socket error → `DIRECTORY_UNAVAILABLE`, timeout → `DIRECTORY_TIMEOUT`
    - **Validates: Requirements 2.1, 2.2, 1.8**

  - [ ]* 1.8 Write unit tests for LDAP lookup logic
    - File: `lambdas/query/directory_lookup/tests/test_logic.py` (extend existing)
    - `test_lookup_ldap_happy_path_email_query` — valid email query returns Employee_Record
    - `test_lookup_ldap_no_results_returns_404` — empty search result → EMPLOYEE_NOT_FOUND
    - `test_lookup_ldap_bind_failure_returns_502` — invalid credentials → DIRECTORY_AUTH_ERROR
    - `test_lookup_ldap_server_unreachable_returns_502` — connection refused → DIRECTORY_UNAVAILABLE
    - `test_lookup_ldap_timeout_returns_504` — timeout → DIRECTORY_TIMEOUT
    - `test_lookup_ldap_credentials_unavailable` — Secrets Manager failure → CREDENTIALS_UNAVAILABLE
    - `test_lookup_ldap_invalid_filter_template` — filter without `{query}` → PROVIDER_NOT_CONFIGURED
    - `test_lookup_ldap_missing_attributes_returns_empty_strings` — partial LDAP entry → empty strings
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.1, 2.2, 2.3, 2.4_

- [x] 2. Checkpoint — Ensure all directory lookup Lambda tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Add LDAP credential validation, defaults, and connection test to admin Lambda
  - [x] 3.1 Extend `validate_credential_payload` in `lambdas/query/admin/logic.py` for LDAP
    - Add `"ldap"` to `VALID_DIRECTORY_PROVIDERS`
    - For `provider == "ldap"`: require non-empty `server_url`, `bind_dn`, `bind_password`, `search_base_dn`
    - Return list of missing required field names (whitespace-only counts as empty)
    - _Requirements: 3.1, 3.4, 5.1_

  - [x] 3.2 Extend `save_directory_config` in `lambdas/query/admin/logic.py` for LDAP defaults
    - Before storing LDAP credentials, apply defaults: `port` → `"389"` if missing/empty, `search_filter_template` → `"(|(mail={query})(uid={query}))"` if missing/empty
    - Ensure the stored credential payload always contains all six fields
    - Update the validation error message to include `ldap` in the valid providers list
    - _Requirements: 3.2, 3.3, 3.5_

  - [x] 3.3 Implement `_test_ldap_connection` in `lambdas/query/admin/logic.py`
    - Connect to LDAP server and perform simple bind using `ldap3` with 10-second timeout
    - Return `{ test_passed: true, message: "Connection successful" }` on success
    - Return `{ test_passed: false, message: "..." }` on bind failure, unreachable server, or timeout
    - Never persist credentials
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 3.4 Wire `_test_ldap_connection` into `test_directory_connection` in `lambdas/query/admin/logic.py`
    - Add `elif provider == "ldap"` branch to route to `_test_ldap_connection`
    - _Requirements: 4.1, 5.1_

  - [ ]* 3.5 Write property test: LDAP credential validation rejects invalid payloads
    - **Property 2: LDAP credential validation rejects invalid payloads**
    - File: `lambdas/query/admin/tests/test_ldap_validation_property.py`
    - Generate credential dicts with at least one required LDAP field missing/empty
    - Assert `validate_credential_payload("ldap", creds)` returns the missing fields
    - **Validates: Requirements 3.1, 3.4**

  - [ ]* 3.6 Write property test: LDAP defaults application on save
    - **Property 3: LDAP defaults application on save**
    - File: `lambdas/query/admin/tests/test_ldap_validation_property.py`
    - Generate valid LDAP credential payloads with missing/empty `port` and/or `search_filter_template`
    - Mock SM and DDB, call `save_directory_config`
    - Assert the payload stored in SM contains `port` = `"389"` and `search_filter_template` = `"(|(mail={query})(uid={query}))"` for missing fields, and preserves provided values
    - **Validates: Requirements 3.2, 3.3, 3.5**

  - [ ]* 3.7 Write unit tests for admin LDAP logic
    - File: `lambdas/query/admin/tests/test_logic.py` (extend existing)
    - `test_validate_ldap_credentials_valid` — all required fields present → empty list
    - `test_validate_ldap_credentials_missing_fields` — missing required fields → list of missing
    - `test_save_ldap_config_stores_with_defaults` — save with missing optional fields → defaults in SM
    - `test_test_ldap_connection_success` — successful bind → test_passed true
    - `test_test_ldap_connection_bind_failure` — bind failure → test_passed false
    - `test_test_ldap_connection_timeout` — timeout → test_passed false with timeout message
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.5_

- [x] 4. Checkpoint — Ensure all admin Lambda tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Add `ldap3` dependency to Lambda requirements.txt files
  - [x] 5.1 Add `ldap3` to `lambdas/query/directory_lookup/requirements.txt`
    - _Requirements: 7.1_

  - [x] 5.2 Create `lambdas/query/admin/requirements.txt` with `ldap3` (or add to existing if present)
    - _Requirements: 7.2_

- [ ] 6. Update frontend types and Settings page for LDAP provider
  - [x] 6.1 Update `DirectoryConfig` type in `frontend/src/api/twins.ts`
    - Change provider union from `"microsoft" | "google" | null` to `"microsoft" | "google" | "ldap" | null`
    - _Requirements: 5.1, 6.1_

  - [x] 6.2 Add LDAP provider option and credential fields to `frontend/src/pages/SettingsPage.tsx`
    - Add `"ldap"` to `ProviderType` union
    - Add `LdapCreds` interface with `server_url`, `port`, `bind_dn`, `bind_password`, `search_base_dn`, `search_filter_template`
    - Add `emptyLdap` default with `port: "389"` and `search_filter_template: "(|(mail={query})(uid={query}))"`
    - Add "LDAP" as third radio option in provider selector
    - When LDAP selected, display fields: Server URL, Port (default "389"), Bind DN, Bind Password (masked), Search Base DN, Search Filter Template (default with `{query}` placeholder)
    - Add helper text below Search Filter Template: "Use `{query}` as a placeholder — it will be replaced with the lookup value at runtime."
    - Update `buildCredentials()` to handle LDAP provider
    - Update current config display to show "LDAP" when `config.provider === "ldap"`
    - Clear all LDAP fields after successful save
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 8.3_

  - [ ]* 6.3 Write property test: no LDAP credential values in API responses
    - **Property 7: No LDAP credential values in API responses**
    - File: `frontend/src/api/__tests__/ldapDirectoryConfigNoCredentials.property.test.ts`
    - Generate random LDAP credential values, build a `DirectoryConfig` response with provider `"ldap"`
    - Assert the serialized response contains none of the credential values
    - **Validates: Requirements 8.2**

- [x] 7. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend uses Python (pytest + hypothesis), frontend uses TypeScript (vitest + fast-check)
- No CDK infrastructure changes are required — existing IAM permissions, API Gateway routes, and environment variables are sufficient for LDAP
