# Implementation Plan: M365 Email Integration

## Overview

Add Microsoft 365 email retrieval to KnowledgeKeeper by creating a new `m365_email_fetcher` Lambda, updating the admin Lambda to dispatch to it, extending the Twin data model and frontend to support the `"microsoft"` provider, and adding the Lambda + IAM resources to the CDK ingestion stack. The downstream ingestion pipeline is provider-agnostic and requires no changes.

## Tasks

- [ ] 1. Update shared models and admin logic for Microsoft provider
  - [x] 1.1 Extend Twin provider Literal in `lambdas/shared/models.py`
    - Add `"microsoft"` to the `provider` field Literal type: `Literal["google", "upload", "microsoft"]`
    - _Requirements: 6.1_

  - [x] 1.2 Add provider validation and M365 dispatch to `lambdas/query/admin/logic.py`
    - Add a `VALID_PROVIDERS` set: `{"google", "upload", "microsoft"}`
    - In `create_twin()`, validate `provider` against `VALID_PROVIDERS`; return HTTP 400 with `VALIDATION_ERROR` and a message listing valid providers if invalid
    - Add `elif provider == "microsoft"` branch that reads `M365_EMAIL_FETCHER_FN_NAME` from env and invokes it async with `{"employeeId": employeeId, "email": email}`
    - Log failure if M365 fetcher invocation fails; leave Twin in `ingesting` status
    - _Requirements: 1.1, 1.2, 1.4, 6.2, 6.3_

  - [ ]* 1.3 Write property test for valid provider acceptance (Property 1)
    - **Property 1: Valid provider acceptance**
    - **Validates: Requirements 1.1, 6.1**

  - [ ]* 1.4 Write property test for Microsoft provider dispatch (Property 2)
    - **Property 2: Microsoft provider dispatches to M365 fetcher**
    - **Validates: Requirements 1.2, 6.2**

  - [ ]* 1.5 Write property test for invalid provider rejection (Property 3)
    - **Property 3: Invalid provider rejection**
    - **Validates: Requirements 6.3**

  - [ ]* 1.6 Write unit tests for admin logic M365 dispatch in `lambdas/query/admin/tests/test_logic.py`
    - Test `create_twin` with `provider: "microsoft"` invokes M365 fetcher
    - Test `create_twin` with invalid provider returns 400 with `VALIDATION_ERROR`
    - Test M365 fetcher invocation failure is logged and Twin stays in `ingesting`
    - _Requirements: 1.1, 1.2, 1.4, 6.2, 6.3_

- [x] 2. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Create M365 Email Fetcher Lambda core logic
  - [x] 3.1 Scaffold `lambdas/ingestion/m365_email_fetcher/` directory
    - Create `__init__.py`, `handler.py`, `logic.py`, `requirements.txt`, `tests/__init__.py`, `tests/test_logic.py`
    - `requirements.txt` should contain: `msal`, `requests`, `boto3`
    - _Requirements: 5.1_

  - [x] 3.2 Implement `get_m365_credentials()` in `logic.py`
    - Retrieve `tenant_id`, `client_id`, `client_secret` from Secrets Manager at `kk/{env}/m365-credentials`
    - Return an MSAL `ConfidentialClientApplication` configured with the credentials
    - _Requirements: 2.1, 2.2_

  - [x] 3.3 Implement `acquire_token()` in `logic.py`
    - Use MSAL `acquire_token_for_client()` with scope `https://graph.microsoft.com/.default`
    - Handle token refresh automatically via MSAL (covers token expiry mid-fetch)
    - _Requirements: 2.2, 2.4_

  - [x] 3.4 Implement `list_mail_folders()` in `logic.py`
    - Call `GET /users/{email}/mailFolders` via `requests` with the access token
    - Paginate using `@odata.nextLink`
    - Exclude folders with `displayName` equal to `"Deleted Items"` or `"Junk Email"`
    - Handle HTTP 429 with `Retry-After` header, up to 5 retries
    - Handle HTTP 401/403 by raising an auth error
    - _Requirements: 3.1, 3.2, 3.5, 3.6_

  - [ ]* 3.5 Write property test for folder exclusion filter (Property 4)
    - **Property 4: Folder exclusion filter**
    - **Validates: Requirements 3.2**

  - [x] 3.6 Implement `fetch_folder_messages()` in `logic.py`
    - Call `GET /users/{email}/mailFolders/{folderId}/messages` with `$select` for required fields and `$top=100`
    - Paginate using `@odata.nextLink`
    - Handle HTTP 429 with `Retry-After` header, up to 5 retries
    - _Requirements: 3.3, 3.4, 3.5_

  - [ ]* 3.7 Write property test for pagination completeness (Property 5)
    - **Property 5: Pagination collects all messages**
    - **Validates: Requirements 3.3**

  - [x] 3.8 Implement `graph_message_to_rfc2822()` in `logic.py`
    - Map Graph API JSON fields to RFC 2822 headers per the design field mapping table
    - For HTML body content type, produce multipart/alternative with text/html and text/plain parts
    - For text body content type, produce text/plain
    - Skip and log messages that fail conversion
    - _Requirements: 4.4, 4.5, 4.6_

  - [ ]* 3.9 Write property test for RFC 2822 field mapping round trip (Property 7)
    - **Property 7: Graph API message to RFC 2822 field mapping round trip**
    - **Validates: Requirements 4.4, 4.5**

  - [x] 3.10 Implement `messages_to_mbox()` in `logic.py`
    - Package a list of RFC 2822 byte strings into a single .mbox file using Python `mailbox` module
    - Follow the same pattern as the existing `email_fetcher/logic.py::_messages_to_mbox()`
    - _Requirements: 4.1_

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Implement M365 fetcher orchestration and handler
  - [x] 5.1 Implement `fetch_and_upload_emails()` orchestrator in `logic.py`
    - Enumerate folders → fetch messages per folder → batch into groups of 100 → convert to RFC 2822 → package as .mbox → upload to S3 at `{employeeId}/batch_{batchNumber:04d}.mbox`
    - Retry S3 uploads up to 3 times with exponential backoff (1s, 2s, 4s)
    - Write `manifest.json` with totalCount, batchCount, dateRange, folderBreakdown, fetchTimestamp
    - _Requirements: 4.1, 4.2, 4.3, 7.5_

  - [ ]* 5.2 Write property test for batch upload correctness (Property 6)
    - **Property 6: Batch upload correctness**
    - **Validates: Requirements 4.1, 4.2**

  - [ ]* 5.3 Write property test for manifest correctness (Property 8)
    - **Property 8: Manifest reflects actual upload state**
    - **Validates: Requirements 4.3**

  - [x] 5.4 Implement `handler.py` for the M365 Email Fetcher Lambda
    - Parse event `{"employeeId": "...", "email": "..."}`
    - Set Twin status to `ingesting` via DynamoDB
    - Call `get_m365_credentials()` then `fetch_and_upload_emails()`
    - On success, log employee ID, total count, batch count at INFO
    - On failure, update Twin status to `error`; if that also fails, log secondary failure at ERROR and re-raise original
    - Environment variables: `RAW_ARCHIVES_BUCKET`, `M365_CREDS_SECRET`, `TWINS_TABLE_NAME`
    - _Requirements: 2.3, 7.1, 7.2, 7.3, 7.4_

  - [ ]* 5.5 Write unit tests for M365 fetcher logic in `lambdas/ingestion/m365_email_fetcher/tests/test_logic.py`
    - Test happy path: credentials retrieval, folder enumeration, message fetch, conversion, upload
    - Test zero messages scenario (manifest only)
    - Test individual message conversion failure (skip and continue)
    - Test HTTP 429 rate limit retry
    - Test HTTP 401/403 auth error handling
    - Test S3 upload retry with exponential backoff
    - Test double failure (primary error + status update failure)
    - Test Secrets Manager failure sets Twin status to error
    - _Requirements: 2.1, 2.3, 3.5, 3.6, 4.6, 7.1, 7.4, 7.5_

- [ ] 6. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Add CDK infrastructure for M365 Email Fetcher
  - [x] 7.1 Add M365 Email Fetcher Lambda and IAM role to `infrastructure/stacks/ingestion_stack.py`
    - Lambda function: `kk-{env}-ingestion-m365-email-fetcher`, Python 3.12, 15-min timeout, 1024 MB, shared layer
    - Dedicated IAM role with least-privilege: `s3:PutObject` on raw-archives bucket, `secretsmanager:GetSecretValue` scoped to `kk/{env}/m365-credentials*`, `dynamodb:UpdateItem` on Twins table, KMS encrypt/decrypt permissions
    - Add `M365_EMAIL_FETCHER_FN_NAME` environment variable to the admin Lambda
    - Add `lambda:InvokeFunction` permission on admin Lambda role for the M365 fetcher ARN
    - Export `M365EmailFetcherFnArn` as stack output
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 7.2 Write CDK assertion tests for M365 fetcher infrastructure
    - Assert Lambda function name, runtime, timeout, memory
    - Assert IAM role has correct policy statements
    - Assert stack output exists for M365EmailFetcherFnArn
    - Assert admin Lambda has M365_EMAIL_FETCHER_FN_NAME env var
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [-] 8. Update frontend for Microsoft 365 provider
  - [x] 8.1 Add `"microsoft"` to `CreateTwinPayload.provider` type in `frontend/src/api/twins.ts`
    - Update the union type: `"google" | "upload" | "microsoft"`
    - _Requirements: 6.1_

  - [x] 8.2 Add Microsoft 365 option to provider dropdown in `frontend/src/pages/AdminDashboard.tsx`
    - Add `<option value="microsoft">Microsoft 365</option>` between Google Workspace and File Upload
    - Dropdown order: Google Workspace, Microsoft 365, File Upload (.mbox)
    - _Requirements: 1.3, 6.4_

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use `hypothesis` with `@settings(max_examples=100)`
- Unit tests follow existing patterns: `pytest` + `unittest.mock` + `moto`
- The downstream ingestion pipeline (trigger → parser → cleaner → embedder) requires no changes
