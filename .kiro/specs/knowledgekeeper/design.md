# Design Document

## Overview

KnowledgeKeeper is implemented as a fully serverless AWS application with two independent functional layers: an **ingestion pipeline** (event-driven, asynchronous) and a **query layer** (synchronous, request/response). These layers share a storage tier but are deployed as separate CDK stacks to allow independent scaling and deployment. A React frontend provides admin and query interfaces.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INGESTION LAYER                             │
│                                                                     │
│  Email Provider (Google Workspace)                                  │
│          │                                                          │
│          ▼                                                          │
│  Lambda: email_fetcher ──────────────────────────────────┐         │
│  (fetches via Admin SDK)                                  │         │
│                                                           ▼         │
│  S3: raw-archives/                          S3 PutObject event      │
│    └── {employeeId}/                                     │         │
│         └── batch_001.mbox                               ▼         │
│                                              Lambda: ingest_trigger │
│                                                           │         │
│                                                           ▼         │
│                                               SQS: ParseQueue      │
│                                                           │         │
│                                                           ▼         │
│                                              Lambda: parser        │
│                                          (thread reconstruction)   │
│                                                           │         │
│                                                           ▼         │
│                                               SQS: CleanQueue      │
│                                                           │         │
│                                                           ▼         │
│                                              Lambda: cleaner       │
│                                    (PII detection, noise filter)   │
│                                                           │         │
│                                                           ▼         │
│                                               SQS: EmbedQueue      │
│                                                           │         │
│                                                           ▼         │
│                                              Lambda: embedder      │
│                                    (Nova Embeddings → S3 Vectors)  │
│                                                           │         │
│                                                           ▼         │
│                                           DynamoDB: update Twin     │
│                                               status → "active"     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                          QUERY LAYER                                │
│                                                                     │
│  React Frontend ──► API Gateway (REST) ──► API Key validation      │
│                                                   │                 │
│                                                   ▼                 │
│                                      Lambda: query_handler          │
│                                                   │                 │
│                    ┌──────────────────────────────┤                 │
│                    ▼                              ▼                 │
│         Bedrock: Nova Embeddings        S3 Vectors                 │
│         (embed query, 1024-dim)     (query_vectors, top-10)        │
│                    │                              │                 │
│                    └──────────────────────────────┘                 │
│                                                   │                 │
│                                                   ▼                 │
│                                      Bedrock: Amazon Nova Pro      │
│                                  (RAG generation with citations)    │
│                                                   │                 │
│                                                   ▼                 │
│                    { answer, sources, confidence, staleness }       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                         STORAGE LAYER                               │
│                                                                     │
│  S3 Buckets:                    DynamoDB Tables:                    │
│  • raw-archives                 • KKTwins (twin metadata)          │
│                                 • KKAudit (query + admin audit)    │
│  S3 Vectors:                    • KKAccess (user-twin ACL)         │
│  • kk-{env} bucket                                                 │
│  • kk-{env}-chunks index        Secrets Manager:                   │
│    (1024-dim, cosine, float32)  • google-workspace-creds           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Design

### Lambda: email_fetcher

**Trigger**: Invoked directly by `admin` Lambda (async)
**Runtime**: Python 3.12, up to 15 min timeout, 1024MB memory

```python
# Pseudocode
def handler(event, context):
    employee_id = event["employeeId"]
    creds = get_secret("kk/{env}/google-workspace-creds")  # from Secrets Manager

    emails = GoogleWorkspaceFetcher(creds).fetch_all(event["email"])

    for batch in chunk_list(emails, size=100):
        mbox_content = convert_to_mbox(batch)
        s3.put_object(
            Bucket=RAW_ARCHIVE_BUCKET,
            Key=f"{employee_id}/batch_{batch_num:04d}.mbox",
            Body=mbox_content
        )

    write_manifest(employee_id, total_count, date_range)
```

### Lambda: parser

**Trigger**: SQS ParseQueue (batch size: 10 messages)
**Runtime**: Python 3.12, 5 min timeout

Thread reconstruction algorithm:
1. Parse all emails in batch using Python `mailbox` module
2. Build graph: `message_id → email`, `in_reply_to → parent message_id`
3. Walk graph depth-first from root messages to reconstruct thread chains
4. Output each thread as an ordered list of `EmailMessage` objects

### Lambda: cleaner

**Trigger**: SQS CleanQueue (batch size: 5 messages)
**Runtime**: Python 3.12, 5 min timeout

Processing steps:
1. Strip email signatures (`--`, `Best,`, `Thanks,` patterns), legal disclaimers (regex), calendar invites
2. Discard messages with cleaned body < 50 characters
3. Run Amazon Comprehend `detect_pii_entities` on each message body
4. Redact detected PII (SSN, credit card, phone, bank account) with `[REDACTED-{type}]`
5. Flag as `pii_unverified` if Comprehend call fails (do not discard)
6. Publish cleaned threads to EmbedQueue

### Lambda: embedder

**Trigger**: SQS EmbedQueue (batch size: 3 threads)
**Runtime**: Python 3.12, 10 min timeout

Chunking strategy:
```python
def chunk_thread(thread: Thread, max_tokens=512, overlap=64) -> list[Chunk]:
    sentences = split_into_sentences(thread.full_text)
    chunks = []
    current_chunk = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = count_tokens(sentence)
        if current_tokens + sentence_tokens > max_tokens:
            chunks.append(build_chunk(current_chunk, thread.metadata))
            current_chunk = current_chunk[-overlap_sentences:]
            current_tokens = count_tokens(current_chunk)
        current_chunk.append(sentence)
        current_tokens += sentence_tokens

    if current_chunk:
        chunks.append(build_chunk(current_chunk, thread.metadata))

    return chunks
```

Embedding with Nova Multimodal Embeddings:
```python
def embed_chunk(text: str) -> list[float]:
    response = bedrock.invoke_model(
        modelId="amazon.nova-2-multimodal-embeddings-v1:0",
        body=json.dumps({
            "taskType": "SINGLE_EMBEDDING",
            "singleEmbeddingParams": {
                "embeddingPurpose": "GENERIC_INDEX"
            },
            "embeddingDimension": 1024,
            "text": {
                "truncationMode": "END",
                "value": text
            }
        })
    )
    body = json.loads(response["body"].read())
    return body["embeddings"][0]["embedding"]
```

Indexing with S3 Vectors:
```python
s3v.put_vectors(
    vectorBucketName=f"kk-{env}",
    indexName=f"kk-{env}-chunks",
    vectors=[{
        "key": chunk_id,
        "data": {"float32": embedding},
        "metadata": {
            "employee_id": employee_id,
            "thread_id": thread_id,
            "author_role": author_role,
            "date": date_iso,
            "content": chunk_text,
            "subject": subject
        }
    }]
)
```

### Lambda: query_handler

**Trigger**: API Gateway POST `/twins/{employeeId}/query`

```python
def handler(event, context):
    employee_id = event["pathParameters"]["employeeId"]
    user_id = event["headers"].get("x-user-id")
    body = json.loads(event["body"])
    query_text = body["query"]

    # Check access in KKAccess table
    access = dynamo.get_item(
        TableName=ACCESS_TABLE,
        Key={"userId": user_id, "employeeId": employee_id}
    )
    if not access.get("Item"):
        return error_response(403, "ACCESS_DENIED", "Not authorized")

    # Get twin metadata
    twin = dynamo.get_item(
        TableName=TWINS_TABLE,
        Key={"employeeId": employee_id}
    )
    if not twin.get("Item") or twin["Item"]["status"] != "active":
        return error_response(400, "TWIN_NOT_ACTIVE", "Twin not available")

    # Embed query (GENERIC_RETRIEVAL purpose)
    query_embedding = embed_query(query_text)

    # Search S3 Vectors
    results = s3v.query_vectors(
        vectorBucketName=f"kk-{env}",
        indexName=f"kk-{env}-chunks",
        queryVector={"float32": query_embedding},
        topK=10,
        filter={"employee_id": employee_id},
        returnDistance=True,
        returnMetadata=True
    )

    # Build RAG prompt + generate with Nova Pro
    chunks = results["vectors"]
    prompt = build_rag_prompt(twin["Item"], query_text, chunks)
    response = bedrock.converse(
        modelId="amazon.nova-pro-v1:0",
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        system=[{"text": RAG_SYSTEM_PROMPT.format(**twin["Item"])}]
    )
    answer = response["output"]["message"]["content"][0]["text"]

    # Log to audit + return
    log_query_audit(employee_id, user_id, query_text)
    return success_response({
        "answer": answer,
        "sources": format_sources(chunks),
        "confidence": calculate_confidence(chunks),
        "staleness_warning": check_staleness(chunks)
    })
```

RAG system prompt:
```python
RAG_SYSTEM_PROMPT = """
You are a knowledge retrieval assistant for {name}, who was a {role}
in the {department} department. You have access to excerpts from their
work emails dated between {tenure_start} and {offboard_date}.

Rules:
1. Answer ONLY from the provided context. Do not use general knowledge.
2. For every factual claim, cite the source chunk ID and date in brackets.
3. If the context does not contain sufficient information, say exactly:
   "I don't have information about that in {name}'s knowledge base."
4. Never invent technical details, system names, or decisions.
5. If sources are older than 18 months, note that the information may be outdated.
"""
```

### Lambda: admin

**Trigger**: API Gateway — all `/twins` admin routes

```python
def handler(event, context):
    method = event["httpMethod"]
    path = event["resource"]

    if method == "POST" and path == "/twins":
        return create_twin(event)
    elif method == "GET" and path == "/twins":
        return list_twins(event)
    elif method == "GET" and path == "/twins/{employeeId}":
        return get_twin(event)
    elif method == "DELETE" and path == "/twins/{employeeId}":
        return delete_twin(event)
    elif method == "POST" and path == "/twins/{employeeId}/access":
        return grant_access(event)
    elif method == "DELETE" and path == "/twins/{employeeId}/access/{userId}":
        return revoke_access(event)
```

---

## CDK Stack Design

### KKStorageStack
- S3 bucket: `raw-archives` (KMS encrypted, versioning, public access blocked, lifecycle rule)
- S3 Vectors: `CfnVectorBucket` (`kk-{env}`) + `CfnVectorIndex` (`kk-{env}-chunks`, 1024-dim, cosine, float32)
- DynamoDB tables: KKTwins, KKAudit, KKAccess (all KMS encrypted, PITR enabled)
- KMS keys for each storage service

### KKIngestionStack (depends on KKStorageStack)
- SQS queues: ParseQueue, CleanQueue, EmbedQueue + DLQs
- Lambda functions: email_fetcher, ingest_trigger, parser, cleaner, embedder
- S3 event notification: raw-archives → ingest_trigger
- SQS event source mappings for each Lambda
- IAM roles with least-privilege per Lambda

### KKQueryStack (depends on KKStorageStack)
- API Gateway REST API with API key authentication
- Usage plan + API key for rate limiting (500 req/sec steady, 1000 burst)
- Lambda functions: query_handler, admin
- API Gateway routes + Lambda proxy integrations
- CORS configuration for frontend origin

---

## Data Flow: End-to-End Ingestion Example

```
1. IT Admin submits form: { employeeId: "emp_123", email: "jane@corp.com", ... }
2. POST /twins → Lambda: admin → DynamoDB PutItem (status: "ingesting")
3. Lambda: admin → invoke Lambda: email_fetcher async
4. email_fetcher → Google Workspace API → fetch 4,821 emails in batches
5. email_fetcher → S3 PutObject × 49 (100 emails/batch → 49 batches)
6. Each S3 PutObject → S3 Event → SQS ParseQueue (49 messages)
7. Lambda: parser (10 messages/batch) → ~5 invocations
8. Each invocation → thread reconstruction → SQS CleanQueue messages
9. Lambda: cleaner → PII detection + noise filter
10. Surviving threads → SQS EmbedQueue
11. Lambda: embedder → Nova Embeddings → chunked + embedded → S3 Vectors
12. embedder → DynamoDB UpdateItem: { status: "active", chunk_count: 2,341 }
13. Admin dashboard polls GET /twins/emp_123 → sees "active"
```

---

## Frontend Component Design

```
frontend/src/
├── pages/
│   ├── AdminDashboard.tsx     # Twin list table + offboarding form
│   ├── TwinDetail.tsx         # Twin stats, access control, delete
│   └── QueryInterface.tsx     # Chat-style query UI with citations
│
├── components/
│   ├── TwinStatusBadge.tsx    # Color-coded status pill
│   ├── SourceCitation.tsx     # Expandable citation card
│   ├── StalenessWarning.tsx   # Orange banner for old sources
│   ├── ConfidenceBar.tsx      # Visual confidence score
│   └── AccessControlList.tsx  # User-role management table
│
├── hooks/
│   ├── useTwins.ts            # Query + mutation hooks for twin API
│   ├── useQuery.ts            # RAG query hook
│   └── useIngestionStatus.ts  # Polling hook for status updates
│
└── api/
    ├── client.ts              # Axios wrapper with x-api-key + x-user-id headers
    ├── twins.ts               # API client for /twins endpoints
    └── query.ts               # API client for /query endpoints
```

### Frontend Auth Pattern (API Key)

The frontend sends `x-api-key` and `x-user-id` headers on every request:

```typescript
// api/client.ts
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  headers: {
    "x-api-key": getApiKey(),
    "x-user-id": getUserId(),
  },
});
```

---

## Error Handling Strategy

| Layer | Error | Handling |
|---|---|---|
| email_fetcher | Provider API rate limit | Exponential backoff, max 5 retries |
| email_fetcher | Auth token expired | Refresh token, retry once |
| parser | Malformed .mbox file | Skip batch, log to audit table, continue |
| cleaner | Comprehend API error | Skip PII detection, flag as `pii_unverified`, continue |
| embedder | Nova Embeddings API error | Retry 3x with backoff, then DLQ |
| embedder | S3 Vectors put_vectors error | Retry 3x with backoff, then DLQ |
| query_handler | S3 Vectors unavailable | Return 503 with `SEARCH_UNAVAILABLE` |
| query_handler | Bedrock timeout | Return 504 with `GENERATION_TIMEOUT` |
| query_handler | Access denied | Return 403 with `ACCESS_DENIED` |

---

## Security Design

- **Encryption in transit**: All service-to-service calls use TLS 1.2+
- **Encryption at rest**: KMS CMK for S3, DynamoDB, S3 Vectors
- **No VPC required**: S3 Vectors accessed via AWS API
- **Secret rotation**: Secrets Manager auto-rotation for provider credentials every 90 days
- **PII handling**: Comprehend redacts before indexing; raw archives deleted after configurable period
- **Audit log immutability**: Audit DynamoDB table has no delete permissions on Lambda IAM roles
- **API authentication**: API Gateway API key required on all endpoints; `x-user-id` header for user identification
- **Access control**: KKAccess table checked on every query for twin-level authorization
