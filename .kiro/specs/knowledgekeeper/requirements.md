# Requirements Document (MVP)

## Introduction

KnowledgeKeeper MVP enables organizations to preserve and query institutional knowledge from departing employees by ingesting their email archives into an AI-powered RAG system using Amazon S3 Vectors. This MVP focuses on the core ingestion-to-query loop with file upload and Google Workspace integration, a React frontend for admin and query workflows, and API key authentication. Microsoft 365 integration, Cognito auth, and advanced observability are deferred to v1.1.

---

## Requirement 1: IT Admin Offboarding Trigger

**User Story:** As an IT Admin, I want to trigger knowledge capture for a departing employee from the admin dashboard, so that the ingestion process starts and I can track its status.

### Acceptance Criteria

1. WHEN an IT Admin submits the offboarding form with employee ID, name, email, role, department, and offboard date, THE SYSTEM SHALL call `POST /twins` and create a Twin record in DynamoDB with status `ingesting` and a unique `employeeId`.

2. WHEN a Twin is created with `provider: "google"`, THE SYSTEM SHALL initiate email archive retrieval from Google Workspace using the employee's email address.

3. WHEN an IT Admin uploads a .mbox or .eml file directly to the raw-archives S3 bucket under `{employeeId}/`, THE SYSTEM SHALL trigger the ingestion pipeline automatically via S3 event notification.

4. WHEN a Twin already exists for the given employee ID, THE SYSTEM SHALL reject the request with HTTP 409 and error code `TWIN_ALREADY_EXISTS`.

5. WHEN an IT Admin calls `GET /twins/{employeeId}`, THE SYSTEM SHALL return the current Twin status (`ingesting`, `processing`, `embedding`, `active`, `error`).

---

## Requirement 2: Email Ingestion from Google Workspace

**User Story:** As an IT Admin, I want the system to automatically pull email archives from Google Workspace, so that I don't have to manually export and upload mailboxes.

### Acceptance Criteria

1. WHEN Google Workspace is configured as the email provider, THE SYSTEM SHALL use the Google Workspace Admin SDK with a service account and domain-wide delegation to fetch all emails for the departing employee.

2. WHEN fetching emails, THE SYSTEM SHALL retrieve emails from all folders (Inbox, Sent, and all user-created labels) excluding Trash and Spam.

3. WHEN fetching emails, THE SYSTEM SHALL retrieve emails in batches of 100 and upload each batch as a .mbox file to the raw archive S3 bucket.

4. WHEN the OAuth service account token expires during fetching, THE SYSTEM SHALL refresh the token and resume fetching without data loss.

5. WHEN fetching is complete, THE SYSTEM SHALL write a `manifest.json` to the S3 archive folder containing total email count, date range, folder breakdown, and fetch timestamp.

---

## Requirement 3: Email Parsing and Thread Reconstruction

**User Story:** As a system architect, I want emails to be reconstructed into full conversation threads before chunking, so that retrieved knowledge retains its original context.

### Acceptance Criteria

1. WHEN the parser Lambda receives a batch of raw emails from SQS, THE SYSTEM SHALL parse each email into structured fields: `message_id`, `thread_id`, `subject`, `from`, `to`, `cc`, `date`, `body_text`, `in_reply_to`, `references`.

2. WHEN parsing, THE SYSTEM SHALL reconstruct email threads by grouping emails with the same `thread_id` or matching `in_reply_to` → `message_id` chains, ordered chronologically.

3. WHEN a thread is reconstructed, THE SYSTEM SHALL identify the primary author role for each message: `primary` (employee is `from`), `cc`, or `bcc`.

4. WHEN parsing email bodies, THE SYSTEM SHALL extract only plain text content and strip HTML tags, retaining meaningful formatting (line breaks, paragraph breaks) as whitespace.

5. WHEN parsing is complete for a batch, THE SYSTEM SHALL publish each reconstructed thread as a JSON message to the CleanQueue SQS queue.

---

## Requirement 4: Noise Filtering and PII Detection

**User Story:** As a product owner, I want low-signal emails excluded and PII redacted before indexing, so that query results are clean and compliant.

### Acceptance Criteria

1. WHEN the cleaner Lambda receives a thread from SQS, THE SYSTEM SHALL strip email signatures, legal disclaimers (detected by regex patterns), and calendar invites (MIME type `text/calendar`).

2. WHEN filtering, THE SYSTEM SHALL discard any individual message where the cleaned body text is fewer than 50 characters after stripping.

3. WHEN filtering, THE SYSTEM SHALL run Amazon Comprehend PII detection (`detect_pii_entities`) on each message body and redact detected PII (SSN, credit card numbers, phone numbers, bank account numbers) by replacing with `[REDACTED-{type}]`.

4. WHEN a Comprehend call fails, THE SYSTEM SHALL flag the chunk as `pii_unverified` and continue processing (do not discard).

5. WHEN a thread passes filtering, THE SYSTEM SHALL publish it to the EmbedQueue with author roles and the cleaned content.

---

## Requirement 5: Embedding and Vector Indexing with S3 Vectors

**User Story:** As a system architect, I want email chunks embedded and stored in S3 Vectors so that semantic search is available at query time without managing a vector database.

### Acceptance Criteria

1. WHEN the embedder Lambda receives a thread from SQS, THE SYSTEM SHALL split it into chunks of maximum 512 tokens with a 64-token overlap between consecutive chunks, with boundaries at sentence breaks.

2. WHEN embedding, THE SYSTEM SHALL call Amazon Nova Multimodal Embeddings (`amazon.nova-2-multimodal-embeddings-v1:0`) via Bedrock with `embeddingPurpose: "GENERIC_INDEX"` and `embeddingDimension: 1024`, and receive a 1024-dimensional embedding vector.

3. WHEN indexing, THE SYSTEM SHALL call `s3vectors.put_vectors()` to store each chunk's embedding in the S3 vector index `kk-{environment}-chunks`, with filterable metadata keys `employee_id`, `thread_id`, `author_role`, and `date`, and non-filterable metadata key `content` containing the chunk text.

4. WHEN indexing is complete for all chunks in an archive, THE SYSTEM SHALL update the Twin record in DynamoDB: set `status` to `active` and set `chunk_count`.

5. WHEN an embedding or put_vectors API call fails, THE SYSTEM SHALL retry up to 3 times with exponential backoff before sending the message to the DLQ.

---

## Requirement 6: Natural Language Query Interface

**User Story:** As an Engineering Manager, I want to ask natural language questions about a departed colleague's knowledge and receive grounded, cited answers.

### Acceptance Criteria

1. WHEN an authorized user submits a query via `POST /twins/{employeeId}/query`, THE SYSTEM SHALL embed the query using Amazon Nova Multimodal Embeddings (`amazon.nova-2-multimodal-embeddings-v1:0`) with `embeddingPurpose: "GENERIC_RETRIEVAL"` and call `s3vectors.query_vectors()` against the `kk-{environment}-chunks` index with a metadata filter on `employee_id`, returning top 10 results.

2. WHEN building the generation prompt, THE SYSTEM SHALL include the retrieved chunks as context and instruct Amazon Nova Pro (`amazon.nova-pro-v1:0`) to: answer only from the provided context, cite source chunk keys and dates, and say "I don't have information about that" if context is insufficient.

3. WHEN generating a response, THE SYSTEM SHALL return: `answer`, `sources` (list of chunk keys with dates and subjects), `confidence` (average cosine similarity of used chunks), and `staleness_warning` (if newest source is older than 18 months).

4. WHEN a user queries a Twin they are not authorized to access, THE SYSTEM SHALL return HTTP 403 without revealing whether the Twin exists.

5. WHEN a Twin has status other than `active`, THE SYSTEM SHALL return a structured error indicating the Twin is not yet available for querying.

---

## Requirement 7: Access Control and Authorization

**User Story:** As a CISO, I want fine-grained control over who can query which digital twin.

### Acceptance Criteria

1. WHEN an IT Admin creates a Twin, THE SYSTEM SHALL default to no query access for any user until access is explicitly granted via `POST /twins/{employeeId}/access`.

2. WHEN access is granted, THE SYSTEM SHALL support two MVP roles per twin: `admin` (full access) and `viewer` (can query only).

3. WHEN a query Lambda receives a request, THE SYSTEM SHALL validate the API key and check the KKAccess table for a matching `{userId, employeeId}` record before executing the query.

---

## Requirement 8: Twin Deletion (Right to Erasure)

**User Story:** As a CISO, I want to delete all twin data on demand for compliance.

### Acceptance Criteria

1. WHEN a Twin is created, THE SYSTEM SHALL set a `retention_expiry` date equal to the offboard date plus a configurable retention period (default: 3 years).

2. WHEN an IT Admin calls `DELETE /twins/{employeeId}`, THE SYSTEM SHALL delete all associated vectors from S3 Vectors (via `delete_vectors`), all DynamoDB records, and all S3 raw archive objects, then set Twin status to `deleted` and log the event to the audit table.

3. WHEN deletion is complete, THE SYSTEM SHALL return a confirmation response with the deletion timestamp.
