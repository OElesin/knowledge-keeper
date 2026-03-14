"""Business logic for the admin Lambda.

Handles twin CRUD, access management, and twin deletion (right to erasure).
All AWS SDK interactions are injected as module dependencies for testability.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_YEARS = 3

REQUIRED_TWIN_FIELDS = ("employeeId", "name", "email", "role", "department", "offboardDate")


# ---------------------------------------------------------------------------
# POST /twins — create twin
# ---------------------------------------------------------------------------

def create_twin(
    body: dict[str, Any],
    request_id: str,
    *,
    dynamo_module: Any,
    lambda_module: Any | None = None,
) -> dict:
    """Create a new Twin record.

    Returns {"success": True, "status_code": 201, "data": {...}}
    or      {"success": False, "status_code": int, "error": {...}}
    """
    # Validate required fields
    missing = [f for f in REQUIRED_TWIN_FIELDS if not body.get(f)]
    if missing:
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"Missing required fields: {', '.join(missing)}",
                "details": {"missing": missing},
            },
        }

    employee_id = body["employeeId"]

    # Check for existing twin
    existing = dynamo_module.get_twin(employee_id)
    if existing is not None:
        return {
            "success": False,
            "status_code": 409,
            "error": {
                "code": "TWIN_ALREADY_EXISTS",
                "message": f"Twin already exists for employee {employee_id}",
                "details": {},
            },
        }

    # Compute retention_expiry
    retention_years = int(os.environ.get("RETENTION_YEARS", DEFAULT_RETENTION_YEARS))
    offboard_date_str = body["offboardDate"]
    try:
        offboard_dt = date.fromisoformat(offboard_date_str)
    except (ValueError, TypeError):
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "offboardDate must be a valid ISO date (YYYY-MM-DD)",
                "details": {},
            },
        }

    retention_expiry = offboard_dt + timedelta(days=retention_years * 365)

    provider = body.get("provider", "upload")

    item = {
        "employeeId": employee_id,
        "name": body["name"],
        "email": body["email"],
        "role": body["role"],
        "department": body["department"],
        "offboardDate": offboard_date_str,
        "status": "ingesting",
        "chunkCount": 0,
        "topicIndex": [],
        "retentionExpiry": retention_expiry.isoformat(),
        "provider": provider,
    }
    if body.get("tenureStart"):
        item["tenureStart"] = body["tenureStart"]

    try:
        dynamo_module.create_twin(item)
    except Exception:
        logger.exception("Failed to create twin %s", employee_id)
        return {
            "success": False,
            "status_code": 500,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to create twin record",
                "details": {},
            },
        }

    # Optionally invoke email_fetcher async for Google provider
    if provider == "google" and lambda_module is not None:
        fetcher_fn = os.environ.get("EMAIL_FETCHER_FN_NAME", "")
        if fetcher_fn:
            try:
                lambda_module.invoke_async(
                    function_name=fetcher_fn,
                    payload={"employeeId": employee_id, "email": body["email"]},
                )
            except Exception:
                logger.exception("Failed to invoke email_fetcher for %s", employee_id)

    # Audit log
    dynamo_module.write_audit_log(
        request_id=request_id,
        action="create_twin",
        details={"employeeId": employee_id, "provider": provider},
    )

    return {"success": True, "status_code": 201, "data": item}


# ---------------------------------------------------------------------------
# GET /twins — list twins
# ---------------------------------------------------------------------------

def list_twins(
    query_params: dict[str, str] | None,
    *,
    dynamo_module: Any,
) -> dict:
    """List all twins, optionally filtered by status."""
    status_filter = (query_params or {}).get("status")
    items = dynamo_module.list_twins(status_filter=status_filter)
    return {"success": True, "status_code": 200, "data": {"twins": items}}


# ---------------------------------------------------------------------------
# GET /twins/{employeeId} — get twin detail
# ---------------------------------------------------------------------------

def get_twin(
    employee_id: str,
    *,
    dynamo_module: Any,
) -> dict:
    """Get a single twin by employeeId."""
    twin = dynamo_module.get_twin(employee_id)
    if twin is None:
        return {
            "success": False,
            "status_code": 404,
            "error": {
                "code": "TWIN_NOT_FOUND",
                "message": f"No twin found for employee {employee_id}",
                "details": {},
            },
        }
    return {"success": True, "status_code": 200, "data": twin}


# ---------------------------------------------------------------------------
# DELETE /twins/{employeeId} — delete twin (right to erasure)
# ---------------------------------------------------------------------------

def delete_twin(
    employee_id: str,
    request_id: str,
    *,
    dynamo_module: Any,
    s3vectors_module: Any,
    s3_module: Any,
) -> dict:
    """Delete all data associated with a twin."""
    twin = dynamo_module.get_twin(employee_id)
    if twin is None:
        return {
            "success": False,
            "status_code": 404,
            "error": {
                "code": "TWIN_NOT_FOUND",
                "message": f"No twin found for employee {employee_id}",
                "details": {},
            },
        }

    now = datetime.now(timezone.utc)

    # 1. Delete vectors from S3 Vectors
    try:
        s3vectors_module.delete_vectors_for_employee(employee_id)
    except Exception:
        logger.exception("Failed to delete vectors for %s", employee_id)

    # 2. Delete S3 raw archive objects
    try:
        bucket = os.environ.get("RAW_ARCHIVES_BUCKET", "")
        if bucket:
            s3_module.delete_objects_with_prefix(bucket, f"{employee_id}/")
    except Exception:
        logger.exception("Failed to delete S3 objects for %s", employee_id)

    # 3. Delete DynamoDB records
    dynamo_module.delete_twin(employee_id)
    dynamo_module.delete_access_for_employee(employee_id)

    # 4. Audit log
    dynamo_module.write_audit_log(
        request_id=request_id,
        action="delete_twin",
        details={"employeeId": employee_id, "deletedAt": now.isoformat()},
    )

    return {
        "success": True,
        "status_code": 200,
        "data": {"employeeId": employee_id, "deletedAt": now.isoformat()},
    }



# ---------------------------------------------------------------------------
# POST /twins/{employeeId}/access — grant access
# ---------------------------------------------------------------------------

def grant_access(
    employee_id: str,
    body: dict[str, Any],
    request_id: str,
    *,
    dynamo_module: Any,
) -> dict:
    """Grant a user access to a twin."""
    user_id = body.get("userId", "").strip()
    role = body.get("role", "viewer").strip()

    if not user_id:
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "userId is required",
                "details": {},
            },
        }

    if role not in ("admin", "viewer"):
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "role must be 'admin' or 'viewer'",
                "details": {},
            },
        }

    # Verify twin exists
    twin = dynamo_module.get_twin(employee_id)
    if twin is None:
        return {
            "success": False,
            "status_code": 404,
            "error": {
                "code": "TWIN_NOT_FOUND",
                "message": f"No twin found for employee {employee_id}",
                "details": {},
            },
        }

    record = dynamo_module.grant_access(user_id, employee_id, role)

    dynamo_module.write_audit_log(
        request_id=request_id,
        action="grant_access",
        details={"employeeId": employee_id, "userId": user_id, "role": role},
    )

    return {"success": True, "status_code": 200, "data": record}


# ---------------------------------------------------------------------------
# DELETE /twins/{employeeId}/access/{userId} — revoke access
# ---------------------------------------------------------------------------

def revoke_access(
    employee_id: str,
    user_id: str,
    request_id: str,
    *,
    dynamo_module: Any,
) -> dict:
    """Revoke a user's access to a twin."""
    dynamo_module.revoke_access(user_id, employee_id)

    dynamo_module.write_audit_log(
        request_id=request_id,
        action="revoke_access",
        details={"employeeId": employee_id, "userId": user_id},
    )

    return {
        "success": True,
        "status_code": 200,
        "data": {"employeeId": employee_id, "userId": user_id},
    }
