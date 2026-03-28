# Requirements Document

## Introduction

This feature extends KnowledgeKeeper's ingestion pipeline to capture documents from a departing employee's Google Drive storage via the Google Drive API. Currently the platform ingests email archives from Google Workspace; this addition ensures institutional knowledge stored in documents (design docs, runbooks, architecture decisions, project plans, meeting notes) is also preserved in the digital twin. The feature introduces a new `gdrive_doc_fetcher` Lambda that lists files owned by the employee and downloads content to S3, reuses the existing `Doc_Parser` Lambda and `DocParseQueue` from the SharePoint document ingestion spec for text extraction, and adds frontend controls for opting into document ingestion with optional folder filtering when the provider is "google". Google-native formats (Docs, Sheets, Slides) are exported to their Office equivalents via the Drive API export endpoint. Deduplication, PII detection, source type tagging, and twin metadata updates follow the same patterns established by the SharePoint document ingestion spec.

---

## Glossary

- **GDrive_Doc_Fetcher**: A new AWS Lambda function that lists and downloads documents from a departing employee's Google Drive via the Google Drive API and uploads them to S3.
- **Google_Drive_API**: The Google REST API used to list, download, and export files from a user's Google Drive, accessed via the `files.list`, `files.get`, and `files.export` endpoints.
- **Google_Service_Account**: The existing Google Workspace service account with domain-wide delegation, used to impersonate the departing employee for read-only Drive access.
- **Doc_Parser**: The existing Lambda function (from the SharePoint document ingestion spec) that extracts plain text from document files (docx, pdf, pptx, xlsx, txt) and produces structured payloads for the CleanQueue.
- **Admin_Lambda**: The existing Lambda function that handles twin CRUD operations via the REST API, including dispatch to fetcher functions.
- **Admin_Dashboard**: The React frontend page where IT Admins trigger offboarding and configure ingestion options.
- **Twin_Record**: A DynamoDB item in the KKTwins table representing a departing employee's digital twin.
- **Raw_Archives_Bucket**: The existing S3 bucket where raw ingestion artifacts are stored before pipeline processing.
- **Secrets_Manager**: AWS Secrets Manager, used to store provider credentials at the path pattern `kk/{env}/{secret-name}`.
- **DocParseQueue**: The existing SQS queue (from the SharePoint document ingestion spec) that decouples document download from document text extraction.
- **Supported_File_Types**: The set of document file extensions the system ingests: `.docx`, `.pdf`, `.pptx`, `.xlsx`, `.txt`.
- **Google_Native_Format**: A file type that exists only within Google Drive and has no downloadable binary content: Google Docs, Google Sheets, and Google Slides. These must be exported via the Drive API export endpoint.
- **Source_Type_Metadata**: A metadata tag (`source_type`) applied to each vector chunk in S3 Vectors to distinguish between `email` and `document` origin.
- **Deduplication_Table**: The existing DynamoDB table (from the SharePoint document ingestion spec) used to store SHA-256 content hashes per employee to prevent duplicate indexing across email attachments and documents.

---

## Requirements

### Requirement 1: Document Ingestion Toggle on Offboarding Form for Google Provider

**User Story:** As an IT Admin, I want to opt into document ingestion when offboarding a Google Workspace employee, so that the system captures Google Drive documents in addition to emails.

#### Acceptance Criteria

1. THE Admin_Dashboard SHALL display an "Include Documents" toggle on the offboarding form when the selected email provider is "google".
2. WHEN the "Include Documents" toggle is enabled, THE Admin_Dashboard SHALL display optional text fields for "Include Folders" and "Exclude Folders" where the admin can enter comma-separated folder paths.
3. WHEN the IT Admin submits the offboarding form with the "Include Documents" toggle enabled, THE Admin_Dashboard SHALL send the fields `includeDocuments: true`, `includeFolders` (array of strings or empty array), and `excludeFolders` (array of strings or empty array) in the `POST /twins` request body.
4. WHEN the IT Admin submits the offboarding form with the "Include Documents" toggle disabled or absent, THE Admin_Dashboard SHALL send `includeDocuments: false` in the `POST /twins` request body.

### Requirement 2: Admin API Support for Google Drive Document Ingestion

**User Story:** As a developer, I want the Admin API to accept and persist document ingestion settings for Google provider twins, so that the system knows whether to fetch Google Drive documents for a given twin.

#### Acceptance Criteria

1. WHEN the Admin_Lambda receives a `POST /twins` request with `includeDocuments: true` and `provider: "google"`, THE Admin_Lambda SHALL store `includeDocuments`, `includeFolders`, and `excludeFolders` on the Twin_Record in DynamoDB.
2. WHEN the Admin_Lambda receives a `POST /twins` request with `includeDocuments: true` and `provider: "google"`, THE Admin_Lambda SHALL invoke the GDrive_Doc_Fetcher Lambda asynchronously with the payload `{"employeeId": employeeId, "email": email, "includeFolders": [...], "excludeFolders": [...]}`.
3. WHEN the Admin_Lambda receives a `POST /twins` request with `includeDocuments: true` and `provider: "upload"`, THE Admin_Lambda SHALL return HTTP 400 with error code `VALIDATION_ERROR` and a message stating that document ingestion is only supported for the Google and Microsoft providers.
4. WHEN the Admin_Lambda receives a `POST /twins` request with `includeDocuments: false` or without the `includeDocuments` field, THE Admin_Lambda SHALL not invoke the GDrive_Doc_Fetcher Lambda.

### Requirement 3: Google Drive Document Fetching via Drive API

**User Story:** As an IT Admin, I want the system to automatically retrieve documents from a departing employee's Google Drive, so that institutional knowledge in documents is captured without manual export.

#### Acceptance Criteria

1. WHEN the GDrive_Doc_Fetcher is invoked, THE GDrive_Doc_Fetcher SHALL retrieve Google service account credentials from Secrets_Manager at the path `kk/{env}/google-workspace-creds` and create delegated credentials for the departing employee's email address with the `https://www.googleapis.com/auth/drive.readonly` scope.
2. WHEN the GDrive_Doc_Fetcher is invoked, THE GDrive_Doc_Fetcher SHALL use the Google_Drive_API `files.list` endpoint with the query parameter `trashed=false` to list non-trashed files owned by the employee, recursively traversing folders.
3. WHEN listing files, THE GDrive_Doc_Fetcher SHALL paginate results using the `nextPageToken` returned by the Google_Drive_API until all items are enumerated.
4. WHEN the `includeFolders` parameter is a non-empty array, THE GDrive_Doc_Fetcher SHALL only traverse folders whose paths match one of the specified include folder paths.
5. WHEN the `excludeFolders` parameter is a non-empty array, THE GDrive_Doc_Fetcher SHALL skip folders whose paths match one of the specified exclude folder paths.
6. WHEN both `includeFolders` and `excludeFolders` are provided, THE GDrive_Doc_Fetcher SHALL apply `includeFolders` first and then apply `excludeFolders` within the included set.

### Requirement 4: Google Native Format Export

**User Story:** As a system architect, I want Google-native document formats exported to standard Office formats, so that the existing Doc_Parser can extract text from them.

#### Acceptance Criteria

1. WHEN the GDrive_Doc_Fetcher encounters a Google Docs file (MIME type `application/vnd.google-apps.document`), THE GDrive_Doc_Fetcher SHALL export the file as `.docx` using the Drive API export endpoint with MIME type `application/vnd.openxmlformats-officedocument.wordprocessingml.document`.
2. WHEN the GDrive_Doc_Fetcher encounters a Google Sheets file (MIME type `application/vnd.google-apps.spreadsheet`), THE GDrive_Doc_Fetcher SHALL export the file as `.xlsx` using the Drive API export endpoint with MIME type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
3. WHEN the GDrive_Doc_Fetcher encounters a Google Slides file (MIME type `application/vnd.google-apps.presentation`), THE GDrive_Doc_Fetcher SHALL export the file as `.pptx` using the Drive API export endpoint with MIME type `application/vnd.openxmlformats-officedocument.presentationml.presentation`.
4. WHEN the GDrive_Doc_Fetcher encounters a native file with a Supported_File_Type extension (docx, pdf, pptx, xlsx, txt), THE GDrive_Doc_Fetcher SHALL download the file content using the Drive API `files.get` endpoint with `alt=media`.
5. THE GDrive_Doc_Fetcher SHALL skip all file types that are not in the Supported_File_Types set and are not a Google_Native_Format (Docs, Sheets, Slides).

### Requirement 5: File Size Limits and Rate Limiting

**User Story:** As a system architect, I want only files within safe size limits to be ingested and API rate limits respected, so that the pipeline processes content without Lambda timeouts or throttling errors.

#### Acceptance Criteria

1. THE GDrive_Doc_Fetcher SHALL skip files larger than 100 MB and log the skipped file name, size, and employee ID at WARN level.
2. WHEN the Google_Drive_API returns a rate-limiting response (HTTP 429), THE GDrive_Doc_Fetcher SHALL wait for the duration specified in the `Retry-After` header before retrying the request, up to a maximum of 5 retries per request.
3. IF the Google_Drive_API returns an authorization error (HTTP 401 or 403), THEN THE GDrive_Doc_Fetcher SHALL update the Twin_Record status to `error` and log the error code without exposing token values or credential content.

### Requirement 6: Document Upload to S3

**User Story:** As a system architect, I want downloaded documents stored in S3 under a consistent key structure, so that the downstream pipeline can locate and process them.

#### Acceptance Criteria

1. WHEN the GDrive_Doc_Fetcher downloads or exports a document, THE GDrive_Doc_Fetcher SHALL upload the file to the Raw_Archives_Bucket at the key `{employeeId}/documents/{sanitized_file_path}` where `sanitized_file_path` preserves the original folder structure with forward slashes and URL-unsafe characters removed.
2. WHEN all documents are uploaded, THE GDrive_Doc_Fetcher SHALL write a `doc_manifest.json` file to `{employeeId}/doc_manifest.json` in the Raw_Archives_Bucket containing the total file count, total byte size, list of file keys with their original names and sizes, skipped file count, and fetch timestamp.
3. WHEN the `doc_manifest.json` is uploaded, THE GDrive_Doc_Fetcher SHALL send one SQS message per uploaded document to the DocParseQueue containing the S3 bucket, S3 key, employee ID, original file name, and file extension.
4. IF an individual file download or export from the Google_Drive_API fails, THEN THE GDrive_Doc_Fetcher SHALL skip that file, log the file name and error at ERROR level, and continue processing the remaining files.

### Requirement 7: Reuse of Existing Doc_Parser and DocParseQueue

**User Story:** As a developer, I want the Google Drive document pipeline to reuse the same Doc_Parser Lambda and DocParseQueue established by the SharePoint spec, so that document text extraction logic is not duplicated.

#### Acceptance Criteria

1. THE GDrive_Doc_Fetcher SHALL send SQS messages to the same DocParseQueue used by the SharePoint_Doc_Fetcher, using the same message schema: S3 bucket, S3 key, employee ID, original file name, and file extension.
2. THE Doc_Parser SHALL process documents from Google Drive using the same text extraction logic applied to SharePoint documents, without requiring changes to the Doc_Parser code.
3. THE Doc_Parser SHALL produce CleanQueue payloads with `source_type: "document"` for Google Drive documents, matching the tagging used for SharePoint documents.

### Requirement 8: Document Deduplication

**User Story:** As a system architect, I want documents that were already shared as email attachments or ingested from another source to be detected and skipped, so that the twin does not contain duplicate knowledge chunks.

#### Acceptance Criteria

1. WHEN the Doc_Parser extracts text from a Google Drive document, THE Doc_Parser SHALL compute a SHA-256 hash of the first 10,000 characters of the extracted text.
2. BEFORE sending the cleaned document payload to the CleanQueue, THE Doc_Parser SHALL check the Deduplication_Table for an existing entry with the same `employeeId` and content hash.
3. IF a matching content hash exists for the same employee, THEN THE Doc_Parser SHALL skip the document, log the duplicate detection at INFO level with the file name and matching hash, and not send a message to the CleanQueue.
4. WHEN the Doc_Parser sends a new document payload to the CleanQueue, THE Doc_Parser SHALL write the `employeeId` and content hash to the Deduplication_Table.

### Requirement 9: PII Detection on Document Chunks

**User Story:** As a CISO, I want PII detection to run on Google Drive document chunks before embedding, so that sensitive information in documents is handled with the same safeguards as email content.

#### Acceptance Criteria

1. WHEN the Cleaner Lambda receives a message with `source_type: "document"` originating from Google Drive, THE Cleaner Lambda SHALL run Amazon Comprehend PII detection on the document text using the same redaction rules applied to email content.
2. WHEN the Cleaner Lambda processes a document-sourced message, THE Cleaner Lambda SHALL skip signature stripping and disclaimer removal steps that are specific to email content.
3. IF the Comprehend PII detection call fails for a document chunk, THEN THE Cleaner Lambda SHALL flag the chunk with `pii_unverified: true` and proceed with indexing, matching the existing email behavior.

### Requirement 10: Source Type Tagging in Vector Metadata

**User Story:** As a developer, I want Google Drive document chunks tagged with a source type in vector metadata, so that queries can distinguish between email and document knowledge.

#### Acceptance Criteria

1. THE Embedder Lambda SHALL include a `source_type` field in the S3 Vectors metadata for each chunk, set to `"document"` for chunks originating from the Google Drive document pipeline.
2. THE Embedder Lambda SHALL propagate the `source_type` field from the CleanQueue message payload into the vector metadata without modification.
3. WHEN the `source_type` field is absent from the CleanQueue message, THE Embedder Lambda SHALL default the `source_type` metadata value to `"email"` to maintain backward compatibility with existing email-only ingestion.

### Requirement 11: Infrastructure and Security

**User Story:** As a DevOps engineer, I want the Google Drive document fetcher deployed with proper IAM roles and infrastructure, so that it follows existing security and deployment patterns.

#### Acceptance Criteria

1. THE CDK Ingestion Stack SHALL define the GDrive_Doc_Fetcher as a Lambda function with Python 3.12 runtime, 15-minute timeout, 1024 MB memory, and the shared Lambda layer.
2. THE GDrive_Doc_Fetcher Lambda SHALL have a dedicated IAM role with least-privilege permissions: `s3:PutObject` on the Raw_Archives_Bucket, `secretsmanager:GetSecretValue` scoped to `kk/{env}/google-workspace-creds`, `dynamodb:UpdateItem` on the KKTwins table, `sqs:SendMessage` on the DocParseQueue, and the corresponding KMS permissions.
3. THE Google_Service_Account domain-wide delegation SHALL include the `https://www.googleapis.com/auth/drive.readonly` scope in addition to the existing Gmail readonly scope.
4. THE GDrive_Doc_Fetcher SHALL access files using read-only Drive API endpoints and SHALL NOT call any write or delete endpoints on the employee's Google Drive.
5. THE GDrive_Doc_Fetcher SHALL reuse the existing Google Workspace service account credentials stored in Secrets_Manager at `kk/{env}/google-workspace-creds`, requiring no new secret creation.

### Requirement 12: Twin Metadata Updates for Document Ingestion

**User Story:** As an IT Admin, I want the twin's metadata to reflect Google Drive document ingestion progress, so that I can monitor the status of document processing.

#### Acceptance Criteria

1. WHEN the GDrive_Doc_Fetcher begins processing, THE GDrive_Doc_Fetcher SHALL update the Twin_Record with `docIngestionStatus: "fetching"`.
2. WHEN the GDrive_Doc_Fetcher completes uploading all documents to S3, THE GDrive_Doc_Fetcher SHALL update the Twin_Record with `docIngestionStatus: "processing"` and `docCount` set to the number of documents uploaded.
3. WHEN the Embedder Lambda finishes embedding document-sourced chunks for an employee, THE Embedder Lambda SHALL increment the Twin_Record `chunkCount` by the number of new document chunks indexed.
4. IF the GDrive_Doc_Fetcher encounters an unrecoverable error, THEN THE GDrive_Doc_Fetcher SHALL update the Twin_Record with `docIngestionStatus: "error"` and log the error at ERROR level without exposing credential values.

### Requirement 13: Error Handling and Observability

**User Story:** As an IT Admin, I want clear logging and error feedback for Google Drive document ingestion, so that I can diagnose issues with document fetching and parsing.

#### Acceptance Criteria

1. WHEN the GDrive_Doc_Fetcher starts processing, THE GDrive_Doc_Fetcher SHALL log the employee ID and email address at INFO level without logging credential values or access tokens.
2. WHEN the GDrive_Doc_Fetcher completes successfully, THE GDrive_Doc_Fetcher SHALL log the employee ID, total document count, total byte size, skipped file count, and count of Google_Native_Format exports at INFO level.
3. WHEN the Doc_Parser successfully extracts text from a Google Drive document, THE Doc_Parser SHALL log the employee ID, file name, and extracted text length at INFO level.
4. WHEN a file upload to S3 fails, THE GDrive_Doc_Fetcher SHALL retry the upload up to 3 times with exponential backoff (1 second, 2 seconds, 4 seconds) before recording the file as skipped.
