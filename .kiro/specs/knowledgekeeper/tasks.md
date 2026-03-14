# Tasks (MVP)

## Implementation Plan

Tasks are ordered by dependency. Complete each phase before moving to the next.

---

### Phase 1: Foundation — Storage & Infrastructure

- [x] 1.1 Initialize CDK project
  - Create `infrastructure/` directory with CDK Python app
  - Configure `cdk.json` with dev environment context (account, region, retention periods)
  - Create base `app.py` that instantiates KKStorageStack, KKIngestionStack, KKQueryStack
  - Add `requirements.txt` with `aws-cdk-lib`, `constructs`

- [x] 1.2 Implement KKStorageStack — S3 bucket
  > Supports: Req 1 AC3 (S3 event trigger), Req 2 AC3 (batch upload target), Req 8 AC2 (deletion target)
  - Create `infrastructure/stacks/storage_stack.py`
  - Create `raw-archives` S3 bucket with: KMS encryption (customer-managed CMK), versioning enabled, `BlockPublicAccess.BLOCK_ALL`
  - Configure lifecycle rule: expire objects after 90 days (value from `cdk.json` context)
  - Export bucket name and ARN as stack outputs for cross-stack references

- [x] 1.3 Implement KKStorageStack — S3 Vectors
  > Supports: Req 5 AC2-AC3 (embedding storage), Req 6 AC1 (query search), Req 8 AC2 (deletion)
  - Import `CfnVectorBucket` and `CfnVectorIndex` from `aws_cdk.aws_s3vectors`
  - Create vector bucket `kk-{env}` using `CfnVectorBucket`
  - Create vector index `kk-{env}-chunks` using `CfnVectorIndex` with: `dimension=1024`, `distanceMetric="cosine"`, `dataType="float32"`
  - Configure non-filterable metadata keys: `content`, `subject`
  - Export vector bucket name and index name as stack outputs

- [x] 1.4 Implement KKStorageStack — DynamoDB tables
  > Supports: Req 1 AC1 (Twin record), Req 7 (access control), Req 8 AC2 (audit logging)
  - Create `KKTwins` table: partition key `employeeId` (String); GSI `status-offboardDate-index` (PK: `status`, SK: `offboardDate`)
  - Create `KKAudit` table: partition key `requestId` (String), sort key `timestamp` (String); enable TTL on `ttl` attribute
  - Create `KKAccess` table: partition key `userId` (String), sort key `employeeId` (String)
  - Enable KMS encryption (customer-managed CMK) and point-in-time recovery on all tables
  - Export table names and ARNs as stack outputs

- [x] 1.5 Implement shared Lambda layer
  > Supports: All Lambda tasks — shared utilities used across ingestion and query Lambdas
  - Create `lambdas/shared/models.py`: Pydantic models for `Twin`, `EmailChunk`, `QueryResult` per design doc data models
  - Create `lambdas/shared/bedrock.py`: wrapper functions for Nova Multimodal Embeddings (`amazon.nova-2-multimodal-embeddings-v1:0`) with `GENERIC_INDEX` and `GENERIC_RETRIEVAL` purposes, and Nova Pro (`amazon.nova-pro-v1:0`) Converse API calls
  - Create `lambdas/shared/dynamo.py`: DynamoDB helper functions for Twin CRUD, Access table lookups, Audit table writes
  - Create `lambdas/shared/s3vectors_client.py`: wrapper for `s3vectors` boto3 client — `put_vectors()`, `query_vectors()`, `delete_vectors()` calls
  - Add `lambdas/shared/requirements.txt` with `pydantic`, `boto3`
  - Add Lambda Layer construct in `KKIngestionStack` or `KKStorageStack` that packages `lambdas/shared/`

---

### Phase 2: Ingestion Pipeline

- [x] 2.1 Implement KKIngestionStack — SQS queues
  > Supports: Req 3 AC5 (CleanQueue), Req 4 AC5 (EmbedQueue), Req 5 AC5 (DLQ on failure)
  - Create `infrastructure/stacks/ingestion_stack.py`
  - Create ParseQueue, CleanQueue, EmbedQueue as standard SQS queues
  - Create a DLQ for each queue: 14-day message retention, max receive count = 3
  - Set visibility timeouts: ParseQueue=300s, CleanQueue=300s, EmbedQueue=600s
  - Export queue URLs and ARNs as stack outputs

- [x] 2.2 Implement Lambda: ingest_trigger
  > Supports: Req 1 AC3 (S3 event triggers pipeline), Req 1 AC5 (status update to `processing`)
  - Create `lambdas/ingestion/trigger/handler.py` and `lambdas/ingestion/trigger/logic.py`
  - Handler: parse S3 PutObject event, extract bucket/key
  - Logic: extract `employeeId` from S3 key pattern `{employeeId}/batch_*.mbox`
  - Publish message to ParseQueue: `{employeeId, s3Key, batchNumber}`
  - Update Twin status to `processing` in KKTwins table
  - CDK: create Lambda function with S3 event notification on raw-archives bucket, own IAM role with SQS:SendMessage + DynamoDB:UpdateItem + S3:GetObject permissions

- [x] 2.3 Implement Lambda: parser
  > Supports: Req 3 AC1-AC5 (email parsing, thread reconstruction, publish to CleanQueue)
  - Create `lambdas/ingestion/parser/handler.py` and `lambdas/ingestion/parser/logic.py`
  - Handler: process SQS batch (batch size: 10), download .mbox from S3
  - Logic: parse .mbox using Python `mailbox` module; extract `message_id`, `thread_id`, `subject`, `from`, `to`, `cc`, `date`, `body_text`, `in_reply_to`
  - Strip HTML with BeautifulSoup, retain whitespace for formatting
  - Reconstruct threads: build `message_id → email` and `in_reply_to → parent` graph, walk depth-first from roots
  - Identify author role per message: `primary` (employee is sender) | `cc` | `bcc`
  - Publish each reconstructed thread as JSON to CleanQueue
  - CDK: SQS event source mapping, own IAM role with S3:GetObject + SQS:SendMessage + SQS:ReceiveMessage/DeleteMessage
  - Add `beautifulsoup4` to function `requirements.txt`

- [x] 2.4 Implement Lambda: cleaner
  > Supports: Req 4 AC1-AC5 (noise filtering, PII detection, publish to EmbedQueue)
  - Create `lambdas/ingestion/cleaner/handler.py` and `lambdas/ingestion/cleaner/logic.py`
  - Handler: process SQS batch (batch size: 5)
  - Logic: strip signatures (`--`, `Best,`, `Thanks,` patterns), legal disclaimers (regex), calendar invites (`text/calendar`)
  - Discard messages with cleaned body < 50 characters
  - Call `comprehend.detect_pii_entities()` on each message body; redact SSN, credit card, phone, bank account with `[REDACTED-{type}]`
  - On Comprehend failure: set `pii_unverified=True` on the message, continue processing
  - Publish cleaned threads to EmbedQueue
  - CDK: SQS event source mapping, own IAM role with Comprehend:DetectPiiEntities + SQS:SendMessage + SQS:ReceiveMessage/DeleteMessage

- [x] 2.5 Implement Lambda: embedder
  > Supports: Req 5 AC1-AC5 (chunking, embedding, S3 Vectors indexing, Twin status update)
  - Create `lambdas/ingestion/embedder/handler.py` and `lambdas/ingestion/embedder/logic.py`
  - Handler: process SQS batch (batch size: 3)
  - Logic: chunk threads at sentence boundaries — max 512 tokens, 64-token overlap
  - Call Nova Multimodal Embeddings via `bedrock.invoke_model()` with `taskType: "SINGLE_EMBEDDING"`, `embeddingPurpose: "GENERIC_INDEX"`, `embeddingDimension: 1024`
  - Call `s3vectors.put_vectors()` with chunk embedding + metadata (filterable: `employee_id`, `thread_id`, `author_role`, `date`; non-filterable: `content`, `subject`)
  - On completion of all chunks: update Twin in DynamoDB — set `status` to `active`, set `chunk_count`
  - Retry failed Bedrock/S3Vectors calls 3x with exponential backoff; on final failure, let message go to DLQ
  - CDK: SQS event source mapping, own IAM role with Bedrock:InvokeModel (scoped to Nova Embeddings model ARN) + S3Vectors:PutVectors + DynamoDB:UpdateItem + SQS permissions

- [x] 2.6 Implement Lambda: email_fetcher (Google Workspace)
  > Supports: Req 2 AC1-AC5 (Google Workspace email fetching, batch upload, manifest)
  - Create `lambdas/ingestion/email_fetcher/handler.py` and `lambdas/ingestion/email_fetcher/logic.py`
  - Handler: parse event with `employeeId` and `email`
  - Logic: retrieve Google service account credentials from Secrets Manager (`kk/{env}/google-workspace-creds`)
  - Use Google Workspace Admin SDK with domain-wide delegation to fetch all emails (exclude Trash, Spam)
  - Batch 100 emails per .mbox file, upload to S3 `raw-archives/{employeeId}/batch_{NNNN}.mbox`
  - On token expiry: refresh OAuth token and resume
  - On completion: write `manifest.json` to S3 with total count, date range, folder breakdown, fetch timestamp
  - CDK: Lambda with 15-min timeout, 1024MB memory, own IAM role with S3:PutObject + SecretsManager:GetSecretValue

---

### Phase 3: Query Layer & API

- [ ] 3.1 Implement KKQueryStack — API Gateway with API Key auth
  > Supports: Req 7 AC3 (API key validation), architecture API standards
  - Create `infrastructure/stacks/query_stack.py`
  - Create REST API (`apigateway.RestApi`) with Lambda proxy integration
  - Create usage plan with throttle: 500 requests/sec steady-state, 1000 burst
  - Create API key and associate with usage plan
  - Configure CORS: allow frontend origin, `x-api-key` and `x-user-id` in allowed headers
  - Export API URL and API key ID as stack outputs

- [ ] 3.2 Implement KKQueryStack — API routes
  > Supports: Req 1 AC1-AC5, Req 6 AC1, Req 7 AC1-AC2, Req 8 AC2 (all API endpoints)
  - Define REST API resources and methods:
    - `POST /twins` → admin Lambda
    - `GET /twins` → admin Lambda
    - `GET /twins/{employeeId}` → admin Lambda
    - `DELETE /twins/{employeeId}` → admin Lambda
    - `POST /twins/{employeeId}/query` → query_handler Lambda
    - `POST /twins/{employeeId}/access` → admin Lambda
    - `DELETE /twins/{employeeId}/access/{userId}` → admin Lambda
  - All methods require API key (`apiKeyRequired: true`)
  - Wire Lambda proxy integrations for each route

- [ ] 3.3 Implement Lambda: query_handler
  > Supports: Req 6 AC1-AC5 (query embedding, vector search, RAG generation, response envelope), Req 7 AC3 (access check)
  - Create `lambdas/query/query_handler/handler.py` and `lambdas/query/query_handler/logic.py`
  - Handler: extract `x-user-id` header, `employeeId` path param, `query` from body
  - Logic: check KKAccess table for `{userId, employeeId}` — return 403 if absent (Req 6 AC4)
  - Check Twin status is `active` — return error if not (Req 6 AC5)
  - Embed query with Nova Multimodal Embeddings using `embeddingPurpose: "GENERIC_RETRIEVAL"`
  - Call `s3vectors.query_vectors()` with `employee_id` filter, `topK=10`, `returnDistance=True`, `returnMetadata=True`
  - Build RAG prompt with retrieved chunks as context
  - Call Nova Pro (`amazon.nova-pro-v1:0`) via Bedrock Converse API
  - Calculate confidence (average cosine similarity), check staleness (newest source > 18 months)
  - Log query to KKAudit table
  - Return response envelope: `{answer, sources, confidence, staleness_warning}`
  - CDK: own IAM role with Bedrock:InvokeModel (Nova Embeddings + Nova Pro ARNs), S3Vectors:QueryVectors, DynamoDB:GetItem (Access + Twins), DynamoDB:PutItem (Audit)

- [ ] 3.4 Implement Lambda: admin
  > Supports: Req 1 AC1-AC5 (twin CRUD), Req 7 AC1-AC2 (access management), Req 8 AC1-AC3 (deletion + retention)
  - Create `lambdas/query/admin/handler.py` and `lambdas/query/admin/logic.py`
  - `POST /twins`: validate required fields, check for existing twin (409 if exists), create Twin record with status `ingesting` and `retention_expiry` (offboard_date + configurable retention), optionally invoke email_fetcher async
  - `GET /twins`: scan KKTwins table (or query GSI for filtered listing)
  - `GET /twins/{employeeId}`: get Twin record, return status + metadata
  - `DELETE /twins/{employeeId}`: delete vectors via `s3vectors.delete_vectors()`, delete DynamoDB records (Twins, Access), delete S3 raw archive objects, log to KKAudit, return deletion timestamp
  - `POST /twins/{employeeId}/access`: put record in KKAccess with `{userId, employeeId, role}`
  - `DELETE /twins/{employeeId}/access/{userId}`: delete record from KKAccess
  - CDK: own IAM role with DynamoDB (Twins, Access, Audit tables), S3Vectors:DeleteVectors, S3:DeleteObject, Lambda:InvokeFunction (email_fetcher)

---

### Phase 4: Frontend

- [ ] 4.1 Bootstrap React app
  > Supports: All frontend requirements — project scaffolding
  - Run `npm create vite@latest frontend -- --template react-ts` in project root
  - Install dependencies: `tailwindcss`, `@tanstack/react-query`, `react-router-dom`, `axios`
  - Configure TailwindCSS (`tailwind.config.js`, PostCSS)
  - Create `frontend/src/api/client.ts`: Axios instance with `baseURL` from `VITE_API_URL`, default headers `x-api-key` and `x-user-id`
  - Create `.env.example` with `VITE_API_URL`
  - Set up React Router with routes: `/` (dashboard), `/twins/:employeeId` (detail), `/twins/:employeeId/query` (query)

- [ ] 4.2 Implement AdminDashboard page
  > Supports: Req 1 AC1 (offboarding form), Req 1 AC5 (status tracking)
  - Create `frontend/src/pages/AdminDashboard.tsx`
  - Twin list table: columns for employee name, status (with `TwinStatusBadge` component), offboard date, chunk count
  - Fetch twin list via `GET /twins` using React Query
  - Offboarding form: fields for employee ID, name, email, role, department, offboard date, provider selection (Google / file upload)
  - Form submission calls `POST /twins`, shows success/error feedback
  - Poll for twin status updates using `useIngestionStatus` hook (refetch interval)

- [ ] 4.3 Implement TwinDetail page
  > Supports: Req 1 AC5 (status detail), Req 7 AC1-AC2 (access management), Req 8 AC2 (deletion)
  - Create `frontend/src/pages/TwinDetail.tsx`
  - Display twin metadata: name, email, role, department, offboard date, status, chunk count
  - Access control section: table of users with roles, grant access form (user ID + role dropdown), revoke button per user
  - Grant calls `POST /twins/{employeeId}/access`, revoke calls `DELETE /twins/{employeeId}/access/{userId}`
  - Delete twin button with confirmation dialog; calls `DELETE /twins/{employeeId}`

- [ ] 4.4 Implement QueryInterface page
  > Supports: Req 6 AC1-AC3 (query submission, cited answers, confidence, staleness)
  - Create `frontend/src/pages/QueryInterface.tsx`
  - Chat-style input for natural language queries against selected twin
  - Submit query via `POST /twins/{employeeId}/query`
  - Display answer text with inline source citations
  - `SourceCitation` component: expandable cards showing chunk date, subject, content preview
  - `ConfidenceBar` component: visual bar for confidence score
  - `StalenessWarning` component: orange banner when `staleness_warning` is present

---

### Phase 5: Documentation

- [ ] 5.1 Write deployment guide
  > Supports: Operational readiness
  - Create `docs/deployment.md`: prerequisites (AWS CLI, CDK CLI, Python 3.12, Node.js), CDK bootstrap command, `cdk deploy --all` instructions, post-deploy verification steps (API key retrieval, test API call)

- [ ] 5.2 Write API reference
  > Supports: Developer onboarding
  - Create `docs/api-reference.md`: all 7 endpoints with request/response schemas, error codes, auth flow (API key in `x-api-key` header, user ID in `x-user-id` header), example curl commands
