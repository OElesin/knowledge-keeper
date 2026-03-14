---
inclusion: always
---

# KnowledgeKeeper — Project Structure

## Repository Layout

```
knowledgekeeper/
├── .kiro/
│   ├── steering/           # Kiro steering files (this directory)
│   └── specs/              # Kiro feature specs
│
├── infrastructure/         # AWS CDK (Python)
│   ├── app.py
│   ├── cdk.json
│   └── stacks/
│       ├── storage_stack.py
│       ├── ingestion_stack.py
│       └── query_stack.py
│
├── lambdas/                # All Lambda function code
│   ├── shared/             # Shared utilities (Lambda layer source)
│   │   ├── models.py       # Pydantic data models
│   │   ├── bedrock.py      # Bedrock client wrapper (Nova Embeddings + Nova Pro)
│   │   ├── dynamo.py       # DynamoDB access patterns
│   │   └── s3vectors_client.py  # S3 Vectors put/query/delete wrapper
│   │
│   ├── ingestion/
│   │   ├── trigger/        # Offboarding trigger Lambda
│   │   ├── email_fetcher/  # Google Workspace email fetcher Lambda
│   │   ├── parser/         # Email parser + thread reconstructor Lambda
│   │   ├── cleaner/        # Noise filter + PII detection Lambda
│   │   └── embedder/       # Embedding + S3 Vectors indexer Lambda
│   │
│   └── query/
│       ├── query_handler/  # RAG orchestration Lambda
│       └── admin/          # Admin API Lambda (CRUD on twins)
│
├── frontend/               # React 18 + TypeScript
│   ├── src/
│   │   ├── pages/
│   │   │   ├── AdminDashboard.tsx
│   │   │   ├── TwinDetail.tsx
│   │   │   └── QueryInterface.tsx
│   │   ├── components/
│   │   ├── hooks/
│   │   └── api/            # API client functions
│   └── package.json
│
├── tests/
│   ├── unit/               # pytest unit tests per Lambda
│   ├── integration/        # End-to-end pipeline tests
│   └── fixtures/           # Sample .eml/.mbox test data
│
└── docs/
    ├── deployment.md
    ├── consent-policy-template.md
    └── api-reference.md
```

## Naming Conventions

- **Lambda functions**: `kk-{environment}-{layer}-{function}` e.g. `kk-prod-ingestion-parser`
- **S3 buckets**: `kk-{account-id}-{environment}-{purpose}` e.g. `kk-123456789-prod-raw-archives`
- **DynamoDB tables**: `KK{Environment}{TableName}` e.g. `KKProdTwins`
- **CDK stacks**: `KK{Layer}Stack{Environment}` e.g. `KKIngestionStackProd`
- **Python files**: snake_case; **TypeScript files**: PascalCase for components, camelCase for utilities

## Lambda Function Conventions

Each Lambda function directory contains:
```
{function_name}/
├── handler.py          # Lambda handler (entry point)
├── logic.py            # Business logic (testable, no AWS SDK)
├── requirements.txt    # Function-specific dependencies
└── tests/
    └── test_logic.py   # Unit tests for logic.py
```

- Handlers are thin — they parse events, call logic, return responses
- Business logic in `logic.py` is pure Python — no direct boto3 calls — makes unit testing clean
- AWS SDK calls are in the shared layer or injected as dependencies

## Environment Configuration

- All environment-specific values via Lambda environment variables
- Secrets (API keys, OAuth credentials) via AWS Secrets Manager — never hardcoded
- CDK context (`cdk.json`) for stack-level config (account, region, retention periods)

## Key Data Models (shared/models.py)

```python
class Twin:
    employee_id: str
    name: str
    email: str
    role: str
    department: str
    tenure_start: date
    offboard_date: date
    chunk_count: int
    topic_index: list[str]
    status: Literal["ingesting", "active", "expired", "deleted"]
    retention_expiry: date

class EmailChunk:
    chunk_id: str
    employee_id: str
    thread_id: str
    subject: str
    date: datetime
    author_role: Literal["primary", "cc", "bcc"]
    content: str
    relevance_score: float
    embedding_model: str
    topics: list[str]

class QueryResult:
    answer: str
    sources: list[ChunkReference]
    confidence: float
    staleness_warning: str | None
```
