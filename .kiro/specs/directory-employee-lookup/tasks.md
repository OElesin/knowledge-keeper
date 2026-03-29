# Implementation Plan: Directory Employee Lookup

## Overview

Implement a read-only directory lookup feature that allows IT admins to search for employee information from Microsoft Entra ID or Google Workspace and auto-fill the offboarding form. The implementation adds a `directory_lookup` Lambda with dedicated IAM role, a `GET /directory/lookup` API Gateway endpoint, and a lookup UI component in the AdminDashboard.

## Tasks

- [ ] 1. Create the directory_lookup Lambda with core logic
  - [x] 1.1 Create `lambdas/query/directory_lookup/` directory structure with `__init__.py`, `handler.py`, `logic.py`, `requirements.txt`, and `tests/__init__.py`
    - `requirements.txt` includes: `msal`, `google-api-python-client`, `google-auth`, `requests`
    - _Requirements: 1.1, 5.1, 5.2, 7.6_

  - [x] 1.2 Implement `logic.py` with `lookup_employee()`, `_is_email()`, `_lookup_microsoft()`, `_lookup_google()`, `_normalize_microsoft()`, `_normalize_google()`, and the `SecretsClient` protocol
    - `lookup_employee(query, provider, secret_name, secrets_client)` dispatches to the correct provider
    - Validate query is non-empty/non-whitespace, return 400 `VALIDATION_ERROR` if invalid
    - Validate provider is `"microsoft"` or `"google"`, return 500 `PROVIDER_NOT_CONFIGURED` if invalid
    - `_is_email()` checks for `@` character
    - Microsoft: email queries call `GET /users/{email}`, ID queries call `GET /users?$filter=employeeId eq '{query}'` with `$select=id,displayName,mail,jobTitle,department`
    - Google: all queries call `users().get(userKey=query)`
    - Normalize responses to `Employee_Record` with 5 string fields, null/missing → `""`
    - Handle HTTP errors: 401/403 → 502 `DIRECTORY_AUTH_ERROR`, 429 → 429 `DIRECTORY_RATE_LIMITED`, 5xx → 502 `DIRECTORY_UNAVAILABLE`, 404 → 404 `EMPLOYEE_NOT_FOUND`
    - Handle Secrets Manager failure → 500 `CREDENTIALS_UNAVAILABLE`
    - Handle timeout → 504 `DIRECTORY_TIMEOUT`
    - Use 10-second request timeout on all external API calls
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3_

  - [x] 1.3 Implement `handler.py` as a thin handler that parses `queryStringParameters.query`, reads `DIRECTORY_PROVIDER` and `DIRECTORY_SECRET_NAME` from env vars, calls `logic.lookup_employee()`, and returns API Gateway proxy response in the standard KnowledgeKeeper envelope
    - Never log full Employee_Record or credential values
    - Log query type (email vs ID) and provider at INFO level
    - Catch-all exception handler returns 500 `INTERNAL_ERROR`
    - _Requirements: 1.1, 1.4, 5.1, 5.2, 7.5_

  - [x] 1.4 Write unit tests for `logic.py` in `lambdas/query/directory_lookup/tests/test_logic.py`
    - Test happy path: valid email query → Microsoft → Employee_Record
    - Test happy path: valid employee ID query → Microsoft → Employee_Record
    - Test happy path: valid email query → Google → Employee_Record
    - Test employee not found → 404 EMPLOYEE_NOT_FOUND
    - Test empty query → 400 VALIDATION_ERROR
    - Test whitespace-only query → 400 VALIDATION_ERROR
    - Test Secrets Manager failure → 500 CREDENTIALS_UNAVAILABLE
    - Test directory auth error (401) → 502 DIRECTORY_AUTH_ERROR
    - Test directory rate limit (429) → 429 DIRECTORY_RATE_LIMITED
    - Test directory server error (500) → 502 DIRECTORY_UNAVAILABLE
    - Test directory timeout → 504 DIRECTORY_TIMEOUT
    - Test invalid provider → 500 PROVIDER_NOT_CONFIGURED
    - Test Graph API response with null fields → empty strings in record
    - Test Google response with empty organizations array → empty strings for role/department
    - Use `unittest.mock` to mock Secrets Manager, Graph API, and Google Admin SDK
    - _Requirements: 1.1, 1.5, 1.6, 2.2, 2.3, 2.4, 2.5, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.3_

- [ ] 2. Property-based tests for directory lookup logic
  - [ ]* 2.1 Write property test for Employee_Record completeness
    - **Property 1: Employee record completeness**
    - Generate random valid Graph/Google responses, verify result has exactly 5 string fields and success=True with status_code=200
    - **Validates: Requirements 1.1, 1.4**

  - [ ]* 2.2 Write property test for empty/whitespace query rejection
    - **Property 2: Empty and whitespace query rejection**
    - Generate whitespace-only strings via `st.text(alphabet=string.whitespace)`, verify 400 VALIDATION_ERROR and no provider call
    - **Validates: Requirements 1.6**

  - [ ]* 2.3 Write property test for Microsoft Graph API dispatch
    - **Property 3: Microsoft Graph API email-based dispatch**
    - Generate random strings (some with `@`), verify correct URL construction for email vs ID queries
    - **Validates: Requirements 2.2, 2.3**

  - [ ]* 2.4 Write property test for Microsoft field mapping with null handling
    - **Property 4: Microsoft field mapping with null handling**
    - Generate dicts with optional None values for each Graph field, verify correct mapping and null→"" conversion
    - **Validates: Requirements 2.4, 2.5**

  - [ ]* 2.5 Write property test for Google Directory API dispatch
    - **Property 5: Google Directory API dispatch**
    - Generate random query strings, verify `userKey` parameter is set to the query value
    - **Validates: Requirements 3.2, 3.3**

  - [ ]* 2.6 Write property test for Google field mapping with null handling
    - **Property 6: Google field mapping with null handling**
    - Generate dicts with optional None values, optional empty `organizations` lists, verify correct mapping and null→"" conversion
    - **Validates: Requirements 3.4, 3.5**

  - [ ]* 2.7 Write property test for directory HTTP error classification
    - **Property 7: Directory HTTP error classification**
    - Generate HTTP status codes in {401, 403, 429, 500-599}, verify correct status code and error code mapping
    - **Validates: Requirements 4.1, 4.2, 4.3**

  - [ ]* 2.8 Write property test for invalid provider rejection
    - **Property 8: Invalid provider rejection**
    - Generate strings excluding "microsoft" and "google" (including empty string and None), verify 500 PROVIDER_NOT_CONFIGURED
    - **Validates: Requirements 5.3**

- [x] 3. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Add CDK infrastructure for directory_lookup Lambda and API Gateway route
  - [x] 4.1 Add `DirectoryLookupRole`, `DirectoryLookupFn`, and `/directory/lookup` GET route to `infrastructure/stacks/query_stack.py`
    - Create dedicated IAM role with `secretsmanager:GetSecretValue` scoped to directory secret ARN and `AWSLambdaBasicExecutionRole`
    - IAM role must NOT have DynamoDB, S3, S3 Vectors, or Bedrock permissions
    - Lambda: Python 3.12, 10-second timeout, 256 MB memory, shared layer for pydantic
    - Environment variables: `DIRECTORY_PROVIDER`, `DIRECTORY_SECRET_NAME`
    - API Gateway: `/directory/lookup` resource with GET method, API key required, Lambda proxy integration
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.6_

  - [ ]* 4.2 Write CDK assertion tests for directory_lookup infrastructure
    - Verify Lambda exists with correct runtime (Python 3.12), timeout (10s), memory (256 MB)
    - Verify IAM role has only `secretsmanager:GetSecretValue` and CloudWatch permissions
    - Verify IAM role does NOT have DynamoDB, S3, S3 Vectors, or Bedrock permissions
    - Verify API Gateway has `/directory/lookup` GET method with API key required
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.6_

- [x] 5. Checkpoint - Ensure all backend and infrastructure tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Add frontend lookup integration
  - [x] 6.1 Add `EmployeeRecord` interface and `lookupEmployee()` API function to `frontend/src/api/twins.ts`
    - `EmployeeRecord` with `employeeId`, `name`, `email`, `role`, `department` fields
    - `lookupEmployee(query: string)` calls `GET /directory/lookup` with query param
    - _Requirements: 1.1, 6.2_

  - [x] 6.2 Add lookup UI to `frontend/src/pages/AdminDashboard.tsx`
    - Add lookup input field and "Lookup" button above the offboarding form fields (inside the `showForm` block)
    - Add state for `lookupQuery`, `lookupLoading`, `lookupError`
    - On lookup success: populate `form.employeeId`, `form.name`, `form.email`, `form.role`, `form.department` from the Employee_Record
    - Leave `offboardDate` and `provider` unchanged on auto-fill
    - Allow manual editing of any auto-filled field before submission
    - Display loading indicator on button and disable it during request
    - Display inline error alert on lookup failure
    - Display specific "no employee found" message for `EMPLOYEE_NOT_FOUND` errors
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

  - [x] 6.3 Write property test for auto-fill field mapping
    - **Property 9: Auto-fill field mapping preserves unrelated fields**
    - Generate random EmployeeRecord + random form state, verify exactly 5 fields are set from record and `offboardDate`/`provider` are unchanged
    - **Validates: Requirements 6.3, 6.4**

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend uses Python (pytest + hypothesis), frontend uses TypeScript (React)
- Property 10 (Error message display) is covered by the frontend implementation in task 6.2 and can be validated via component tests
