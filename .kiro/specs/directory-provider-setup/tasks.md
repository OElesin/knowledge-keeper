# Implementation Plan: Directory Provider Setup

## Overview

Add self-service directory provider configuration to KnowledgeKeeper. Extends the admin Lambda with GET/PUT/POST endpoints for directory config, updates the directory lookup Lambda to read config from DynamoDB at runtime, adds CDK infrastructure for IAM and API Gateway routes, and builds a Settings page in the frontend.

## Tasks

- [ ] 1. Add credential validation and directory config logic to admin Lambda
  - [x] 1.1 Implement `validate_credential_payload` in `lambdas/query/admin/logic.py`
    - Accept `provider` (string) and `credentials` (dict)
    - For `microsoft`: require non-empty `tenant_id`, `client_id`, `client_secret`
    - For `google`: require non-empty `service_account_key` that is valid JSON
    - Return list of missing/invalid field names; empty list means valid
    - Return `VALIDATION_ERROR` for unknown provider types
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 3.5_

  - [x] 1.2 Implement `get_directory_config` in `lambdas/query/admin/logic.py`
    - Read `SETTINGS#directory` item from DynamoDB via injected `dynamo_module`
    - Check secret existence via `secrets_module.describe_secret()` (graceful degradation if call fails)
    - Return `{ provider, credentials_configured }` — never return credential values
    - Return `provider: null, credentials_configured: false` when no record exists
    - _Requirements: 1.1, 1.2, 1.3, 8.2_

  - [x] 1.3 Implement `save_directory_config` in `lambdas/query/admin/logic.py`
    - Validate provider and credentials using `validate_credential_payload`
    - Store credentials in Secrets Manager via `secrets_module.put_secret_value()` under `kk/{env}/directory-creds`
    - Save `SETTINGS#directory` record to DynamoDB with provider, secret_name, updated_at, updated_by
    - Write audit log entry with action `save_directory_config` and provider type
    - Never log credential values
    - _Requirements: 2.1, 2.6, 2.7, 2.8, 8.1_

  - [x] 1.4 Implement `test_directory_connection` in `lambdas/query/admin/logic.py`
    - Validate provider and credentials using `validate_credential_payload`
    - For `microsoft`: acquire OAuth2 token from `login.microsoftonline.com` with 10s timeout
    - For `google`: build service account credentials and call a lightweight directory API endpoint with 10s timeout
    - Return `{ test_passed: bool, message: str }` — never persist credentials
    - Return `test_passed: false` with timeout message if provider does not respond within 10 seconds
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 8.1_

  - [x] 1.5 Write property test: credential validation rejects invalid payloads
    - **Property 3: Credential validation rejects invalid payloads**
    - Generate random provider types and credential dicts with at least one required field missing/empty
    - Assert `validate_credential_payload` returns the missing fields
    - **Validates: Requirements 2.2, 2.3, 2.4, 3.5**

  - [x] 1.6 Write property test: invalid provider type rejected
    - **Property 4: Invalid provider type rejected**
    - Generate random strings excluding "microsoft" and "google"
    - Assert validation returns error with `VALIDATION_ERROR` code
    - **Validates: Requirements 2.5**

  - [ ]* 1.7 Write unit tests for admin directory config logic
    - `test_get_directory_config_returns_provider_and_status` — happy path
    - `test_get_directory_config_no_record_returns_null` — no settings record (Req 1.3)
    - `test_get_directory_config_never_returns_credentials` — security (Req 1.2, 8.2)
    - `test_save_directory_config_stores_to_sm_and_ddb` — happy path
    - `test_save_directory_config_invalid_provider_returns_400` — validation
    - `test_save_directory_config_missing_microsoft_fields_returns_400` — validation
    - `test_save_directory_config_missing_google_fields_returns_400` — validation
    - `test_save_directory_config_invalid_json_google_key_returns_400` — validation
    - `test_save_directory_config_writes_audit_log` — audit (Req 2.8)
    - `test_test_directory_connection_does_not_persist` — no side effects (Req 3.4)
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.8, 3.4, 8.1, 8.2_

- [ ] 2. Wire directory config routes into admin Lambda handler
  - [x] 2.1 Add `_SecretsHelper` class to `lambdas/query/admin/handler.py`
    - Follow existing `_S3Helper` and `_LambdaHelper` patterns with lazy boto3 client init
    - Wrap `describe_secret`, `get_secret_value`, `put_secret_value`, `create_secret`
    - _Requirements: 5.1, 5.2_

  - [x] 2.2 Add directory config routes to `_dispatch` in `lambdas/query/admin/handler.py`
    - `GET /admin/directory-config` → `logic.get_directory_config`
    - `PUT /admin/directory-config` → `logic.save_directory_config`
    - `POST /admin/directory-config/test` → `logic.test_directory_connection`
    - Pass `secrets_module=secrets_helper` and `dynamo_module` to logic functions
    - _Requirements: 1.1, 1.4, 2.1, 3.1, 5.4_

  - [x] 2.3 Write property test: save round-trip
    - **Property 5: Save round-trip**
    - Generate random valid provider + credentials, save, then GET
    - Assert provider matches and `credentials_configured` is `true`
    - **Validates: Requirements 2.1, 2.6**

  - [ ]* 2.4 Write property test: audit log written on successful save
    - **Property 7: Audit log written on successful save**
    - Generate random valid saves, assert audit table contains matching entry with provider type
    - **Validates: Requirements 2.8**

  - [ ]* 2.5 Write property test: connection test does not persist
    - **Property 8: Connection test does not persist**
    - Generate random payloads, snapshot DDB/SM state, call test endpoint, assert state unchanged
    - **Validates: Requirements 3.4**

- [x] 3. Checkpoint — Ensure all admin Lambda tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Update directory lookup Lambda for runtime config resolution
  - [x] 4.1 Implement `resolve_provider_config` in `lambdas/query/directory_lookup/logic.py`
    - Accept `dynamo_client`, `table_name`, `env_provider`, `env_secret_name`
    - Read `SETTINGS#directory` item from DynamoDB
    - If record exists, return `(provider, secret_name)` from DynamoDB record
    - If no record, fall back to `(env_provider, env_secret_name)` from env vars
    - If neither available, raise error with `PROVIDER_NOT_CONFIGURED` code
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 4.2 Update `lambdas/query/directory_lookup/handler.py` to call `resolve_provider_config`
    - Read `TWINS_TABLE_NAME` from env vars
    - Create DynamoDB client and call `resolve_provider_config` before each lookup
    - Use resolved provider and secret_name instead of raw env vars
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 4.3 Write property test: config resolution — DynamoDB overrides env vars
    - **Property 9: Config resolution — DynamoDB overrides env vars**
    - Generate random DDB records and env var values
    - Assert `resolve_provider_config` returns DDB values when present, env vars otherwise
    - **Validates: Requirements 4.1, 4.2, 4.3**

  - [ ]* 4.4 Write unit tests for directory lookup runtime config
    - `test_resolve_provider_config_uses_dynamodb_when_record_exists` — DDB override
    - `test_resolve_provider_config_falls_back_to_env_vars` — fallback
    - `test_resolve_provider_config_no_config_raises_error` — edge case (Req 4.4)
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 5. Update CDK infrastructure for IAM and API Gateway routes
  - [x] 5.1 Add Secrets Manager IAM permissions to admin Lambda role in `infrastructure/stacks/query_stack.py`
    - `secretsmanager:CreateSecret`, `secretsmanager:PutSecretValue`, `secretsmanager:GetSecretValue` scoped to `kk/{env}/directory-creds`
    - `secretsmanager:DescribeSecret` scoped to `kk/{env}/directory-creds`
    - _Requirements: 5.1, 5.2_

  - [x] 5.2 Add DynamoDB GetItem permission and `TWINS_TABLE_NAME` env var to directory lookup Lambda in `infrastructure/stacks/query_stack.py`
    - Grant `dynamodb:GetItem` on Twins table
    - Add KMS decrypt permission for DynamoDB CMK
    - Add `TWINS_TABLE_NAME` environment variable
    - _Requirements: 5.3_

  - [x] 5.3 Add API Gateway routes for directory config in `infrastructure/stacks/query_stack.py`
    - Add `/admin` resource, then `/admin/directory-config` sub-resource
    - Wire GET and PUT methods on `/admin/directory-config` to admin Lambda integration with API key required
    - Add `/admin/directory-config/test` sub-resource with POST method wired to admin Lambda integration with API key required
    - _Requirements: 5.4, 1.4_

  - [x] 5.4 Add `ENVIRONMENT` env var to admin Lambda in `infrastructure/stacks/query_stack.py`
    - The admin Lambda needs the environment name to construct the secret name `kk/{env}/directory-creds`
    - _Requirements: 2.1, 5.5_

- [x] 6. Checkpoint — Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Add directory config API functions to frontend
  - [x] 7.1 Add `DirectoryConfig`, `DirectoryTestResult` types and API functions to `frontend/src/api/twins.ts`
    - `getDirectoryConfig()` → GET `/admin/directory-config`
    - `saveDirectoryConfig(payload)` → PUT `/admin/directory-config`
    - `testDirectoryConnection(payload)` → POST `/admin/directory-config/test`
    - Follow existing `ApiResponse<T>` envelope pattern
    - _Requirements: 1.1, 2.1, 3.1_

- [ ] 8. Build Settings page UI
  - [x] 8.1 Create `frontend/src/pages/SettingsPage.tsx`
    - Fetch current config on mount via `getDirectoryConfig()`
    - Display current provider and credentials_configured status
    - Provider selector (radio group): "Microsoft Entra ID" / "Google Workspace"
    - Conditional credential fields: Microsoft shows `tenant_id`, `client_id`, `client_secret` (password masked); Google shows `service_account_key` textarea (password masked) and optional `delegated_admin` email
    - "Test Connection" button → calls `testDirectoryConnection`, shows success/error indicator
    - "Save" button → calls `saveDirectoryConfig`, shows success notification, clears credential fields on success
    - Disable both buttons while no provider selected, during test, or during save
    - Loading indicators on buttons during async operations
    - Inline error/success alerts for test results and save outcomes
    - Never store credentials in localStorage, sessionStorage, or cookies
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 8.3, 8.4_

  - [x] 8.2 Add `/settings` route to `frontend/src/App.tsx` and navigation link to `frontend/src/pages/AdminDashboard.tsx`
    - Add `<Route path="/settings" element={<SettingsPage />} />` to App.tsx
    - Add "Settings" navigation link in AdminDashboard header
    - _Requirements: 6.1_

  - [x] 8.3 Write property test: no credential values in API responses (frontend validation)
    - **Property 2: No credential values in API responses**
    - If client-side validation is added, generate random credential objects and verify no credential values appear in response data
    - **Validates: Requirements 1.2, 8.2**

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend uses Python (pytest + hypothesis), frontend uses TypeScript (vitest + fast-check)
