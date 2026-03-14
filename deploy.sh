#!/usr/bin/env bash
#
# KnowledgeKeeper — Full deployment script
#
# Deploys the CDK infrastructure (storage, ingestion, query, frontend)
# and builds the React frontend before the frontend stack deploys it to S3/CloudFront.
#
# Usage:
#   ./deploy.sh              # Deploy everything (default: dev environment)
#   ./deploy.sh --env prod   # Deploy to a specific environment
#   ./deploy.sh --skip-fe    # Deploy backend stacks only, skip frontend build & stack
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="dev"
SKIP_FRONTEND=false

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)
            ENV_NAME="$2"
            shift 2
            ;;
        --skip-fe)
            SKIP_FRONTEND=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./deploy.sh [--env <environment>] [--skip-fe]"
            exit 1
            ;;
    esac
done

SUFFIX="$(echo "${ENV_NAME:0:1}" | tr '[:lower:]' '[:upper:]')${ENV_NAME:1}"

echo "==> Deploying KnowledgeKeeper (env: ${ENV_NAME})"
echo ""

# --- Preflight checks ---
echo "==> Checking prerequisites..."
for cmd in aws cdk python3 node npm; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: '$cmd' is not installed. See docs/deployment.md for prerequisites."
        exit 1
    fi
done
echo "    All tools found."
echo ""

# --- Python dependencies ---
echo "==> Installing CDK Python dependencies..."
cd "${SCRIPT_DIR}/infrastructure"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
echo ""

# --- CDK synth (validate templates) ---
echo "==> Synthesizing CloudFormation templates..."
cdk synth -c env="${ENV_NAME}" --quiet
echo ""

# --- Deploy backend stacks ---
echo "==> Deploying backend stacks..."
cdk deploy \
    "KKStorageStack${SUFFIX}" \
    "KKIngestionStack${SUFFIX}" \
    "KKQueryStack${SUFFIX}" \
    -c env="${ENV_NAME}" \
    --require-approval broadening
echo ""

# --- Retrieve API URL for frontend .env ---
echo "==> Retrieving API URL from stack outputs..."
API_URL=$(aws cloudformation describe-stacks \
    --stack-name "KKQueryStack${SUFFIX}" \
    --query "Stacks[0].Outputs[?contains(OutputKey,'ApiUrl') || contains(OutputKey,'RestApiEndpoint')].OutputValue" \
    --output text 2>/dev/null || echo "")

API_KEY_ID=$(aws cloudformation describe-stacks \
    --stack-name "KKQueryStack${SUFFIX}" \
    --query "Stacks[0].Outputs[?contains(OutputKey,'ApiKey')].OutputValue" \
    --output text 2>/dev/null || echo "")

if [ -n "$API_KEY_ID" ]; then
    API_KEY=$(aws apigateway get-api-key \
        --api-key "$API_KEY_ID" \
        --include-value \
        --query "value" \
        --output text 2>/dev/null || echo "")
else
    API_KEY=""
fi

if [ -z "$API_URL" ]; then
    echo "WARNING: Could not retrieve API URL from stack outputs."
else
    echo "    API URL: ${API_URL}"
fi
echo ""

if [ "$SKIP_FRONTEND" = true ]; then
    echo "==> Skipping frontend (--skip-fe flag set)"
    echo ""
    echo "==> Done. Backend deployed successfully."
    exit 0
fi

# --- Build frontend ---
echo "==> Building frontend..."
cd "${SCRIPT_DIR}/frontend"
npm ci --silent

# Write .env with the deployed API URL
cat > .env <<EOF
VITE_API_URL=${API_URL}
VITE_API_KEY=${API_KEY}
VITE_USER_ID=admin
EOF
echo "    Wrote frontend/.env with API URL"

npm run build
echo "    Frontend built to frontend/dist/"
echo ""

# --- Deploy frontend stack ---
echo "==> Deploying frontend stack..."
cd "${SCRIPT_DIR}/infrastructure"
source .venv/bin/activate
cdk deploy "KKFrontendStack${SUFFIX}" \
    -c env="${ENV_NAME}" \
    --require-approval never
echo ""

# --- Print outputs ---
FRONTEND_URL=$(aws cloudformation describe-stacks \
    --stack-name "KKFrontendStack${SUFFIX}" \
    --query "Stacks[0].Outputs[?contains(OutputKey,'FrontendUrl')].OutputValue" \
    --output text 2>/dev/null || echo "(not available)")

echo "============================================"
echo "  KnowledgeKeeper deployed successfully"
echo "============================================"
echo ""
echo "  Environment:  ${ENV_NAME}"
echo "  API URL:      ${API_URL:-N/A}"
echo "  Frontend URL: ${FRONTEND_URL}"
echo ""
echo "  Retrieve your API key:"
echo "    aws apigateway get-api-key --api-key ${API_KEY_ID:-<key-id>} --include-value --query value --output text"
echo ""
