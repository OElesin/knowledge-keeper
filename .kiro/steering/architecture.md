---
inclusion: always
---

# KnowledgeKeeper — Architecture & API Standards (MVP)

## Architecture Principles

1. **Serverless-first**: No persistent compute. Every piece of logic lives in a Lambda function.
2. **Event-driven ingestion**: S3 events → Lambda → SQS → Lambda chains. No polling.
3. **Separation of concerns**: Ingestion pipeline and query layer are completely independent stacks.
4. **Data never leaves the account**: All Bedrock calls stay within AWS. No third-party AI API calls.
5. **Audit everything**: Every ingestion event, query, and admin action is logged to DynamoDB and CloudWatch.
6. **Fail loudly on ingestion, fail gracefully on query**: Ingestion errors go to DLQ; query errors return a structured error response, never a 500.

## Ingestion Pipeline — Event Flow

```
S3 PutObject (raw archive)
  → Lambda: ingest_trigger
  → SQS: ParseQueue
  → Lambda: parser (thread reconstruction)
  → SQS: CleanQueue
  → Lambda: cleaner (PII detection, noise filter)
  → SQS: EmbedQueue
  → Lambda: embedder (Nova Embeddings → S3 Vectors put_vectors)
  → DynamoDB: update Twin.chunk_count + Twin.status
```

Each SQS queue has a DLQ. Failed messages after 3 retries land in DLQ.

## Query Flow

```
User → API Gateway → API Key validation
  → Lambda: query_handler
    → Embed query (Nova Multimodal Embeddings)
    → s3vectors.query_vectors() with employee_id filter (top-k=10)
    → Build prompt with retrieved chunks
    → Generate response (Amazon Nova Pro)
    → Return: { answer, sources, confidence, staleness_warning }
  → Log query to DynamoDB audit table
```

## REST API Conventions (MVP)

**Base URL**: `https://api.{domain}/v1`

**Admin Endpoints** (requires valid API key):
```
POST   /twins                              # Trigger offboarding ingestion
GET    /twins                              # List all twins
GET    /twins/{employeeId}                 # Get twin detail + status
DELETE /twins/{employeeId}                 # Delete twin (right-to-erasure)
POST   /twins/{employeeId}/access          # Grant user access
DELETE /twins/{employeeId}/access/{userId}  # Revoke user access
```

**Query Endpoints** (requires valid API key + access record in KKAccess table):
```
POST   /twins/{employeeId}/query           # Submit natural language query
```

**Response envelope — always used**:
```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "requestId": "uuid"
}
```

**Error response**:
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "TWIN_NOT_FOUND",
    "message": "No twin found for employee ID emp_123",
    "details": {}
  },
  "requestId": "uuid"
}
```

**HTTP Status codes**:
- `200` — success
- `201` — resource created (POST /twins)
- `400` — bad request (validation error)
- `401` — unauthenticated
- `403` — unauthorized (authenticated but not permitted for this twin)
- `404` — twin not found
- `409` — conflict (twin already exists)
- `429` — rate limited
- `500` — internal error (never expose raw exceptions)

## DynamoDB Access Patterns (MVP)

**Twins table** — primary key: `employeeId` (String)
- GSI: `status-offboardDate-index` for listing active twins

**Audit table** — primary key: `requestId` (String), sort key: `timestamp` (String)
- TTL: configurable, default 7 years for compliance

**Access table** — primary key: `userId` (String), sort key: `employeeId` (String)
- Attribute: `role` (admin | viewer)

## S3 Vectors Schema

**Vector bucket**: `kk-{environment}`
**Vector index**: `kk-{environment}-chunks`

```
Dimension: 1024
Distance metric: cosine
Data type: float32

Filterable metadata keys:
  - employee_id    (per-twin query filtering)
  - thread_id
  - author_role
  - date           (ISO 8601 string)

Non-filterable metadata keys:
  - content        (chunk text for RAG context)
  - subject        (thread subject line)
```

**boto3 usage**:
```python
s3v = boto3.client("s3vectors")

# Insert
s3v.put_vectors(
    vectorBucketName="kk-dev",
    indexName="kk-dev-chunks",
    vectors=[{
        "key": chunk_id,
        "data": {"float32": embedding},
        "metadata": {"employee_id": "emp_123", "date": "2024-01-15", ...}
    }]
)

# Query
s3v.query_vectors(
    vectorBucketName="kk-dev",
    indexName="kk-dev-chunks",
    queryVector={"float32": query_embedding},
    topK=10,
    filter={"employee_id": "emp_123"},
    returnDistance=True,
    returnMetadata=True
)

# Delete
s3v.delete_vectors(
    vectorBucketName="kk-dev",
    indexName="kk-dev-chunks",
    keys=["chunk_001", "chunk_002"]
)
```

## Security Standards

- All Lambda functions use individual IAM roles with least-privilege policies
- S3 buckets: versioning enabled, public access blocked, KMS encrypted
- S3 Vectors: SSE-KMS encrypted (no VPC required)
- DynamoDB: KMS encrypted, point-in-time recovery enabled
- API Gateway: throttling 1000 req/sec burst, 500 req/sec steady
- API Gateway: API key required on all endpoints
- All secrets in Secrets Manager — never in environment variables or code
