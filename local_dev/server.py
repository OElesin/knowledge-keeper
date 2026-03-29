"""Local mock API server for KnowledgeKeeper frontend development.

Implements the same REST API as the real Lambda-backed API Gateway,
but with in-memory data and fake RAG responses. No AWS credentials needed.

Usage:
    pip install -r local_dev/requirements.txt
    python local_dev/server.py
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# In-memory data stores
# ---------------------------------------------------------------------------

TWINS: dict[str, dict] = {}
ACCESS: dict[str, dict] = {}  # key = "{userId}:{employeeId}"
AUDIT: list[dict] = []
DIRECTORY_CONFIG: dict = {"provider": None, "credentials_configured": False}
DIRECTORY_CREDENTIALS: dict = {}  # stored credentials (never returned in responses)

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SEED_TWINS = [
    {
        "employeeId": "emp_001",
        "name": "Jane Chen",
        "email": "jane.chen@example.com",
        "role": "Senior SRE",
        "department": "Platform Engineering",
        "tenureStart": "2019-03-15",
        "offboardDate": "2025-01-31",
        "chunkCount": 1247,
        "topicIndex": ["Kafka", "Kubernetes", "incident response", "monitoring"],
        "status": "active",
        "retentionExpiry": "2028-01-31",
        "provider": "google",
    },
    {
        "employeeId": "emp_002",
        "name": "Marcus Rivera",
        "email": "marcus.r@example.com",
        "role": "Engineering Manager",
        "department": "Backend Services",
        "tenureStart": "2017-06-01",
        "offboardDate": "2025-02-15",
        "chunkCount": 2034,
        "topicIndex": ["architecture", "hiring", "sprint planning", "AWS migration"],
        "status": "active",
        "retentionExpiry": "2028-02-15",
        "provider": "google",
    },
    {
        "employeeId": "emp_003",
        "name": "Priya Sharma",
        "email": "priya.s@example.com",
        "role": "Data Engineer",
        "department": "Data Platform",
        "tenureStart": "2021-09-01",
        "offboardDate": "2025-03-01",
        "chunkCount": 0,
        "topicIndex": [],
        "status": "ingesting",
        "retentionExpiry": "2028-03-01",
        "provider": "microsoft",
    },
]

SEED_ACCESS = [
    {"userId": "local-dev-user", "employeeId": "emp_001", "role": "admin"},
    {"userId": "local-dev-user", "employeeId": "emp_002", "role": "viewer"},
    {"userId": "local-dev-user", "employeeId": "emp_003", "role": "admin"},
]

# Fake chunks used for mock query responses
FAKE_CHUNKS = {
    "emp_001": [
        {
            "key": "chunk_j001",
            "date": "2024-11-12",
            "subject": "Re: Kafka consumer lag spike",
            "content": "The root cause was the consumer group rebalancing triggered by the deployment. We need to set cooperative-sticky assignor to avoid stop-the-world rebalances.",
            "distance": 0.15,
        },
        {
            "key": "chunk_j002",
            "date": "2024-10-03",
            "subject": "Monitoring stack migration plan",
            "content": "I recommend we move from Prometheus to Amazon Managed Prometheus. The main benefit is we drop the operational burden of running Thanos for long-term storage.",
            "distance": 0.22,
        },
        {
            "key": "chunk_j003",
            "date": "2024-08-19",
            "subject": "Re: Incident postmortem - checkout outage",
            "content": "The circuit breaker on the payment gateway was misconfigured with a 30s timeout instead of 5s. I've updated the runbook with the correct values.",
            "distance": 0.28,
        },
    ],
    "emp_002": [
        {
            "key": "chunk_m001",
            "date": "2024-12-01",
            "subject": "Q1 hiring plan",
            "content": "We need two senior backend engineers and one staff engineer for the API platform team. Budget approved by VP Eng last week.",
            "distance": 0.12,
        },
        {
            "key": "chunk_m002",
            "date": "2024-09-15",
            "subject": "Re: AWS migration timeline",
            "content": "Phase 2 of the migration moves the order service and inventory service to ECS Fargate. Target completion is end of Q1. The database cutover is the riskiest part.",
            "distance": 0.19,
        },
    ],
}

FAKE_ANSWERS = {
    "emp_001": (
        "Based on Jane's communications, the Kafka consumer lag spike in November 2024 "
        "was caused by consumer group rebalancing during a deployment [chunk_j001 | 2024-11-12]. "
        "She recommended switching to the cooperative-sticky partition assignor to prevent "
        "stop-the-world rebalances. She also documented circuit breaker configuration issues "
        "in the checkout outage postmortem [chunk_j003 | 2024-08-19]."
    ),
    "emp_002": (
        "According to Marcus's emails, the AWS migration Phase 2 targets the order service "
        "and inventory service, moving them to ECS Fargate [chunk_m002 | 2024-09-15]. "
        "He identified the database cutover as the highest-risk component. Target completion "
        "was end of Q1."
    ),
}


def _seed():
    """Populate in-memory stores with sample data."""
    for t in SEED_TWINS:
        TWINS[t["employeeId"]] = dict(t)
    for a in SEED_ACCESS:
        key = f"{a['userId']}:{a['employeeId']}"
        ACCESS[key] = dict(a)


_seed()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(data=None, error=None, status_code=200):
    request_id = str(uuid.uuid4())
    body = {
        "success": error is None,
        "data": data,
        "error": error,
        "requestId": request_id,
    }
    return jsonify(body), status_code


def _get_user_id():
    return request.headers.get("x-user-id", "local-dev-user")



# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@app.route("/twins", methods=["POST"])
def create_twin():
    body = request.get_json(silent=True) or {}
    required = ("employeeId", "name", "email", "role", "department", "offboardDate")
    missing = [f for f in required if not body.get(f)]
    if missing:
        return _envelope(
            error={"code": "VALIDATION_ERROR", "message": f"Missing required fields: {', '.join(missing)}", "details": {"missing": missing}},
            status_code=400,
        )

    eid = body["employeeId"]
    if eid in TWINS:
        return _envelope(
            error={"code": "TWIN_ALREADY_EXISTS", "message": f"Twin already exists for employee {eid}", "details": {}},
            status_code=409,
        )

    try:
        offboard_dt = date.fromisoformat(body["offboardDate"])
    except (ValueError, TypeError):
        return _envelope(
            error={"code": "VALIDATION_ERROR", "message": "offboardDate must be a valid ISO date (YYYY-MM-DD)", "details": {}},
            status_code=400,
        )

    provider = body.get("provider", "upload")
    if provider not in ("google", "upload", "microsoft"):
        return _envelope(
            error={"code": "VALIDATION_ERROR", "message": f"Invalid provider '{provider}'", "details": {}},
            status_code=400,
        )

    retention_expiry = offboard_dt + timedelta(days=3 * 365)
    item = {
        "employeeId": eid,
        "name": body["name"],
        "email": body["email"],
        "role": body["role"],
        "department": body["department"],
        "offboardDate": body["offboardDate"],
        "status": "ingesting",
        "chunkCount": 0,
        "topicIndex": [],
        "retentionExpiry": retention_expiry.isoformat(),
        "provider": provider,
    }
    if body.get("tenureStart"):
        item["tenureStart"] = body["tenureStart"]

    TWINS[eid] = item

    # Auto-grant admin access to the creating user
    uid = _get_user_id()
    ACCESS[f"{uid}:{eid}"] = {"userId": uid, "employeeId": eid, "role": "admin"}

    return _envelope(data=item, status_code=201)


@app.route("/twins", methods=["GET"])
def list_twins():
    status_filter = request.args.get("status")
    items = list(TWINS.values())
    if status_filter:
        items = [t for t in items if t["status"] == status_filter]
    return _envelope(data={"twins": items})


@app.route("/twins/<employee_id>", methods=["GET"])
def get_twin(employee_id):
    twin = TWINS.get(employee_id)
    if twin is None:
        return _envelope(
            error={"code": "TWIN_NOT_FOUND", "message": f"No twin found for employee {employee_id}", "details": {}},
            status_code=404,
        )
    return _envelope(data=twin)


@app.route("/twins/<employee_id>", methods=["DELETE"])
def delete_twin(employee_id):
    twin = TWINS.pop(employee_id, None)
    if twin is None:
        return _envelope(
            error={"code": "TWIN_NOT_FOUND", "message": f"No twin found for employee {employee_id}", "details": {}},
            status_code=404,
        )
    # Remove associated access records
    to_remove = [k for k in ACCESS if k.endswith(f":{employee_id}")]
    for k in to_remove:
        del ACCESS[k]
    now = datetime.now(timezone.utc).isoformat()
    return _envelope(data={"employeeId": employee_id, "deletedAt": now})


# ---------------------------------------------------------------------------
# Access management routes
# ---------------------------------------------------------------------------


@app.route("/twins/<employee_id>/access", methods=["GET"])
def list_access(employee_id):
    if employee_id not in TWINS:
        return _envelope(
            error={"code": "TWIN_NOT_FOUND", "message": f"No twin found for employee {employee_id}", "details": {}},
            status_code=404,
        )
    records = [v for k, v in ACCESS.items() if k.endswith(f":{employee_id}")]
    return _envelope(data=records)


@app.route("/twins/<employee_id>/access", methods=["POST"])
def grant_access(employee_id):
    if employee_id not in TWINS:
        return _envelope(
            error={"code": "TWIN_NOT_FOUND", "message": f"No twin found for employee {employee_id}", "details": {}},
            status_code=404,
        )
    body = request.get_json(silent=True) or {}
    uid = (body.get("userId") or "").strip()
    role = (body.get("role") or "viewer").strip()
    if not uid:
        return _envelope(
            error={"code": "VALIDATION_ERROR", "message": "userId is required", "details": {}},
            status_code=400,
        )
    if role not in ("admin", "viewer"):
        return _envelope(
            error={"code": "VALIDATION_ERROR", "message": "role must be 'admin' or 'viewer'", "details": {}},
            status_code=400,
        )
    record = {"userId": uid, "employeeId": employee_id, "role": role}
    ACCESS[f"{uid}:{employee_id}"] = record
    return _envelope(data=record)


@app.route("/twins/<employee_id>/access/<user_id>", methods=["DELETE"])
def revoke_access(employee_id, user_id):
    key = f"{user_id}:{employee_id}"
    ACCESS.pop(key, None)
    return _envelope(data={"employeeId": employee_id, "userId": user_id})


# ---------------------------------------------------------------------------
# Query route (mock RAG)
# ---------------------------------------------------------------------------


@app.route("/twins/<employee_id>/query", methods=["POST"])
def query_twin(employee_id):
    uid = _get_user_id()

    # Access check
    access_key = f"{uid}:{employee_id}"
    if access_key not in ACCESS:
        return _envelope(
            error={"code": "ACCESS_DENIED", "message": "Not authorized", "details": {}},
            status_code=403,
        )

    twin = TWINS.get(employee_id)
    if twin is None:
        return _envelope(
            error={"code": "ACCESS_DENIED", "message": "Not authorized", "details": {}},
            status_code=403,
        )
    if twin.get("status") != "active":
        return _envelope(
            error={
                "code": "TWIN_NOT_ACTIVE",
                "message": f"Twin is not available for querying (status: {twin.get('status')})",
                "details": {"status": twin.get("status", "unknown")},
            },
            status_code=400,
        )

    body = request.get_json(silent=True) or {}
    query_text = (body.get("query") or "").strip()
    if not query_text:
        return _envelope(
            error={"code": "VALIDATION_ERROR", "message": "query is required", "details": {}},
            status_code=400,
        )

    # Return mock RAG response
    chunks = FAKE_CHUNKS.get(employee_id, [])
    sources = [
        {
            "chunkId": c["key"],
            "date": c["date"],
            "subject": c["subject"],
            "contentPreview": c["content"][:200],
            "distance": c["distance"],
        }
        for c in chunks
    ]

    answer = FAKE_ANSWERS.get(
        employee_id,
        f"I don't have enough information about that in {twin['name']}'s knowledge base.",
    )

    confidence = round(random.uniform(0.72, 0.95), 4) if chunks else 0.0
    staleness = None if chunks else "No source data available."

    return _envelope(data={
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
        "staleness_warning": staleness,
    })


# ---------------------------------------------------------------------------
# Ingestion status route (used by useIngestionStatus hook)
# ---------------------------------------------------------------------------


@app.route("/ingestion/status/<employee_id>", methods=["GET"])
def ingestion_status(employee_id):
    twin = TWINS.get(employee_id)
    if twin is None:
        return _envelope(
            error={"code": "TWIN_NOT_FOUND", "message": f"No twin found for employee {employee_id}", "details": {}},
            status_code=404,
        )
    return _envelope(data={
        "employeeId": employee_id,
        "status": twin["status"],
        "chunkCount": twin.get("chunkCount", 0),
        "topicIndex": twin.get("topicIndex", []),
    })


# ---------------------------------------------------------------------------
# Directory configuration routes
# ---------------------------------------------------------------------------

VALID_DIRECTORY_PROVIDERS = {"microsoft", "google", "ldap"}

MICROSOFT_REQUIRED_FIELDS = ("tenant_id", "client_id", "client_secret")
GOOGLE_REQUIRED_FIELDS = ("service_account_key",)
LDAP_REQUIRED_FIELDS = ("server_url", "bind_dn", "bind_password", "search_base_dn")

# Mock employee directory for lookup responses
MOCK_DIRECTORY = {
    "jane.chen@example.com": {
        "employeeId": "emp_001",
        "name": "Jane Chen",
        "email": "jane.chen@example.com",
        "role": "Senior SRE",
        "department": "Platform Engineering",
    },
    "emp_001": {
        "employeeId": "emp_001",
        "name": "Jane Chen",
        "email": "jane.chen@example.com",
        "role": "Senior SRE",
        "department": "Platform Engineering",
    },
    "marcus.r@example.com": {
        "employeeId": "emp_002",
        "name": "Marcus Rivera",
        "email": "marcus.r@example.com",
        "role": "Engineering Manager",
        "department": "Backend Services",
    },
    "emp_002": {
        "employeeId": "emp_002",
        "name": "Marcus Rivera",
        "email": "marcus.r@example.com",
        "role": "Engineering Manager",
        "department": "Backend Services",
    },
}


def _validate_credentials(provider, credentials):
    """Return list of missing required field names."""
    if provider == "microsoft":
        return [f for f in MICROSOFT_REQUIRED_FIELDS if not (credentials.get(f) or "").strip()]
    if provider == "google":
        return [f for f in GOOGLE_REQUIRED_FIELDS if not (credentials.get(f) or "").strip()]
    if provider == "ldap":
        return [f for f in LDAP_REQUIRED_FIELDS if not (credentials.get(f) or "").strip()]
    return ["VALIDATION_ERROR"]


@app.route("/admin/directory-config", methods=["GET"])
def get_directory_config():
    return _envelope(data=DIRECTORY_CONFIG)


@app.route("/admin/directory-config", methods=["PUT"])
def save_directory_config():
    body = request.get_json(silent=True) or {}
    provider = body.get("provider", "")
    credentials = body.get("credentials", {})

    if provider not in VALID_DIRECTORY_PROVIDERS:
        return _envelope(
            error={
                "code": "VALIDATION_ERROR",
                "message": f"Invalid provider '{provider}'. Valid providers: google, ldap, microsoft",
                "details": {},
            },
            status_code=400,
        )

    missing = _validate_credentials(provider, credentials)
    if missing:
        return _envelope(
            error={
                "code": "VALIDATION_ERROR",
                "message": f"Missing required fields: {', '.join(missing)}",
                "details": {"missing": missing},
            },
            status_code=400,
        )

    # Apply LDAP defaults
    if provider == "ldap":
        if not (credentials.get("port") or "").strip():
            credentials["port"] = "389"
        if not (credentials.get("search_filter_template") or "").strip():
            credentials["search_filter_template"] = "(|(mail={query})(uid={query}))"

    DIRECTORY_CREDENTIALS.clear()
    DIRECTORY_CREDENTIALS.update(credentials)
    DIRECTORY_CONFIG["provider"] = provider
    DIRECTORY_CONFIG["credentials_configured"] = True

    return _envelope(data={"provider": provider, "credentials_configured": True})


@app.route("/admin/directory-config/test", methods=["POST"])
def test_directory_connection():
    body = request.get_json(silent=True) or {}
    provider = body.get("provider", "")
    credentials = body.get("credentials", {})

    if provider not in VALID_DIRECTORY_PROVIDERS:
        return _envelope(
            error={
                "code": "VALIDATION_ERROR",
                "message": f"Invalid provider '{provider}'. Valid providers: google, ldap, microsoft",
                "details": {},
            },
            status_code=400,
        )

    missing = _validate_credentials(provider, credentials)
    if missing:
        return _envelope(
            error={
                "code": "VALIDATION_ERROR",
                "message": f"Missing required fields: {', '.join(missing)}",
                "details": {"missing": missing},
            },
            status_code=400,
        )

    # Mock: always succeed for valid payloads
    return _envelope(data={"test_passed": True, "message": "Connection successful"})


@app.route("/directory/lookup", methods=["GET"])
def directory_lookup():
    query = (request.args.get("query") or "").strip()
    if not query:
        return _envelope(
            error={"code": "VALIDATION_ERROR", "message": "query parameter is required", "details": {}},
            status_code=400,
        )

    provider = DIRECTORY_CONFIG.get("provider")
    if not provider:
        return _envelope(
            error={"code": "PROVIDER_NOT_CONFIGURED", "message": "No directory provider configured", "details": {}},
            status_code=500,
        )

    if not DIRECTORY_CONFIG.get("credentials_configured"):
        return _envelope(
            error={"code": "CREDENTIALS_UNAVAILABLE", "message": "Directory credentials not configured", "details": {}},
            status_code=500,
        )

    record = MOCK_DIRECTORY.get(query)
    if record is None:
        return _envelope(
            error={"code": "EMPLOYEE_NOT_FOUND", "message": f"No employee found for query '{query}'", "details": {}},
            status_code=404,
        )

    return _envelope(data=record)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n  KnowledgeKeeper Local Dev Server")
    print("  ================================")
    print(f"  Seeded {len(TWINS)} twins, {len(ACCESS)} access records")
    print("  Default user: local-dev-user")
    print()
    print("  Twins:")
    for t in TWINS.values():
        print(f"    {t['employeeId']} — {t['name']} ({t['status']})")
    print()
    print("  Running on http://localhost:8000")
    print()
    app.run(host="0.0.0.0", port=8000, debug=True)
