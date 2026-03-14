---
inclusion: always
---

# KnowledgeKeeper — Security Policies

## Foundational Principles

KnowledgeKeeper processes sensitive employee communications. Security is not a feature — it is a precondition. Every implementation decision must be evaluated against these principles:

1. **Data minimization**: Only ingest what is necessary. Exclude Trash, Spam, and optionally configurable folder exclusions.
2. **Least privilege**: Every Lambda has its own IAM role with only the permissions it needs. No shared roles.
3. **Defence in depth**: Encryption at rest + in transit + network isolation. No single control is relied upon alone.
4. **Audit everything**: Every admin action, every query, every deletion is logged immutably.

## IAM Rules

- **Never use broad policies** (`s3:*`, `dynamodb:*`). Always specify exact actions.
- **Resource-level conditions**: S3 and DynamoDB policies must be scoped to specific resource ARNs, not `*`.
- **No inline policies in CDK**: Use managed policies attached to roles for auditability.
- **No Lambda execution roles shared across functions**: One role per function.

Example of correct Lambda IAM pattern:
```python
# CDK
embedder_role = iam.Role(self, "EmbedderRole",
    assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
)
embedder_role.add_to_policy(iam.PolicyStatement(
    actions=["bedrock:InvokeModel"],
    resources=[f"arn:aws:bedrock:{region}::foundation-model/amazon.nova-2-multimodal-embeddings-v1:0"]
))
embedder_role.add_to_policy(iam.PolicyStatement(
    actions=["s3vectors:PutVectors"],
    resources=[f"arn:aws:s3vectors:{region}:{account}:vector-bucket/kk-{env}/*"]
))
```

## Secrets Management

- **Never hardcode credentials**: All API keys, OAuth credentials, and client secrets go to Secrets Manager.
- **Never use environment variables for secrets**: Use Secrets Manager SDK calls at runtime.
- **Secret naming**: `kk/{environment}/{secret-name}` e.g. `kk/prod/google-workspace-creds`
- **Rotation**: Configure Secrets Manager auto-rotation for all provider credentials (90-day cycle).

## PII Handling

- Amazon Comprehend PII detection runs on EVERY chunk before it reaches S3 Vectors.
- Detected PII types to redact: `SSN`, `CREDIT_DEBIT_NUMBER`, `PHONE`, `BANK_ACCOUNT_NUMBER`, `PIN`.
- Email addresses and names are NOT redacted (they are the primary metadata).
- Chunks flagged `pii_unverified` (Comprehend call failed) are indexed but tagged — query responses for such chunks include a warning.
- Raw email archives are deleted from S3 after configurable period (default 30 days post-ingestion completion).

## Network Security

- S3 Vectors is accessed via AWS API — no VPC required.
- S3, DynamoDB, Bedrock accessed via standard AWS endpoints.
- API Gateway is public-facing with API key authentication.

## Encryption

- All S3 buckets: SSE-KMS with customer-managed CMK.
- All DynamoDB tables: KMS encryption with customer-managed CMK.
- S3 Vectors: SSE-KMS encryption.
- KMS key rotation: annual auto-rotation enabled on all CMKs.

## Authentication & Authorization

- All API endpoints require a valid API key (`x-api-key` header) — no exceptions.
- API keys managed via API Gateway usage plans with throttle limits.
- User identification: `x-user-id` header on every request; used for access control lookups.
- Twin-level authorization: after API key validation, check KKAccess table for `{userId, employeeId}` record. If absent → 403.
- Admin endpoints (POST/DELETE /twins, access management): require `admin` role in KKAccess table.
- Cognito JWT authentication deferred to v1.1.

## What Kiro Must Never Generate

- Code that logs full email content to CloudWatch logs
- Code that prints or returns API credentials or secret values
- Hardcoded AWS account IDs, region names, or ARNs in application code (use environment variables or CDK tokens)
- S3 buckets with public access enabled
- DynamoDB tables without encryption
- Lambda functions without explicit IAM roles (never use default Lambda execution role)
- Any code that calls a non-AWS AI API (OpenAI, Cohere, etc.) — Bedrock only
