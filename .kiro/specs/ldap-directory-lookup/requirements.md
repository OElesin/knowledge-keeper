# Requirements Document

## Introduction

KnowledgeKeeper's directory employee lookup feature currently supports two directory providers: Microsoft Entra ID (Graph API) and Google Workspace (Admin SDK). Many organizations use on-premises or cloud-hosted LDAP directories (e.g., OpenLDAP, FreeIPA, Oracle Directory Server) as their primary identity store. This feature adds LDAP as a third directory provider option, enabling IT admins to configure LDAP connection details, test connectivity, and perform read-only employee lookups that auto-fill the offboarding form — using the same architecture and patterns established by the existing Microsoft and Google providers.

The LDAP provider connects to an LDAP server using simple bind authentication, searches for employees by email or employee ID using a configurable search filter template, and returns a normalized Employee_Record with the same five fields (employeeId, name, email, role, department) used by the existing providers.

## Glossary

- **Directory_Lookup_Lambda**: The existing AWS Lambda function that receives a lookup request, determines the configured directory provider, retrieves credentials from Secrets Manager, calls the appropriate directory API, and returns a normalized Employee_Record.
- **Admin_Lambda**: The existing admin Lambda function that handles directory provider configuration management including credential validation, saving, and connection testing.
- **Settings_Page**: The existing React Settings page in the Admin Dashboard where IT admins configure directory provider credentials.
- **LDAP_Server**: The target LDAP directory server (e.g., OpenLDAP, FreeIPA, Active Directory via LDAP) that the Directory_Lookup_Lambda connects to for employee lookups.
- **Bind_DN**: The Distinguished Name used to authenticate (bind) to the LDAP_Server, e.g., `cn=read-only-admin,dc=example,dc=com`.
- **Bind_Password**: The password associated with the Bind_DN for LDAP simple bind authentication.
- **Search_Base_DN**: The base Distinguished Name under which employee searches are performed, e.g., `dc=example,dc=com`.
- **Search_Filter_Template**: A configurable LDAP search filter string containing a `{query}` placeholder that is substituted with the lookup query value at runtime, e.g., `(|(mail={query})(uid={query}))`.
- **LDAP_Credential_Payload**: The set of credential and configuration fields submitted by the IT admin for LDAP: `server_url`, `port`, `bind_dn`, `bind_password`, `search_base_dn`, and `search_filter_template`.
- **Employee_Record**: The normalized data object returned by the Directory_Lookup_Lambda containing employeeId, name, email, role, and department.
- **Lookup_Query**: The search string provided by the admin, which is either an email address or an employee ID.

## Requirements

### Requirement 1: LDAP Provider Lookup

**User Story:** As an IT admin using an LDAP directory, I want the employee lookup to retrieve data from my LDAP server, so that I can auto-fill the offboarding form with accurate directory information.

#### Acceptance Criteria

1. WHEN the configured directory provider is `ldap`, THE Directory_Lookup_Lambda SHALL retrieve LDAP connection parameters (server_url, port, bind_dn, bind_password, search_base_dn, search_filter_template) from Secrets Manager.
2. WHEN performing a lookup, THE Directory_Lookup_Lambda SHALL connect to the LDAP_Server at the configured server_url and port using simple bind authentication with the Bind_DN and Bind_Password.
3. WHEN performing a lookup, THE Directory_Lookup_Lambda SHALL search under the Search_Base_DN using the Search_Filter_Template with the Lookup_Query substituted for the `{query}` placeholder.
4. WHEN the LDAP search returns one or more entries, THE Directory_Lookup_Lambda SHALL use the first matching entry and map LDAP attributes to the Employee_Record as follows: `uid` to `employeeId`, `cn` to `name`, `mail` to `email`, `title` to `role`, `departmentNumber` to `department`.
5. WHEN a mapped LDAP attribute is absent or empty in the search result, THE Directory_Lookup_Lambda SHALL set that field to an empty string in the Employee_Record.
6. WHEN the LDAP search returns zero entries, THE Directory_Lookup_Lambda SHALL return an HTTP 404 response with error code `EMPLOYEE_NOT_FOUND`.
7. THE Directory_Lookup_Lambda SHALL use the `ldap3` Python library for all LDAP operations.
8. THE Directory_Lookup_Lambda SHALL complete each LDAP lookup within 10 seconds; IF the LDAP_Server does not respond within 10 seconds, THEN THE Directory_Lookup_Lambda SHALL return an HTTP 504 response with error code `DIRECTORY_TIMEOUT`.

### Requirement 2: LDAP Error Handling

**User Story:** As an IT admin, I want clear error messages when the LDAP lookup fails, so that I can diagnose connection or configuration issues.

#### Acceptance Criteria

1. IF the LDAP bind operation fails due to invalid credentials, THEN THE Directory_Lookup_Lambda SHALL return an HTTP 502 response with error code `DIRECTORY_AUTH_ERROR` and a message indicating the LDAP bind credentials are invalid.
2. IF the LDAP_Server is unreachable or the connection is refused, THEN THE Directory_Lookup_Lambda SHALL return an HTTP 502 response with error code `DIRECTORY_UNAVAILABLE` and a message indicating the LDAP server is unreachable.
3. IF the Secrets Manager call to retrieve LDAP credentials fails, THEN THE Directory_Lookup_Lambda SHALL return an HTTP 500 response with error code `CREDENTIALS_UNAVAILABLE`.
4. IF the Search_Filter_Template does not contain a `{query}` placeholder, THEN THE Directory_Lookup_Lambda SHALL return an HTTP 500 response with error code `PROVIDER_NOT_CONFIGURED` and a message indicating the search filter template is invalid.

### Requirement 3: LDAP Credential Validation and Storage

**User Story:** As an IT admin, I want to configure LDAP connection details through the Settings page, so that I can set up the LDAP directory provider without AWS console access.

#### Acceptance Criteria

1. WHEN the Admin_Lambda receives a save or test request with provider type `ldap`, THE Admin_Lambda SHALL validate that the LDAP_Credential_Payload contains non-empty `server_url`, `bind_dn`, `bind_password`, and `search_base_dn` fields.
2. IF the `port` field is missing or empty, THEN THE Admin_Lambda SHALL default the port to `389`.
3. IF the `search_filter_template` field is missing or empty, THEN THE Admin_Lambda SHALL default the search filter template to `(|(mail={query})(uid={query}))`.
4. IF required LDAP credential fields are missing or empty, THEN THE Admin_Lambda SHALL return an HTTP 400 response with error code `VALIDATION_ERROR` and a message listing the missing fields.
5. WHEN LDAP credentials are saved successfully, THE Admin_Lambda SHALL store the full LDAP_Credential_Payload (including defaulted values for port and search_filter_template) in Secrets Manager under the existing secret name `kk/{env}/directory-creds`.

### Requirement 4: LDAP Connection Test

**User Story:** As an IT admin, I want to test LDAP connectivity before saving credentials, so that I can verify the connection works.

#### Acceptance Criteria

1. WHEN the Admin_Lambda receives a connection test request with provider type `ldap`, THE Admin_Lambda SHALL attempt to connect to the LDAP_Server and perform a simple bind using the provided Bind_DN and Bind_Password.
2. WHEN the LDAP bind succeeds, THE Admin_Lambda SHALL return a response with `test_passed` set to `true` and message "Connection successful".
3. WHEN the LDAP bind fails, THE Admin_Lambda SHALL return a response with `test_passed` set to `false` and a message describing the failure reason.
4. THE Admin_Lambda SHALL NOT store LDAP credentials in Secrets Manager or DynamoDB during a connection test.
5. THE Admin_Lambda SHALL complete each LDAP connection test within 10 seconds; IF the LDAP_Server does not respond within 10 seconds, THEN THE Admin_Lambda SHALL return a response with `test_passed` set to `false` and a message indicating a timeout.

### Requirement 5: Provider Configuration Extension

**User Story:** As a platform operator, I want the provider configuration system to recognize `ldap` as a valid provider type, so that the LDAP provider integrates with the existing configuration flow.

#### Acceptance Criteria

1. THE Admin_Lambda SHALL accept `ldap` as a valid value for the Provider_Type field in save and test requests, in addition to the existing `microsoft` and `google` values.
2. THE Directory_Lookup_Lambda SHALL accept `ldap` as a valid provider value when dispatching lookup requests, in addition to the existing `microsoft` and `google` values.
3. WHEN the `DIRECTORY_PROVIDER` environment variable or DynamoDB settings record contains `ldap`, THE Directory_Lookup_Lambda SHALL route the lookup to the LDAP provider handler.

### Requirement 6: Settings Page LDAP UI

**User Story:** As an IT admin, I want to see LDAP as a provider option on the Settings page with appropriate configuration fields, so that I can configure the LDAP directory provider through the UI.

#### Acceptance Criteria

1. THE Settings_Page SHALL display "LDAP" as a third provider option alongside "Microsoft Entra ID" and "Google Workspace" in the provider selector.
2. WHEN the admin selects "LDAP", THE Settings_Page SHALL display input fields for: Server URL, Port, Bind DN, Bind Password, Search Base DN, and Search Filter Template.
3. THE Settings_Page SHALL mask the Bind Password field using password-type input masking.
4. THE Settings_Page SHALL pre-populate the Port field with `389` as a default value.
5. THE Settings_Page SHALL pre-populate the Search Filter Template field with `(|(mail={query})(uid={query}))` as a default value.
6. THE Settings_Page SHALL display helper text below the Search Filter Template field explaining that `{query}` is replaced with the lookup value at runtime.

### Requirement 7: LDAP Dependency and Infrastructure

**User Story:** As a platform operator, I want the LDAP library included in the Lambda deployment, so that the LDAP provider functions at runtime.

#### Acceptance Criteria

1. THE Directory_Lookup_Lambda requirements.txt SHALL include the `ldap3` Python package as a dependency.
2. THE Admin_Lambda requirements.txt SHALL include the `ldap3` Python package as a dependency for connection testing.
3. THE Directory_Lookup_Lambda SHALL NOT require any additional IAM permissions beyond the existing Secrets Manager and DynamoDB permissions for LDAP lookups.
4. THE Admin_Lambda SHALL NOT require any additional IAM permissions beyond the existing permissions for LDAP connection testing.

### Requirement 8: LDAP Credential Security

**User Story:** As a platform operator, I want LDAP credentials handled with the same security standards as Microsoft and Google credentials, so that sensitive LDAP secrets are never exposed or logged.

#### Acceptance Criteria

1. THE Admin_Lambda SHALL NOT log any LDAP credential values (bind_password, bind_dn, server_url) to CloudWatch Logs.
2. THE Admin_Lambda SHALL NOT return LDAP credential values in any API response.
3. THE Settings_Page SHALL clear all LDAP credential input fields after a successful save operation.
4. THE Directory_Lookup_Lambda SHALL NOT log the Bind_Password or any LDAP credential values to CloudWatch Logs.
