# KnowledgeKeeper — Deployment Guide

## Prerequisites

Before deploying KnowledgeKeeper, ensure the following tools are installed and configured:

| Tool | Version | Install |
|---|---|---|
| AWS CLI | v2.x | [Install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |
| AWS CDK CLI | v2.200+ | `npm install -g aws-cdk` |
| Python | 3.12 | [python.org](https://www.python.org/downloads/) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) |
| pip | latest | Bundled with Python 3.12 |

Verify installations:

```bash
aws --version
cdk --version
python3 --version
node --version
```

### AWS Credentials

Configure AWS CLI with credentials that have sufficient permissions to create IAM roles, Lambda functions, S3 buckets, DynamoDB tables, API Gateway, SQS queues, and KMS keys:

```bash
aws configure
```

Or export credentials directly:

```bash
export AWS_ACCESS_KEY_ID=<your-access-key>
export AWS_SECRET_ACCESS_KEY=<your-secret-key>
export AWS_DEFAULT_REGION=us-east-1
```

### Amazon Bedrock Model Access

Enable access to the following models in the [Amazon Bedrock console](https://console.aws.amazon.com/bedrock/home#/modelaccess) for your deployment region:

- Amazon Nova Multimodal Embeddings (`amazon.nova-2-multimodal-embeddings-v1:0`)
- Amazon Nova Pro (`amazon.nova-pro-v1:0`)

---

## Step 1: Install Python Dependencies

```bash
cd infrastructure
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Step 2: Bootstrap CDK

CDK bootstrap provisions the resources CDK needs to deploy (S3 staging bucket, IAM roles). Run this once per account/region:

```bash
cdk bootstrap aws://<ACCOUNT_ID>/us-east-1
```

Replace `<ACCOUNT_ID>` with your 12-digit AWS account ID. You can retrieve it with:

```bash
aws sts get-caller-identity --query Account --output text
```

## Step 3: Deploy All Stacks

From the `infrastructure/` directory:

```bash
cdk deploy --all --require-approval broadening
```

This deploys three stacks in dependency order:

1. **KKStorageStackDev** — S3 bucket, S3 Vectors, DynamoDB tables, KMS keys
2. **KKIngestionStackDev** — SQS queues, ingestion Lambda functions, S3 event notifications
3. **KKQueryStackDev** — API Gateway, query and admin Lambda functions

CDK will prompt for approval when IAM policy changes are detected. Review and confirm.

### Deploy a Specific Stack

```bash
cdk deploy KKStorageStackDev
cdk deploy KKIngestionStackDev
cdk deploy KKQueryStackDev
```

---

## Step 4: Post-Deploy Verification

### Retrieve the API URL

The API Gateway URL is in the KKQueryStack outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name KKQueryStackDev \
  --query "Stacks[0].Outputs[?contains(OutputKey,'ApiUrl') || contains(OutputKey,'RestApiEndpoint')].OutputValue" \
  --output text
```

### Retrieve the API Key

1. Get the API key ID from stack outputs:

```bash
API_KEY_ID=$(aws cloudformation describe-stacks \
  --stack-name KKQueryStackDev \
  --query "Stacks[0].Outputs[?contains(OutputKey,'ApiKey')].OutputValue" \
  --output text)
```

2. Get the actual key value:

```bash
aws apigateway get-api-key --api-key "$API_KEY_ID" --include-value \
  --query "value" --output text
```

### Test the API

```bash
API_URL=<your-api-url>
API_KEY=<your-api-key>

curl -s -X GET "${API_URL}/twins" \
  -H "x-api-key: ${API_KEY}" \
  -H "x-user-id: admin" | python3 -m json.tool
```

A successful response returns:

```json
{
  "success": true,
  "data": [],
  "error": null,
  "requestId": "..."
}
```

---

## Step 5: Configure the Frontend

```bash
cd frontend
npm install
cp .env.example .env
```

Edit `.env` with the values from Step 4:

```
VITE_API_URL=<your-api-url>
VITE_API_KEY=<your-api-key>
VITE_USER_ID=admin
```

Start the dev server:

```bash
npm run dev
```

---

## Google Workspace Setup (Optional)

If using Google Workspace as the email provider:

1. Create a Google Cloud service account with domain-wide delegation
2. Enable the Gmail API and Admin SDK API
3. Store the service account JSON credentials in Secrets Manager:

```bash
aws secretsmanager create-secret \
  --name "kk/dev/google-workspace-creds" \
  --secret-string file://service-account-key.json
```

---

## Useful Commands

| Command | Description |
|---|---|
| `cdk synth` | Emit the synthesized CloudFormation templates |
| `cdk diff` | Compare deployed stack with current state |
| `cdk deploy --all` | Deploy all stacks |
| `cdk destroy --all` | Tear down all stacks |
| `cdk ls` | List all stacks in the app |

---

## Troubleshooting

**CDK bootstrap fails**: Ensure your AWS credentials have `cloudformation:*`, `s3:*`, `iam:*`, and `ssm:*` permissions.

**Bedrock InvokeModel returns AccessDeniedException**: Verify model access is enabled in the Bedrock console for your region.

**S3 Vectors API errors**: Confirm S3 Vectors is available in your deployment region. Check [AWS regional availability](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-regions.html).

**API Gateway returns 403 Forbidden**: Verify the `x-api-key` header value matches the deployed API key.
