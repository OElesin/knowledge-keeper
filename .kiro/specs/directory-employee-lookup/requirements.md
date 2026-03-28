# Requirements Document

## Introduction

KnowledgeKeeper currently requires IT admins to manually enter all employee details (employeeId, name, email, role, department, offboardDate) when offboarding an employee via the AdminDashboard. This feature adds an Active Directory lookup capability that retrieves employee information from Microsoft Entra ID (Graph API) or Google Workspace (Admin SDK Directory API), allowing the admin to search by email or employee ID and auto-fill the offboarding form. The lookup is read-only and the admin retains the ability to override any auto-filled field before submission.

## Glossary

- **Directory_Lookup_Lambda**: The AWS Lambda function that receives a lookup request, determines the configured directory provider, retrieves credentials from Secrets Manager, calls the appropriate directory API, and returns normalized employee data.
- **Lookup_Endpoint**: The API Gateway REST endpoint `GET /directory/lookup` that accepts a query parameter and routes the request to the Directory_Lookup_Lambda.
- **Admin_UI**: The React frontend AdminDashboard page where IT admins manage offboarding, including the new lookup field.
- **Directory_Provider**: The external identity provider configured for the organization — either Microsoft Entra ID (Graph API) or Google Workspace (Admin SDK Directory API).
- **Lookup_Query**: The search string provided by the admin, which is either an email address or an employee ID.
- **Employee_Record**: The normalized data object returned by the Directory_Lookup_Lambda containing employeeId, name, email, role, and department.

## Requirements

### Requirement 1: Directory Lookup API Endpoint

**User Story:** As an IT admin, I want a dedicated API endpoint that looks up employee information from the corporate directory, so that I can retrieve employee details without manually searching external systems.

#### Acceptance Criteria

1. WHEN the Lookup_Endpoint receives a GET request with a valid `query` parameter, THE Directory_Lookup_Lambda SHALL query the configured Directory_Provider and return an Employee_Record containing employeeId, name, email, role, and department.
2. THE Lookup_Endpoint SHALL require a valid API key in the `x-api-key` header for every request.
3. THE Lookup_Endpoint SHALL accept a `query` parameter that contains either an email address or an employee ID.
4. WHEN the Directory_Provider returns a matching user, THE Directory_Lookup_Lambda SHALL return an HTTP 200 response with the Employee_Record in the standard KnowledgeKeeper response envelope (`{ success, data, error, requestId }`).
5. WHEN the Directory_Provider returns no matching user, THE Directory_Lookup_Lambda SHALL return an HTTP 404 response with error code `EMPLOYEE_NOT_FOUND`.
6. IF the `query` parameter is missing or empty, THEN THE Directory_Lookup_Lambda SHALL return an HTTP 400 response with error code `VALIDATION_ERROR`.

### Requirement 2: Microsoft Entra ID Provider Support

**User Story:** As an IT admin using Microsoft 365, I want the lookup to retrieve employee data from Microsoft Entra ID via the Graph API, so that I can auto-fill the offboarding form with accurate directory information.

#### Acceptance Criteria

1. WHEN the configured Directory_Provider is Microsoft Entra ID, THE Directory_Lookup_Lambda SHALL authenticate using client credentials retrieved from Secrets Manager via the existing M365 app registration.
2. WHEN a Lookup_Query is an email address, THE Directory_Lookup_Lambda SHALL call the Microsoft Graph API endpoint `GET /users/{email}` with `$select=id,displayName,mail,jobTitle,department`.
3. WHEN a Lookup_Query is not an email address, THE Directory_Lookup_Lambda SHALL call the Microsoft Graph API endpoint `GET /users` with a `$filter` on `employeeId eq '{query}'` and `$select=id,displayName,mail,jobTitle,department`.
4. THE Directory_Lookup_Lambda SHALL map the Graph API response fields to the Employee_Record as follows: `id` to `employeeId`, `displayName` to `name`, `mail` to `email`, `jobTitle` to `role`, `department` to `department`.
5. WHEN a mapped field is null or absent in the Graph API response, THE Directory_Lookup_Lambda SHALL set that field to an empty string in the Employee_Record.

### Requirement 3: Google Workspace Provider Support

**User Story:** As an IT admin using Google Workspace, I want the lookup to retrieve employee data from the Google Workspace Directory via the Admin SDK, so that I can auto-fill the offboarding form with accurate directory information.

#### Acceptance Criteria

1. WHEN the configured Directory_Provider is Google Workspace, THE Directory_Lookup_Lambda SHALL authenticate using service account credentials retrieved from Secrets Manager via the existing Google Workspace service account.
2. WHEN a Lookup_Query is an email address, THE Directory_Lookup_Lambda SHALL call the Google Admin SDK Directory API `users.get` method with the email as the `userKey`.
3. WHEN a Lookup_Query is not an email address, THE Directory_Lookup_Lambda SHALL call the Google Admin SDK Directory API `users.get` method with the query value as the `userKey`.
4. THE Directory_Lookup_Lambda SHALL map the Directory API response fields to the Employee_Record as follows: `id` to `employeeId`, `name.fullName` to `name`, `primaryEmail` to `email`, `organizations[0].title` to `role`, `organizations[0].department` to `department`.
5. WHEN a mapped field is null or absent in the Directory API response, THE Directory_Lookup_Lambda SHALL set that field to an empty string in the Employee_Record.

### Requirement 4: Error Handling and Resilience

**User Story:** As an IT admin, I want the lookup to handle errors gracefully, so that I receive clear feedback when something goes wrong and can proceed with manual entry.

#### Acceptance Criteria

1. IF the Directory_Provider returns an authentication error (HTTP 401 or 403), THEN THE Directory_Lookup_Lambda SHALL return an HTTP 502 response with error code `DIRECTORY_AUTH_ERROR` and a message indicating the directory credentials are invalid or insufficient.
2. IF the Directory_Provider returns a rate-limit error (HTTP 429), THEN THE Directory_Lookup_Lambda SHALL return an HTTP 429 response with error code `DIRECTORY_RATE_LIMITED` and a message indicating the admin should retry after a short delay.
3. IF the Directory_Provider is unreachable or returns a server error (HTTP 5xx), THEN THE Directory_Lookup_Lambda SHALL return an HTTP 502 response with error code `DIRECTORY_UNAVAILABLE` and a message indicating the directory service is temporarily unavailable.
4. IF the Secrets Manager call to retrieve directory credentials fails, THEN THE Directory_Lookup_Lambda SHALL return an HTTP 500 response with error code `CREDENTIALS_UNAVAILABLE`.
5. THE Directory_Lookup_Lambda SHALL complete each lookup request within 10 seconds; IF the Directory_Provider does not respond within 10 seconds, THEN THE Directory_Lookup_Lambda SHALL return an HTTP 504 response with error code `DIRECTORY_TIMEOUT`.

### Requirement 5: Provider Configuration

**User Story:** As an IT admin, I want the system to support selecting which directory provider to use, so that the lookup works with my organization's identity provider.

#### Acceptance Criteria

1. THE Directory_Lookup_Lambda SHALL read the active directory provider from the `DIRECTORY_PROVIDER` environment variable, which contains either `microsoft` or `google`.
2. THE Directory_Lookup_Lambda SHALL read the Secrets Manager secret name from the `DIRECTORY_SECRET_NAME` environment variable.
3. IF the `DIRECTORY_PROVIDER` environment variable is not set or contains an unsupported value, THEN THE Directory_Lookup_Lambda SHALL return an HTTP 500 response with error code `PROVIDER_NOT_CONFIGURED`.

### Requirement 6: Frontend Lookup Integration

**User Story:** As an IT admin, I want a lookup field at the top of the offboarding form, so that I can search for an employee by email or ID and have the form auto-filled with their directory information.

#### Acceptance Criteria

1. WHEN the offboarding form is displayed, THE Admin_UI SHALL render a lookup input field and a "Lookup" button above the existing form fields.
2. WHEN the admin enters a Lookup_Query and activates the "Lookup" button, THE Admin_UI SHALL send a GET request to the Lookup_Endpoint with the query value.
3. WHEN the Lookup_Endpoint returns a successful Employee_Record, THE Admin_UI SHALL populate the employeeId, name, email, role, and department form fields with the returned values.
4. WHEN the Lookup_Endpoint returns a successful Employee_Record, THE Admin_UI SHALL leave the offboardDate and provider fields unchanged.
5. THE Admin_UI SHALL allow the admin to manually edit any auto-filled field before submitting the offboarding form.
6. WHILE the lookup request is in progress, THE Admin_UI SHALL display a loading indicator on the "Lookup" button and disable the button to prevent duplicate requests.
7. WHEN the Lookup_Endpoint returns an error, THE Admin_UI SHALL display the error message from the response in an inline alert above the form fields.
8. WHEN the Lookup_Endpoint returns an `EMPLOYEE_NOT_FOUND` error, THE Admin_UI SHALL display a message indicating no employee was found and the admin can fill in the fields manually.

### Requirement 7: Infrastructure and Security

**User Story:** As a platform operator, I want the lookup endpoint to follow KnowledgeKeeper's existing security and infrastructure patterns, so that the feature integrates cleanly and maintains the security posture.

#### Acceptance Criteria

1. THE Directory_Lookup_Lambda SHALL have a dedicated IAM role with least-privilege permissions scoped to Secrets Manager read access for the directory credentials secret and CloudWatch Logs write access.
2. THE Directory_Lookup_Lambda SHALL NOT have permissions to read or write to DynamoDB, S3, S3 Vectors, or Bedrock.
3. THE Lookup_Endpoint SHALL be defined in the existing API Gateway REST API with API key authentication required.
4. THE Lookup_Endpoint SHALL be subject to the existing API Gateway throttling configuration (500 requests per second steady, 1000 burst).
5. THE Directory_Lookup_Lambda SHALL NOT log the full Employee_Record or any credential values to CloudWatch Logs.
6. THE Directory_Lookup_Lambda SHALL be deployed using AWS CDK as part of the KKQueryStack.
