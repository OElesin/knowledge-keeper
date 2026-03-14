"""Query handler Lambda — POST /twins/{employeeId}/query.

Thin handler that parses the API Gateway event and delegates to logic.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import logic

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Shared-layer modules are imported at module level so they can be
# patched easily in tests while remaining available to the logic layer.
from shared import bedrock as bedrock_module  # noqa: E402
from shared import dynamo as dynamo_module  # noqa: E402
from shared import s3vectors_client as s3vectors_module  # noqa: E402


def _response(status_code: int, body: dict) -> dict[str, Any]:
    """Build an API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle POST /twins/{employeeId}/query requests."""
    request_id = getattr(context, "aws_request_id", "unknown")

    try:
        # Extract inputs
        headers = event.get("headers") or {}
        user_id = headers.get("x-user-id") or headers.get("X-User-Id", "")
        employee_id = (event.get("pathParameters") or {}).get("employeeId", "")

        if not user_id:
            return _response(400, {
                "success": False,
                "data": None,
                "error": {
                    "code": "MISSING_USER_ID",
                    "message": "x-user-id header is required",
                    "details": {},
                },
                "requestId": request_id,
            })

        if not employee_id:
            return _response(400, {
                "success": False,
                "data": None,
                "error": {
                    "code": "MISSING_EMPLOYEE_ID",
                    "message": "employeeId path parameter is required",
                    "details": {},
                },
                "requestId": request_id,
            })

        body = json.loads(event.get("body") or "{}")
        query_text = body.get("query", "").strip()

        if not query_text:
            return _response(400, {
                "success": False,
                "data": None,
                "error": {
                    "code": "MISSING_QUERY",
                    "message": "Request body must include a non-empty 'query' field",
                    "details": {},
                },
                "requestId": request_id,
            })

        # Execute query pipeline
        result = logic.execute_query(
            user_id=user_id,
            employee_id=employee_id,
            query_text=query_text,
            request_id=request_id,
            dynamo_module=dynamo_module,
            bedrock_module=bedrock_module,
            s3vectors_module=s3vectors_module,
        )

        if result["success"]:
            return _response(200, {
                "success": True,
                "data": result["data"],
                "error": None,
                "requestId": request_id,
            })

        return _response(result["status_code"], {
            "success": False,
            "data": None,
            "error": result["error"],
            "requestId": request_id,
        })

    except json.JSONDecodeError:
        logger.exception("Invalid JSON in request body")
        return _response(400, {
            "success": False,
            "data": None,
            "error": {
                "code": "INVALID_JSON",
                "message": "Request body is not valid JSON",
                "details": {},
            },
            "requestId": request_id,
        })
    except Exception:
        logger.exception("Unexpected error in query_handler")
        return _response(500, {
            "success": False,
            "data": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {},
            },
            "requestId": request_id,
        })
