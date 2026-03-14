# KnowledgeKeeper

An open-source, self-hosted platform that transforms departing employees' email archives into persistent, queryable AI-powered knowledge bases — **digital twins**. Triggered by IT Admins during standard employee offboarding, it preserves institutional knowledge that would otherwise be lost.

## How It Works

1. IT Admin triggers offboarding for a departing employee
2. System ingests their email archive (Google Workspace or direct .mbox upload)
3. Emails are parsed into threads, cleaned, PII-redacted, chunked, and embedded
4. A digital twin is created — a queryable knowledge profile
5. Authorized colleagues ask natural language questions and get cited, grounded answers

## Architecture

Fully serverless on AWS. Two independent layers sharing a storage tier:

- **Ingestion Pipeline** — S3 events → SQS → Lambda chain (parser → cleaner → embedder)
- **Query Layer** — API Gateway → Lambda (embed query → S3 Vectors search → Nova Pro RAG)
- **Storage** — S3 (raw archives), S3 Vectors (embeddings), DynamoDB (metadata, access, audit)

All AI calls go through Amazon Bedrock (Nova Multimodal Embeddings + Nova Pro). No external API calls. Data never leaves your AWS account.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Compute | AWS Lambda (Python 3.12) |
| Embeddings | Amazon Nova Multimodal Embeddings (1024-dim, cosine) |
| Generation | Amazon Nova Pro via Bedrock Converse API |
| Vector Store | Amazon S3 Vectors |
| Metadata | Amazon DynamoDB |
| PII Detection | Amazon Comprehend |
| API | Amazon API Gateway (REST, API key auth) |
| IaC | AWS CDK (Python) |
| Frontend | React 18 + TypeScript + Vite + TailwindCSS |

## Project Structure

```
knowledgekeeper/
├── infrastructure/         # AWS CDK stacks (Python)
│   ├── app.py              # CDK app entry point
│   ├── cdk.json            # Environment config
│   └── stacks/             # KKStorageStack, KKIngestionStack, KKQueryStack
├── lambdas/                # Lambda function code
│   ├── shared/             # Shared layer (models, bedrock, dynamo, s3vectors)
│   ├── ingestion/          # trigger, email_fetcher, parser, cleaner, embedder
│   └── query/              # query_handler, admin
├── frontend/               # React 18 + TypeScript
├── tests/                  # Integration tests and fixtures
└── docs/                   # Deployment guide, API reference
```

## Prerequisites

- Python 3.12+
- Node.js 18+ (for CDK CLI and frontend)
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`)

## Quick Start

```bash
# Clone and set up Python environment
git clone https://github.com/your-org/knowledgekeeper.git
cd knowledgekeeper
python3 -m venv .venv
source .venv/bin/activate
pip install -r infrastructure/requirements.txt

# Bootstrap CDK (first time only)
cd infrastructure
cdk bootstrap

# Deploy all stacks
cdk deploy --all

# Run tests
cd ..
pip install pytest moto pydantic boto3
pytest lambdas/shared/tests/ -v
```

## Security

- All data encrypted at rest (KMS CMK) and in transit (TLS 1.2+)
- One IAM role per Lambda function (least privilege)
- PII detection and redaction before any content reaches the vector store
- API key authentication on all endpoints
- Audit trail for every query and admin action
- No public S3 buckets, no hardcoded credentials

## License

MIT
