# Requirements Document

## Introduction

This feature adds Microsoft 365 (Office 365) email integration to KnowledgeKeeper, enabling IT Admins to ingest departing employees' email archives from Microsoft 365 tenants in addition to the existing Google Workspace and file upload providers. The M365 Email Fetcher uses the Microsoft Graph API with application-level permissions to fetch emails, converts them to .mbox format, and uploads them to the existing raw-archives S3 bucket. The downstream ingestion pipeline (parser → cleaner → embedder) is provider-agnostic and requires no changes.

---

## Glossary

- **M365_Email_Fetcher**: A new AWS Lambda function that retrieves emails from Microsoft 365 mailboxes via the Microsoft Graph API and uploads batched .mbox files to S3.
- **Microsoft_Graph_API**: The Microsoft REST API used to access Microsoft 365 resources including user mailboxes.
- **Admin_Lambda**: The existing Lambda function that handles twin CRUD operations via the REST API, including provider-based dispatch to email fetcher functions.
- **Twin_Record**: A DynamoDB item in the KKTwins table representing a departing employee's digital twin, including a `provider` field.
- **Raw_Archives_Bucket**: The existing S3 bucket where .mbox files are stored before ingestion pipeline processing.
- **Secrets_Manager**: AWS Secrets Manager, used to store provider credentials at the path pattern `kk/{env}/{secret-name}`.
- **Ingestion_Pipeline**: The existing chain of Lambda functions (ingest_trigger → parser → cleaner → embedder) that processes .mbox files from S3 into vector embeddings.
- **Application_Permission**: A Microsoft Entra ID (Azure AD) permission model where the application accesses resources without a signed-in user, using client credentials (client ID + client secret or certificate).

---

## Requirements

### Requirement 1: Microsoft 365 Provider Selection

**User Story:** As an IT Admin, I want to select Microsoft 365 as the email provider when offboarding an employee, so that the system fetches emails from the organization's M365 tenant.

#### Acceptance Criteria

1. WHEN an IT Admin selects "Microsoft 365" as the email provider in the offboarding form, THE Admin_Lambda SHALL accept `"microsoft"` as a valid value for the `provider` field on `POST /twins`.
2. WHEN a Twin_Record is created with `provider: "microsoft"`, THE Admin_Lambda SHALL invoke the M365_Email_Fetcher Lambda asynchronously with the employee's `employeeId` and `email` address.
3. THE Admin_Dashboard SHALL display "Microsoft 365" as a selectable option in the email provider dropdown alongside "Google Workspace" and "File Upload (.mbox)".
4. WHEN a Twin_Record is created with `provider: "microsoft"` and the M365_Email_Fetcher invocation fails, THE Admin_Lambda SHALL log the failure and allow the Twin_Record to remain in `ingesting` status for retry.

### Requirement 2: Microsoft 365 Credential Management

**User Story:** As an IT Admin, I want Microsoft 365 application credentials stored securely, so that the system can authenticate to the Microsoft Graph API without exposing secrets.

#### Acceptance Criteria

1. THE M365_Email_Fetcher SHALL retrieve Microsoft 365 application credentials (tenant ID, client ID, and client secret) from Secrets_Manager at the path `kk/{env}/m365-credentials`.
2. THE M365_Email_Fetcher SHALL authenticate to the Microsoft_Graph_API using the OAuth 2.0 client credentials flow with the retrieved tenant ID, client ID, and client secret.
3. IF the Secrets_Manager call to retrieve M365 credentials fails, THEN THE M365_Email_Fetcher SHALL update the Twin_Record status to `error` and log the failure reason without exposing credential values.
4. WHEN the OAuth 2.0 access token expires during email fetching, THE M365_Email_Fetcher SHALL request a new access token using the client credentials flow and resume fetching without data loss.

### Requirement 3: Email Retrieval from Microsoft 365 Mailboxes

**User Story:** As an IT Admin, I want the system to automatically pull all relevant emails from a departing employee's Microsoft 365 mailbox, so that institutional knowledge is captured without manual export.

#### Acceptance Criteria

1. WHEN the M365_Email_Fetcher is invoked for an employee, THE M365_Email_Fetcher SHALL use the Microsoft_Graph_API endpoint `GET /users/{email}/mailFolders` to enumerate all mail folders in the employee's mailbox.
2. WHEN enumerating mail folders, THE M365_Email_Fetcher SHALL retrieve emails from all folders except "Deleted Items" and "Junk Email".
3. WHEN retrieving emails, THE M365_Email_Fetcher SHALL use the Microsoft_Graph_API endpoint `GET /users/{email}/mailFolders/{folderId}/messages` with pagination (using `$top` and `$skip` or `@odata.nextLink`) to fetch all messages.
4. WHEN retrieving emails, THE M365_Email_Fetcher SHALL request the following fields for each message: `id`, `internetMessageId`, `subject`, `from`, `toRecipients`, `ccRecipients`, `bccRecipients`, `body`, `receivedDateTime`, `internetMessageHeaders`, and `conversationId`.
5. WHEN the Microsoft_Graph_API returns a rate-limiting response (HTTP 429), THE M365_Email_Fetcher SHALL wait for the duration specified in the `Retry-After` header before retrying the request, up to a maximum of 5 retries per request.
6. IF the Microsoft_Graph_API returns an authorization error (HTTP 401 or 403) for a mailbox, THEN THE M365_Email_Fetcher SHALL update the Twin_Record status to `error` and log the error code without exposing token values.

### Requirement 4: Email Conversion and Upload to S3

**User Story:** As a system architect, I want Microsoft 365 emails converted to .mbox format and uploaded to S3, so that the existing provider-agnostic ingestion pipeline processes them without modification.

#### Acceptance Criteria

1. WHEN the M365_Email_Fetcher retrieves emails, THE M365_Email_Fetcher SHALL convert each batch of 100 messages into RFC 2822 format and package them as a single .mbox file.
2. WHEN uploading batches, THE M365_Email_Fetcher SHALL upload each .mbox file to the Raw_Archives_Bucket at the key `{employeeId}/batch_{batchNumber:04d}.mbox`, matching the existing key pattern used by the Google Workspace email fetcher.
3. WHEN all email batches are uploaded, THE M365_Email_Fetcher SHALL write a `manifest.json` file to `{employeeId}/manifest.json` in the Raw_Archives_Bucket containing the total email count, batch count, date range (earliest and latest `receivedDateTime`), folder breakdown, and fetch timestamp.
4. WHEN converting Microsoft_Graph_API message JSON to RFC 2822 format, THE M365_Email_Fetcher SHALL map `internetMessageId` to the `Message-ID` header, `conversationId` to the `Thread-ID` header, `from` to the `From` header, `toRecipients` to the `To` header, `ccRecipients` to the `Cc` header, `receivedDateTime` to the `Date` header, `subject` to the `Subject` header, and `body.content` to the message body.
5. WHEN the message body content type is `html`, THE M365_Email_Fetcher SHALL include both `text/html` and `text/plain` (converted from HTML) MIME parts in the RFC 2822 output.
6. IF an individual message fails to convert to RFC 2822 format, THEN THE M365_Email_Fetcher SHALL skip that message, log the message ID and error, and continue processing the remaining messages in the batch.

### Requirement 5: Infrastructure and Deployment

**User Story:** As a DevOps engineer, I want the M365 email fetcher deployed as a standard KnowledgeKeeper Lambda with proper IAM permissions, so that it follows the existing security and deployment patterns.

#### Acceptance Criteria

1. THE CDK Ingestion Stack SHALL define the M365_Email_Fetcher as a Lambda function with Python 3.12 runtime, 15-minute timeout, 1024 MB memory, and the shared Lambda layer, matching the existing email_fetcher configuration.
2. THE M365_Email_Fetcher Lambda SHALL have a dedicated IAM role with least-privilege permissions: `s3:PutObject` on the Raw_Archives_Bucket, `secretsmanager:GetSecretValue` scoped to `kk/{env}/m365-credentials`, `dynamodb:UpdateItem` on the KKTwins table, and the corresponding KMS decrypt and encrypt permissions.
3. THE CDK Ingestion Stack SHALL export the M365_Email_Fetcher function ARN as a stack output.
4. THE Admin_Lambda IAM role SHALL have `lambda:InvokeFunction` permission on the M365_Email_Fetcher function ARN.
5. THE M365_Email_Fetcher function name SHALL follow the naming convention `kk-{env}-ingestion-m365-email-fetcher`.

### Requirement 6: Data Model and API Updates

**User Story:** As a developer, I want the Twin data model and API to support the Microsoft 365 provider, so that the system correctly tracks and dispatches M365-based twins.

#### Acceptance Criteria

1. THE Twin Pydantic model SHALL accept `"microsoft"` as a valid value for the `provider` field, in addition to the existing `"google"` and `"upload"` values.
2. WHEN the Admin_Lambda receives a `POST /twins` request with `provider: "microsoft"`, THE Admin_Lambda SHALL invoke the M365_Email_Fetcher Lambda (identified by the `M365_EMAIL_FETCHER_FN_NAME` environment variable) asynchronously with the payload `{"employeeId": employeeId, "email": email}`.
3. WHEN the Admin_Lambda receives a `POST /twins` request with an unsupported provider value, THE Admin_Lambda SHALL return HTTP 400 with error code `VALIDATION_ERROR` and a message listing the valid provider values.
4. THE Admin_Dashboard provider dropdown SHALL display the provider options in the order: "Google Workspace", "Microsoft 365", "File Upload (.mbox)".

### Requirement 7: Error Handling and Observability

**User Story:** As an IT Admin, I want clear feedback when Microsoft 365 email fetching fails, so that I can diagnose and resolve configuration issues.

#### Acceptance Criteria

1. WHEN the M365_Email_Fetcher encounters an unrecoverable error, THE M365_Email_Fetcher SHALL update the Twin_Record status to `error` in DynamoDB before terminating.
2. WHEN the M365_Email_Fetcher starts processing, THE M365_Email_Fetcher SHALL log the employee ID and email address (but not credential values) at INFO level.
3. WHEN the M365_Email_Fetcher completes successfully, THE M365_Email_Fetcher SHALL log the employee ID, total email count, and batch count at INFO level.
4. IF the M365_Email_Fetcher fails to update the Twin_Record status to `error` after a primary failure, THEN THE M365_Email_Fetcher SHALL log the secondary failure at ERROR level and re-raise the original exception.
5. WHEN a batch upload to S3 fails, THE M365_Email_Fetcher SHALL retry the upload up to 3 times with exponential backoff before marking the Twin_Record status as `error`.
