# KnowledgeKeeper API Reference

## Overview

The KnowledgeKeeper API is a REST API served through Amazon API Gateway. All endpoints require API key authentication and return a consistent JSON response envelope.

**Base URL**: `https://{api-id}.execute-api.{region}.amazonaws.com/prod`

---

## Authentication

Every request must include two headers:

| Header | Required | Description |
|---|---|---|
| `x-api-key` | Yes | API Gateway API key. Retrieve from the CDK stack outputs after deployment. |
| `x-user-id` | Yes | Identifier of the calling user. Used for twin-level access control lookups in the KKAccess table. |

API keys are managed via API Gateway usage plans. Rate limits: 500 requests/sec steady-state, 1000 requests/sec burst.

---

## Response Envelope

All responses use a consistent envelope:

**Success**:
```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "requestId": "uuid"
}
```

**Error**:
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": {}
  },
  "requestId": "uuid"
}
```

---

## Error Codes

| Code | HTTP Status | Description |
|---|---|---|
| `VALIDATION_ERROR` | 400 | Missing or invalid required fields |
| `INVALID_JSON` | 400 | Request body is not valid JSON |
| `MISSING_USER_ID` | 400 | `x-user-id` header not provided |
| `MISSING_EMPLOYEE_ID` | 400 | `employeeId` path parameter missing |
| `MISSING_QUERY` | 400 | Request body missing non-empty `query` field |
| `ACCESS_DENIED` | 403 | User not authorized for this twin |
| `TWIN_NOT_FOUND` | 404 | No twin exists for the given employee ID |
| `TWIN_NOT_ACTIVE` | 400 | Twin exists but is not available for querying |
| `TWIN_ALREADY_EXISTS` | 409 | A twin already exists for this employee ID |
| `UNKNOWN_ROUTE` | 400 | No handler matched the request method and path |
| `SEARCH_UNAVAILABLE` | 503 | S3 Vectors service unavailable |
| `GENERATION_TIMEOUT` | 504 | Bedrock generation timed out |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

---

## Endpoints

### POST /twins

Create a new digital twin and start the ingestion process.

**Request Body**:
```json
{
  "employeeId": "emp_123",
  "name": "Jane Smith",
  "email": "jane@corp.com",
  "role": "Senior SRE",
  "department": "Engineering",
  "offboardDate": "2025-06-30",
  "tenureStart": "2020-01-15",
  "provider": "google"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `employeeId` | string | Yes | Unique employee identifier |
| `name` | string | Yes | Employee full name |
| `email` | string | Yes | Employee email address |
| `role` | string | Yes | Job title / role |
| `department` | string | Yes | Department name |
| `offboardDate` | string | Yes | Departure date (ISO 8601: `YYYY-MM-DD`) |
| `tenureStart` | string | No | Employment start date (ISO 8601) |
| `provider` | string | No | Email provider: `"google"` or `"upload"` (default: `"upload"`) |

**Response** (`201 Created`):
```json
{
  "success": true,
  "data": {
    "employeeId": "emp_123",
    "name": "Jane Smith",
    "email": "jane@corp.com",
    "role": "Senior SRE",
    "department": "Engineering",
    "offboardDate": "2025-06-30",
    "status": "ingesting",
    "chunkCount": 0,
    "topicIndex": [],
    "retentionExpiry": "2028-06-29",
    "provider": "google"
  },
  "error": null,
  "requestId": "uuid"
}
```

**Errors**: `VALIDATION_ERROR` (400), `TWIN_ALREADY_EXISTS` (409)

**Example**:
```bash
curl -X POST https://{api-url}/twins \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "x-user-id: admin_user_01" \
  -d '{
    "employeeId": "emp_123",
    "name": "Jane Smith",
    "email": "jane@corp.com",
    "role": "Senior SRE",
    "department": "Engineering",
    "offboardDate": "2025-06-30",
    "provider": "google"
  }'
```

---

### GET /twins

List all digital twins, optionally filtered by status.

**Query Parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `status` | string | No | Filter by twin status: `ingesting`, `processing`, `active`, `expired`, `deleted` |

**Response** (`200 OK`):
```json
{
  "success": true,
  "data": {
    "twins": [
      {
        "employeeId": "emp_123",
        "name": "Jane Smith",
        "status": "active",
        "offboardDate": "2025-06-30",
        "chunkCount": 2341
      }
    ]
  },
  "error": null,
  "requestId": "uuid"
}
```

**Example**:
```bash
curl https://{api-url}/twins?status=active \
  -H "x-api-key: YOUR_API_KEY" \
  -H "x-user-id: admin_user_01"
```

---

### GET /twins/{employeeId}

Get detailed metadata for a single twin.

**Path Parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `employeeId` | string | Yes | The employee ID of the twin |

**Response** (`200 OK`):
```json
{
  "success": true,
  "data": {
    "employeeId": "emp_123",
    "name": "Jane Smith",
    "email": "jane@corp.com",
    "role": "Senior SRE",
    "department": "Engineering",
    "offboardDate": "2025-06-30",
    "status": "active",
    "chunkCount": 2341,
    "topicIndex": [],
    "retentionExpiry": "2028-06-29",
    "provider": "google"
  },
  "error": null,
  "requestId": "uuid"
}
```

**Errors**: `TWIN_NOT_FOUND` (404)

**Example**:
```bash
curl https://{api-url}/twins/emp_123 \
  -H "x-api-key: YOUR_API_KEY" \
  -H "x-user-id: admin_user_01"
```

---

### DELETE /twins/{employeeId}

Delete a twin and all associated data (vectors, DynamoDB records, S3 archives). This is the right-to-erasure endpoint.

**Path Parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `employeeId` | string | Yes | The employee ID of the twin to delete |

**Response** (`200 OK`):
```json
{
  "success": true,
  "data": {
    "employeeId": "emp_123",
    "deletedAt": "2025-07-15T14:30:00+00:00"
  },
  "error": null,
  "requestId": "uuid"
}
```

**Errors**: `TWIN_NOT_FOUND` (404)

**What gets deleted**:
- All chunk embeddings from S3 Vectors
- All raw email archive objects from S3
- Twin record from KKTwins DynamoDB table
- All access records from KKAccess DynamoDB table
- An audit log entry is written to KKAudit

**Example**:
```bash
curl -X DELETE https://{api-url}/twins/emp_123 \
  -H "x-api-key: YOUR_API_KEY" \
  -H "x-user-id: admin_user_01"
```

---

### POST /twins/{employeeId}/query

Submit a natural language query against a twin's knowledge base. Requires the calling user to have an access record in the KKAccess table for this twin.

**Path Parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `employeeId` | string | Yes | The employee ID of the twin to query |

**Request Body**:
```json
{
  "query": "What was the root cause of the Kafka lag issue in March?"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | Yes | Natural language question (non-empty) |

**Response** (`200 OK`):
```json
{
  "success": true,
  "data": {
    "answer": "According to Jane's emails, the root cause was consumer group rebalancing triggered by a deployment on March 12th. [chunk_042 | 2023-03-15]",
    "sources": [
      {
        "chunkId": "chunk_042",
        "date": "2023-03-15",
        "subject": "Re: Kafka lag issue",
        "contentPreview": "The root cause is the consumer group rebalancing...",
        "distance": 0.1234
      }
    ],
    "confidence": 0.8766,
    "staleness_warning": null
  },
  "error": null,
  "requestId": "uuid"
}
```

**Response Fields**:

| Field | Type | Description |
|---|---|---|
| `answer` | string | Generated answer with inline source citations |
| `sources` | array | List of source chunks used to generate the answer |
| `sources[].chunkId` | string | Unique chunk identifier |
| `sources[].date` | string | Date of the source email (ISO 8601) |
| `sources[].subject` | string | Email thread subject line |
| `sources[].contentPreview` | string | First 200 characters of the chunk text |
| `sources[].distance` | number | Cosine distance from query (lower = more relevant) |
| `confidence` | number | Average cosine similarity of returned chunks (0.0 – 1.0) |
| `staleness_warning` | string or null | Warning message if newest source is older than 18 months |

**Errors**: `ACCESS_DENIED` (403), `TWIN_NOT_ACTIVE` (400), `MISSING_QUERY` (400), `MISSING_USER_ID` (400)

**Example**:
```bash
curl -X POST https://{api-url}/twins/emp_123/query \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "x-user-id: manager_user_42" \
  -d '{"query": "What was the root cause of the Kafka lag issue in March?"}'
```

---

### POST /twins/{employeeId}/access

Grant a user access to query a specific twin.

**Path Parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `employeeId` | string | Yes | The employee ID of the twin |

**Request Body**:
```json
{
  "userId": "manager_user_42",
  "role": "viewer"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `userId` | string | Yes | The user ID to grant access to |
| `role` | string | No | Access role: `"admin"` or `"viewer"` (default: `"viewer"`) |

**Response** (`200 OK`):
```json
{
  "success": true,
  "data": {
    "userId": "manager_user_42",
    "employeeId": "emp_123",
    "role": "viewer"
  },
  "error": null,
  "requestId": "uuid"
}
```

**Errors**: `VALIDATION_ERROR` (400), `TWIN_NOT_FOUND` (404)

**Example**:
```bash
curl -X POST https://{api-url}/twins/emp_123/access \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "x-user-id: admin_user_01" \
  -d '{"userId": "manager_user_42", "role": "viewer"}'
```

---

### DELETE /twins/{employeeId}/access/{userId}

Revoke a user's access to a twin.

**Path Parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `employeeId` | string | Yes | The employee ID of the twin |
| `userId` | string | Yes | The user ID whose access to revoke |

**Response** (`200 OK`):
```json
{
  "success": true,
  "data": {
    "employeeId": "emp_123",
    "userId": "manager_user_42"
  },
  "error": null,
  "requestId": "uuid"
}
```

**Example**:
```bash
curl -X DELETE https://{api-url}/twins/emp_123/access/manager_user_42 \
  -H "x-api-key: YOUR_API_KEY" \
  -H "x-user-id: admin_user_01"
```
