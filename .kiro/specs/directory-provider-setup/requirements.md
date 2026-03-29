# Requirements Document

## Introduction

KnowledgeKeeper's directory employee lookup feature currently requires the platform operator to manually configure directory provider credentials via AWS Secrets Manager and set CDK environment variables (`DIRECTORY_PROVIDER`, `DIRECTORY_SECRET_NAME`) before deploying. This creates a dependency on CDK redeployments and direct AWS console access for what should be an IT admin self-service operation.

This feature adds a Directory Provider Settings page to the Admin Dashboard UI, along with supporting API endpoints, that allows IT admins to select a directory provider (Microsoft Entra ID or Google Workspace), enter credentials, test the connection, and save the configuration — all without CDK redeployments or AWS console access. The credentials are stored securely in AWS Secrets Manager, and the `directory_lookup` Lambda is updated at runtime to read the active provider configuration from a DynamoDB settings record rather than relying solely on CDK-set environment variables.

## Glossary

- **Admin_Dashboard**: The React frontend application where IT admins manage offboarding, twin lifecycle, and now directory provider configuration.
- **Settings_Page**: A new page in the Admin_Dashboard dedicated to directory provider configuration.
- **Directory_Config_API**: The set of API Gateway endpoints under `/admin/directory-config` that handle reading, saving, and testing directory provider configuration.
- **Admin_Lambda**: The existing admin Lambda function (`kk-{env}-query-admin`) that is extended with new routes for directory configuration management.
- **Directory_Lookup_Lambda**: The existing Lambda function (`kk-{env}-directory-lookup`) that performs employee lookups against the configured directory provider.
- **Provider_Type**: A string value of either `microsoft` or `google` identifying the active directory provider.
- **Connection_Test**: A lightweight verification operation that uses the provided credentials to authenticate against the selected directory provider and confirm the credentials are valid, without performing a full employee lookup.
- **Directory_Settings_Record**: A DynamoDB item in the Twins table (partition key `SETTINGS#directory`) that stores the active Provider_Type and the Secrets Manager secret name for the directory credentials.
- **Credential_Payload**: The set of credential fields submitted by the IT admin — for Microsoft: `tenant_id`, `client_id`, `client_secret`; for Google: the service account JSON key and optional `delegated_admin` email.

## Requirements

### Requirement 1: Directory Configuration Read Endpoint

**User Story:** As an IT admin, I want to view the current directory provider configuration status, so that I can see which provider is active and whether credentials are configured.

#### Acceptance Criteria

1. WHEN the Admin_Dashboard sends a GET request to `/admin/directory-config`, THE Admin_Lambda SHALL return the current Directory_Settings_Record containing the active Provider_Type and a boolean indicating whether credentials exist in Secrets Manager.
2. THE Admin_Lambda SHALL NOT return any credential values (tenant_id, client_id, client_secret, service account key) in the GET response.
3. IF no Directory_Settings_Record exists, THEN THE Admin_Lambda SHALL return a response with Provider_Type set to `null` and credentials_configured set to `false`.
4. THE Directory_Config_API SHALL require a valid API key in the `x-api-key` header for every request.

### Requirement 2: Directory Configuration Save Endpoint

**User Story:** As an IT admin, I want to save directory provider credentials through the Admin Dashboard, so that I can configure the directory lookup without needing AWS console access or CDK redeployments.

#### Acceptance Criteria

1. WHEN the Admin_Dashboard sends a PUT request to `/admin/directory-config` with a valid Provider_Type and Credential_Payload, THE Admin_Lambda SHALL store the credentials in Secrets Manager under the secret name `kk/{env}/directory-creds` and save the Provider_Type to the Directory_Settings_Record in DynamoDB.
2. IF the Provider_Type is `microsoft`, THEN THE Admin_Lambda SHALL validate that the Credential_Payload contains non-empty `tenant_id`, `client_id`, and `client_secret` fields before saving.
3. IF the Provider_Type is `google`, THEN THE Admin_Lambda SHALL validate that the Credential_Payload contains a non-empty `service_account_key` field that is valid JSON before saving.
4. IF required credential fields are missing or empty, THEN THE Admin_Lambda SHALL return an HTTP 400 response with error code `VALIDATION_ERROR` and a message listing the missing fields.
5. IF the Provider_Type is not `microsoft` or `google`, THEN THE Admin_Lambda SHALL return an HTTP 400 response with error code `VALIDATION_ERROR`.
6. WHEN credentials are saved successfully, THE Admin_Lambda SHALL return an HTTP 200 response with the updated Provider_Type and `credentials_configured` set to `true`.
7. THE Admin_Lambda SHALL overwrite any previously stored credentials in Secrets Manager when new credentials are saved for the same or different provider.
8. THE Admin_Lambda SHALL write an audit log entry for every successful directory configuration save, recording the Provider_Type and the admin user ID.

### Requirement 3: Directory Connection Test Endpoint

**User Story:** As an IT admin, I want to test directory credentials before saving them, so that I can verify the connection works and avoid saving invalid credentials.

#### Acceptance Criteria

1. WHEN the Admin_Dashboard sends a POST request to `/admin/directory-config/test` with a Provider_Type and Credential_Payload, THE Admin_Lambda SHALL attempt to authenticate against the selected directory provider using the provided credentials.
2. WHEN the authentication succeeds, THE Admin_Lambda SHALL return an HTTP 200 response with `test_passed` set to `true`.
3. WHEN the authentication fails, THE Admin_Lambda SHALL return an HTTP 200 response with `test_passed` set to `false` and a `message` field describing the failure reason.
4. THE Admin_Lambda SHALL NOT store the credentials in Secrets Manager or DynamoDB during a connection test.
5. IF required credential fields are missing or empty, THEN THE Admin_Lambda SHALL return an HTTP 400 response with error code `VALIDATION_ERROR`.
6. THE Admin_Lambda SHALL complete each connection test within 10 seconds; IF the directory provider does not respond within 10 seconds, THEN THE Admin_Lambda SHALL return a response with `test_passed` set to `false` and a message indicating a timeout.

### Requirement 4: Directory Lookup Lambda Runtime Configuration

**User Story:** As a platform operator, I want the directory lookup Lambda to read its provider configuration from DynamoDB at runtime, so that IT admins can change the directory provider without requiring a CDK redeployment.

#### Acceptance Criteria

1. WHEN the Directory_Lookup_Lambda receives a lookup request, THE Directory_Lookup_Lambda SHALL first read the Directory_Settings_Record from DynamoDB to determine the active Provider_Type and secret name.
2. IF a Directory_Settings_Record exists in DynamoDB, THEN THE Directory_Lookup_Lambda SHALL use the Provider_Type and secret name from the DynamoDB record, overriding the `DIRECTORY_PROVIDER` and `DIRECTORY_SECRET_NAME` environment variables.
3. IF no Directory_Settings_Record exists in DynamoDB, THEN THE Directory_Lookup_Lambda SHALL fall back to reading the `DIRECTORY_PROVIDER` and `DIRECTORY_SECRET_NAME` environment variables.
4. IF neither a Directory_Settings_Record nor valid environment variables are available, THEN THE Directory_Lookup_Lambda SHALL return an HTTP 500 response with error code `PROVIDER_NOT_CONFIGURED`.

### Requirement 5: Admin Lambda IAM and Infrastructure

**User Story:** As a platform operator, I want the admin Lambda to have the minimum permissions needed for directory configuration management, so that the security posture is maintained.

#### Acceptance Criteria

1. THE Admin_Lambda IAM role SHALL have `secretsmanager:CreateSecret`, `secretsmanager:PutSecretValue`, and `secretsmanager:GetSecretValue` permissions scoped to the secret ARN pattern `kk/{env}/directory-creds`.
2. THE Admin_Lambda IAM role SHALL have `secretsmanager:DescribeSecret` permission scoped to the secret ARN pattern `kk/{env}/directory-creds` to check whether credentials exist.
3. THE Directory_Lookup_Lambda IAM role SHALL have `dynamodb:GetItem` permission on the Twins table to read the Directory_Settings_Record.
4. THE Directory_Config_API endpoints SHALL be defined in the existing API Gateway REST API under the `/admin/directory-config` path with API key authentication required.
5. THE Admin_Lambda SHALL be deployed using AWS CDK as part of the KKQueryStack with the updated IAM permissions and environment variables.

### Requirement 6: Settings Page UI — Provider Selection and Credential Entry

**User Story:** As an IT admin, I want a settings page in the Admin Dashboard where I can select a directory provider and enter credentials, so that I can configure the directory lookup through a user-friendly interface.

#### Acceptance Criteria

1. THE Admin_Dashboard SHALL include a Settings page accessible via a navigation link from the main dashboard.
2. WHEN the Settings_Page loads, THE Admin_Dashboard SHALL send a GET request to `/admin/directory-config` and display the current configuration status (active provider and whether credentials are configured).
3. THE Settings_Page SHALL display a provider selector with two options: "Microsoft Entra ID" and "Google Workspace".
4. WHEN the admin selects "Microsoft Entra ID", THE Settings_Page SHALL display input fields for `tenant_id`, `client_id`, and `client_secret`.
5. WHEN the admin selects "Google Workspace", THE Settings_Page SHALL display a textarea for the service account JSON key and an optional input field for `delegated_admin` email.
6. THE Settings_Page SHALL mask the `client_secret` field and the service account JSON key textarea using password-type input masking.
7. WHILE no provider is selected, THE Settings_Page SHALL disable the "Test Connection" and "Save" buttons.

### Requirement 7: Settings Page UI — Connection Test and Save

**User Story:** As an IT admin, I want to test the connection and save credentials from the settings page, so that I can verify and persist my directory configuration in one workflow.

#### Acceptance Criteria

1. WHEN the admin clicks the "Test Connection" button, THE Settings_Page SHALL send a POST request to `/admin/directory-config/test` with the selected Provider_Type and entered Credential_Payload.
2. WHEN the connection test returns `test_passed` as `true`, THE Settings_Page SHALL display a success indicator with the message "Connection successful".
3. WHEN the connection test returns `test_passed` as `false`, THE Settings_Page SHALL display an error indicator with the failure message from the response.
4. WHILE a connection test is in progress, THE Settings_Page SHALL display a loading indicator on the "Test Connection" button and disable both the "Test Connection" and "Save" buttons.
5. WHEN the admin clicks the "Save" button, THE Settings_Page SHALL send a PUT request to `/admin/directory-config` with the selected Provider_Type and entered Credential_Payload.
6. WHEN the save operation succeeds, THE Settings_Page SHALL display a success notification and update the displayed configuration status.
7. WHEN the save operation fails, THE Settings_Page SHALL display the error message from the response in an inline alert.
8. WHILE a save operation is in progress, THE Settings_Page SHALL display a loading indicator on the "Save" button and disable both the "Test Connection" and "Save" buttons.

### Requirement 8: Credential Security

**User Story:** As a platform operator, I want directory credentials to be handled securely at every layer, so that sensitive secrets are never exposed or logged.

#### Acceptance Criteria

1. THE Admin_Lambda SHALL NOT log any credential values (client_secret, service account key contents, tenant_id, client_id) to CloudWatch Logs.
2. THE Admin_Lambda SHALL NOT return credential values in any API response, including the GET configuration endpoint.
3. THE Settings_Page SHALL clear all credential input fields after a successful save operation.
4. THE Settings_Page SHALL NOT store credential values in browser local storage, session storage, or cookies.
5. THE Admin_Lambda SHALL store credentials in Secrets Manager with the default KMS encryption provided by Secrets Manager.
