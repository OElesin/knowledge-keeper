---
inclusion: always
---

# KnowledgeKeeper — Technology Stack (MVP)

## Cloud Platform

- **AWS** — all infrastructure; nothing runs outside AWS
- **Region**: Deployable to any AWS region; default `us-east-1`
- **Account isolation**: All data stays within the customer's own AWS account

## Compute

- **AWS Lambda** — all application logic; no EC2, no ECS, no containers at runtime
- **Runtime**: Python 3.12 for all Lambda functions
- **Packaging**: Lambda layers for shared dependencies (boto3, pydantic, etc.)
- **Timeouts**: Ingestion Lambdas up to 15 min; Query Lambdas up to 30 sec

## Storage

- **Amazon S3** — raw email archive drop zone (.mbox / .eml)
- **Amazon S3 Vectors** — vector store for embeddings (cosine similarity search); fully serverless, no VPC required, up to 90% cheaper than OpenSearch Serverless
  - Vector bucket: `kk-{env}`, index: `kk-{env}-chunks`
  - Dimension: 1024, distance metric: cosine, data type: float32
  - boto3 client: `s3vectors` with `put_vectors()` / `query_vectors()` / `delete_vectors()`
  - CDK: L1 constructs `CfnVectorBucket` and `CfnVectorIndex` from `aws_cdk.aws_s3vectors`
- **Amazon DynamoDB** — twin metadata, user access control table, audit trail
- **S3 lifecycle policies** — auto-expire raw archives after configurable retention period

## Messaging & Orchestration

- **Amazon SQS** — decouples email parsing from embedding pipeline; handles large archive bursts
- **Dead Letter Queues (DLQ)** — on all SQS queues for failed message handling
- **S3 Event Notifications** — trigger ingestion Lambda on archive upload

## AI / ML

- **Amazon Bedrock** — all LLM and embedding calls; no external AI API calls
  - **Embeddings**: Amazon Nova Multimodal Embeddings (`amazon.nova-2-multimodal-embeddings-v1:0`)
    - 1024-dim, cosine, float32
    - Uses `taskType: "SINGLE_EMBEDDING"` with `singleEmbeddingParams`
    - `embeddingPurpose: "GENERIC_INDEX"` for indexing, `"GENERIC_RETRIEVAL"` for querying
    - Text input: `text: {"truncationMode": "END", "value": "..."}`
    - Response path: `response_body["embeddings"][0]["embedding"]`
  - **Generation**: Amazon Nova Pro (`amazon.nova-pro-v1:0`) — RAG response generation via Converse API
- **Amazon Comprehend** — PII detection before any chunk reaches the vector store

## API & Auth

- **Amazon API Gateway (REST API)** — REST endpoints for admin operations and query interface
- **API Key authentication** — API Gateway usage plans + API keys for MVP auth; Cognito deferred to v1.1
- **IAM roles** — least-privilege per Lambda function; no shared credentials

## Infrastructure as Code

- **AWS CDK (Python)** — all infrastructure defined as code; no manual console configuration
- **CDK Stacks**: KKStorageStack, KKIngestionStack, KKQueryStack
- **cdk.json** — environment-specific configuration

## Frontend (Admin UI & Query Interface)

- **React 18** with TypeScript
- **Vite** — build tooling
- **TailwindCSS** — styling
- **React Query** — server state management
- **Hosted on S3 + CloudFront** (or local dev server for MVP)

## Email Integrations (MVP)

- **Google Workspace**: Google Workspace Admin SDK (service account with domain-wide delegation)
- **Fallback**: Direct .mbox / .eml file upload to S3
- **Microsoft 365**: Deferred to v1.1

## Testing

- **pytest** — unit and integration tests for all Lambda functions
- **moto** — AWS service mocking for unit tests
- **AWS CDK assertions** — infrastructure unit tests
- **Postman / Bruno** — API integration test collections

## Observability (MVP)

- **AWS CloudWatch** — Lambda logs (basic; dashboards and alarms deferred to v1.1)

## Security

- **AWS KMS** — encryption at rest for S3, DynamoDB; SSE-KMS for S3 Vectors
- **No VPC required** — S3 Vectors is accessed via AWS API, not VPC endpoint
- **AWS Secrets Manager** — store Google OAuth credentials
- **CloudTrail** — all API calls logged for compliance audit
