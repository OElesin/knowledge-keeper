# Requirements Document

## Introduction

This feature extends KnowledgeKeeper's ingestion pipeline to capture documents from a departing employee's OneDrive for Business / SharePoint storage via the Microsoft Graph API. Currently the platform only ingests email archives; this addition ensures institutional knowledge stored in documents (design docs, runbooks, architecture decisions, project plans, meeting notes) is also preserved in the digital twin. The feature introduces a new `sharepoint_doc_fetcher` Lambda, a `doc_parser` Lambda for extracting text from document formats, frontend controls for opting into document ingestion with optional folder filtering, and deduplication logic to avoid double-indexing content already captured via email.

---

## Glossary

- **SharePoint_Doc_Fetcher**: A new AWS Lambda function that lists and downloads documents from a departing employee's OneDrive for Business / SharePoint storage via the Microsoft Graph API and uploads them to S3.
- **Doc_Parser**: A new AWS Lambda function that extracts plain text from document files (docx, pdf, pptx, xlsx, txt) and produces structured payloads for the CleanQueue.
- **Microsoft_Graph_API**: The Microsoft REST API used to access Microsoft 365 resources including OneDrive for Business files and SharePoint sites.
- **Admin_Lambda**: The existing Lambda function that handles twin CRUD operations via the REST API, including dispatch to fetcher functions.
- **Admin_Dashboard**: The React frontend page where IT Admins trigger offboarding and configure ingestion options.
- **Twin_Record**: A DynamoDB item in the KKTwins table representing a departing employee's digital twin.
- **Raw_Archives_Bucket**: The existing S3 bucket where raw ingestion artifacts are stored before pipeline processing.
- **Ingestion_Pipeline**: The existing chain of Lambda functions (ingest_trigger → parser → cleaner → embedder) that processes raw content into vector embeddings.
- **Secrets_Manager**: AWS Secrets Manager, used to store provider credentials at the path pattern `kk/{env}/{secret-name}`.
- **DocParseQueue**: A new SQS queue that decouples document download from document text extraction.
- **Supported_File_Types**: The set of document file extensions the system ingests: `.docx`, `.pdf`, `.pptx`, `.xlsx`, `.txt`.
- **Source_Type_Metadata**: A metadata tag (`source_type`) applied to each vector chunk in S3 Vectors to distinguish between `email` and `document` origin.

---

## Requirements

### Requirement 1: Document Ingestion Toggle on Offboarding Form

**User Story:** As an IT Admin, I want to opt into document ingestion when offboarding an employee, so that the system captures SharePoint/OneDrive documents in addition to emails.

#### Acceptance Criteria

1. THE Admin_Dashboard SHALL display an "Include Documents" toggle on the offboarding form when the selected email provider is "Microsoft 365".
2. WHEN the "Include Documents" toggle is enabled, THE Admin_Dashboard SHALL display optional text fields for "Include Folders" and "Exclude Folders" where the admin can enter comma-separated folder paths.
3. WHEN the IT Admin submits the offboarding form with the "Include Documents" toggle enabled, THE Admin_Dashboard SHALL send the fields `includeDocuments: true`, `includeFolders` (array of strings or empty array), and `excludeFolders` (array of strings or empty array) in the `POST /twins` request body.
4. WHEN the IT Admin submits the offboarding form with the "Include Documents" toggle disabled or absent, THE Admin_Dashboard SHALL send `includeDocuments: false` in the `POST /twins` request body.

### Requirement 2: Admin API Support for Document Ingestion

**User Story:** As a developer, I want the Admin API to accept and persist document ingestion settings, so that the system knows whether to fetch documents for a given twin.

#### Acceptance Criteria

1. WHEN the Admin_Lambda receives a `POST /twins` request with `includeDocuments: true` and `provider: "microsoft"`, THE Admin_Lambda SHALL store `includeDocuments`, `includeFolders`, and `excludeFolders` on the Twin_Record in DynamoDB.
2. WHEN the Admin_Lambda receives a `POST /twins` request with `includeDocuments: true` and `provider: "microsoft"`, THE Admin_Lambda SHALL invoke the SharePoint_Doc_Fetcher Lambda asynchronously with the payload `{"employeeId": employeeId, "email": email, "includeFolders": [...], "excludeFolders": [...]}`.
3. WHEN the Admin_Lambda receives a `POST /twins` request with `includeDocuments: true` and a provider other than `"microsoft"`, THE Admin_Lambda SHALL return HTTP 400 with error code `VALIDATION_ERROR` and a message stating that document ingestion is only supported for the Microsoft 365 provider.
4. WHEN the Admin_Lambda receives a `POST /twins` request with `includeDocuments: false` or without the `includeDocuments` field, THE Admin_Lambda SHALL not invoke the SharePoint_Doc_Fetcher Lambda.

### Requirement 3: SharePoint Document Fetching via Microsoft Graph API

**User Story:** As an IT Admin, I want the system to automatically retrieve documents from a departing employee's OneDrive for Business, so that institutional knowledge in documents is captured without manual export.

#### Acceptance Criteria

1. WHEN the SharePoint_Doc_Fetcher is invoked, THE SharePoint_Doc_Fetcher SHALL retrieve M365 application credentials from Secrets_Manager at the path `kk/{env}/m365-credentials` and authenticate using the OAuth 2.0 client credentials flow.
2. WHEN the SharePoint_Doc_Fetcher is invoked, THE SharePoint_Doc_Fetcher SHALL use the Microsoft_Graph_API endpoint `GET /users/{email}/drive/root/children` to list files and folders in the employee's OneDrive for Business root, recursively traversing subfolders.
3. WHEN listing files, THE SharePoint_Doc_Fetcher SHALL paginate results using the `@odata.nextLink` token returned by the Microsoft_Graph_API until all items are enumerated.
4. WHEN the `includeFolders` parameter is a non-empty array, THE SharePoint_Doc_Fetcher SHALL only traverse folders whose paths match one of the specified include folder paths.
5. WHEN the `excludeFolders` parameter is a non-empty array, THE SharePoint_Doc_Fetcher SHALL skip folders whose paths match one of the specified exclude folder paths.
6. WHEN both `includeFolders` and `excludeFolders` are provided, THE SharePoint_Doc_Fetcher SHALL apply `includeFolders` first and then apply `excludeFolders` within the included set.

### Requirement 4: File Type Filtering and Size Limits

**User Story:** As a system architect, I want only supported document types within safe size limits to be ingested, so that the pipeline processes relevant content without Lambda timeouts.

#### Acceptance Criteria

1. THE SharePoint_Doc_Fetcher SHALL download only files with extensions in the Supported_File_Types set (`.docx`, `.pdf`, `.pptx`, `.xlsx`, `.txt`) and skip all other file types.
2. THE SharePoint_Doc_Fetcher SHALL skip files larger than 100 MB and log the skipped file name, size, and employee ID at WARN level.
3. WHEN the Microsoft_Graph_API returns a rate-limiting response (HTTP 429), THE SharePoint_Doc_Fetcher SHALL wait for the duration specified in the `Retry-After` header before retrying the request, up to a maximum of 5 retries per request.
4. IF the Microsoft_Graph_API returns an authorization error (HTTP 401 or 403), THEN THE SharePoint_Doc_Fetcher SHALL update the Twin_Record status to `error` and log the error code without exposing token values.

### Requirement 5: Document Upload to S3

**User Story:** As a system architect, I want downloaded documents stored in S3 under a consistent key structure, so that the downstream pipeline can locate and process them.

#### Acceptance Criteria

1. WHEN the SharePoint_Doc_Fetcher downloads a document, THE SharePoint_Doc_Fetcher SHALL upload the file to the Raw_Archives_Bucket at the key `{employeeId}/documents/{sanitized_file_path}` where `sanitized_file_path` preserves the original folder structure with forward slashes and URL-unsafe characters removed.
2. WHEN all documents are uploaded, THE SharePoint_Doc_Fetcher SHALL write a `doc_manifest.json` file to `{employeeId}/doc_manifest.json` in the Raw_Archives_Bucket containing the total file count, total byte size, list of file keys with their original names and sizes, skipped file count, and fetch timestamp.
3. WHEN the `doc_manifest.json` is uploaded, THE SharePoint_Doc_Fetcher SHALL send one SQS message per uploaded document to the DocParseQueue containing the S3 bucket, S3 key, employee ID, original file name, and file extension.
4. IF an individual file download from the Microsoft_Graph_API fails, THEN THE SharePoint_Doc_Fetcher SHALL skip that file, log the file name and error at ERROR level, and continue processing the remaining files.

### Requirement 6: Document Text Extraction

**User Story:** As a system architect, I want document files parsed into plain text, so that the existing cleaner and embedder pipeline can process document content the same way it processes email content.

#### Acceptance Criteria

1. WHEN the Doc_Parser receives a message from the DocParseQueue, THE Doc_Parser SHALL download the document from the Raw_Archives_Bucket and extract plain text based on the file extension.
2. THE Doc_Parser SHALL extract text from `.docx` files using the `python-docx` library, from `.pdf` files using the `pypdf` library, from `.pptx` files using the `python-pptx` library, from `.xlsx` files by reading cell values with the `openpyxl` library, and from `.txt` files by reading the raw UTF-8 content.
3. WHEN the Doc_Parser extracts text from a document, THE Doc_Parser SHALL produce a payload for the CleanQueue containing `employeeId`, `threadId` (set to the S3 key of the document), `subject` (set to the original file name), `source_type: "document"`, and a single message entry with `body_text` set to the extracted text and `date` set to the document's last modified timestamp from the manifest.
4. IF the Doc_Parser fails to extract text from a document, THEN THE Doc_Parser SHALL log the file name and error at ERROR level and report the SQS message as a batch item failure.
5. FOR ALL supported document formats, extracting text and then re-extracting from the same source file SHALL produce identical text output (deterministic extraction).

### Requirement 7: Source Type Tagging in Vector Metadata

**User Story:** As a developer, I want document-sourced chunks tagged with a source type in vector metadata, so that queries can distinguish between email and document knowledge.

#### Acceptance Criteria

1. THE Embedder Lambda SHALL include a `source_type` field in the S3 Vectors metadata for each chunk, set to `"email"` for chunks originating from the email pipeline and `"document"` for chunks originating from the document pipeline.
2. THE Embedder Lambda SHALL propagate the `source_type` field from the CleanQueue message payload into the vector metadata without modification.
3. WHEN the `source_type` field is absent from the CleanQueue message, THE Embedder Lambda SHALL default the `source_type` metadata value to `"email"` to maintain backward compatibility with existing email-only ingestion.

### Requirement 8: Document Deduplication

**User Story:** As a system architect, I want documents that were already shared as email attachments to be detected and skipped, so that the twin does not contain duplicate knowledge chunks.

#### Acceptance Criteria

1. WHEN the Doc_Parser extracts text from a document, THE Doc_Parser SHALL compute a SHA-256 hash of the first 10,000 characters of the extracted text.
2. BEFORE sending the cleaned document payload to the CleanQueue, THE Doc_Parser SHALL check the deduplication DynamoDB table for an existing entry with the same `employeeId` and content hash.
3. IF a matching content hash exists for the same employee, THEN THE Doc_Parser SHALL skip the document, log the duplicate detection at INFO level with the file name and matching hash, and not send a message to the CleanQueue.
4. WHEN the Doc_Parser sends a new document payload to the CleanQueue, THE Doc_Parser SHALL write the `employeeId` and content hash to the deduplication DynamoDB table.
5. WHEN the email parser processes email attachments, THE email parser SHALL compute the same SHA-256 hash of the first 10,000 characters and write the hash to the deduplication DynamoDB table, enabling cross-source deduplication.

### Requirement 9: PII Detection on Document Chunks

**User Story:** As a CISO, I want PII detection to run on document-sourced chunks before embedding, so that sensitive information in documents is handled with the same safeguards as email content.

#### Acceptance Criteria

1. WHEN the Cleaner Lambda receives a message with `source_type: "document"`, THE Cleaner Lambda SHALL run Amazon Comprehend PII detection on the document text using the same redaction rules applied to email content.
2. WHEN the Cleaner Lambda processes a document-sourced message, THE Cleaner Lambda SHALL skip signature stripping and disclaimer removal steps that are specific to email content.
3. IF the Comprehend PII detection call fails for a document chunk, THEN THE Cleaner Lambda SHALL flag the chunk with `pii_unverified: true` and proceed with indexing, matching the existing email behavior.

### Requirement 10: Infrastructure and Security

**User Story:** As a DevOps engineer, I want the SharePoint document fetcher and document parser deployed with proper IAM roles and infrastructure, so that they follow existing security and deployment patterns.

#### Acceptance Criteria

1. THE CDK Ingestion Stack SHALL define the SharePoint_Doc_Fetcher as a Lambda function with Python 3.12 runtime, 15-minute timeout, 1024 MB memory, and the shared Lambda layer.
2. THE SharePoint_Doc_Fetcher Lambda SHALL have a dedicated IAM role with least-privilege permissions: `s3:PutObject` on the Raw_Archives_Bucket, `secretsmanager:GetSecretValue` scoped to `kk/{env}/m365-credentials`, `dynamodb:UpdateItem` on the KKTwins table, `sqs:SendMessage` on the DocParseQueue, and the corresponding KMS permissions.
3. THE CDK Ingestion Stack SHALL define the Doc_Parser as a Lambda function with Python 3.12 runtime, 5-minute timeout, 512 MB memory, and the shared Lambda layer.
4. THE Doc_Parser Lambda SHALL have a dedicated IAM role with least-privilege permissions: `s3:GetObject` on the Raw_Archives_Bucket, `sqs:SendMessage` on the CleanQueue, `sqs:ReceiveMessage` and `sqs:DeleteMessage` and `sqs:GetQueueAttributes` on the DocParseQueue, `dynamodb:GetItem` and `dynamodb:PutItem` on the deduplication table, and the corresponding KMS permissions.
5. THE CDK Ingestion Stack SHALL define the DocParseQueue as an SQS queue with a dead-letter queue, matching the configuration pattern of the existing ParseQueue (visibility timeout 300 seconds, max receive count 3, DLQ retention 14 days).
6. THE M365 app registration SHALL use the `Files.Read.All` application permission for read-only access to employee files via the Microsoft_Graph_API.
7. THE SharePoint_Doc_Fetcher SHALL access files using read-only Graph API endpoints and SHALL NOT call any write or delete endpoints on the employee's OneDrive.

### Requirement 11: Twin Metadata Updates for Document Ingestion

**User Story:** As an IT Admin, I want the twin's metadata to reflect document ingestion progress, so that I can monitor the status of document processing.

#### Acceptance Criteria

1. WHEN the SharePoint_Doc_Fetcher begins processing, THE SharePoint_Doc_Fetcher SHALL update the Twin_Record with `docIngestionStatus: "fetching"`.
2. WHEN the SharePoint_Doc_Fetcher completes uploading all documents to S3, THE SharePoint_Doc_Fetcher SHALL update the Twin_Record with `docIngestionStatus: "processing"` and `docCount` set to the number of documents uploaded.
3. WHEN the Embedder Lambda finishes embedding document-sourced chunks for an employee, THE Embedder Lambda SHALL increment the Twin_Record `chunkCount` by the number of new document chunks indexed.
4. IF the SharePoint_Doc_Fetcher encounters an unrecoverable error, THEN THE SharePoint_Doc_Fetcher SHALL update the Twin_Record with `docIngestionStatus: "error"` and log the error at ERROR level without exposing credential values.

### Requirement 12: Error Handling and Observability

**User Story:** As an IT Admin, I want clear logging and error feedback for document ingestion, so that I can diagnose issues with SharePoint document fetching and parsing.

#### Acceptance Criteria

1. WHEN the SharePoint_Doc_Fetcher starts processing, THE SharePoint_Doc_Fetcher SHALL log the employee ID and email address at INFO level without logging credential values.
2. WHEN the SharePoint_Doc_Fetcher completes successfully, THE SharePoint_Doc_Fetcher SHALL log the employee ID, total document count, total byte size, and skipped file count at INFO level.
3. WHEN the Doc_Parser successfully extracts text from a document, THE Doc_Parser SHALL log the employee ID, file name, and extracted text length at INFO level.
4. WHEN a batch upload to S3 fails, THE SharePoint_Doc_Fetcher SHALL retry the upload up to 3 times with exponential backoff (1 second, 2 seconds, 4 seconds) before recording the file as skipped.
