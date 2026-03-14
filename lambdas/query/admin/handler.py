"""Admin Lambda — handles all /twins admin routes.

Thin handler that parses the API Gateway event and delegates to logic.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

import logic

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from shared import dynamo as dynamo_module  # noqa: E402
from shared import s3vectors_client as s3vectors_module  # noqa: E402


# ---------------------------------------------------------------------------
# Lightweight S3 helper (used only by delete_twin)
# ---------------------------------------------------------------------------

class _S3Helper:
    """Thin wrapper around S3 list/delete for raw archive cleanup."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client("s3")
        return self._client

    def delete_objects_with_prefix(self, bucket: str, prefix: str) -> None:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if objects:
                self.client.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
                )


# ---------------------------------------------------------------------------
# Lightweight Lambda invoke helper (used only by create_twin)
# ---------------------------------------------------------------------------

class _LambdaHelper:
    """Thin wrapper around Lambda invoke for async email_fetcher calls."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client("lambda")
        return self._client

    def invoke_async(self, function_name: str, payload: dict) -> None:
        self.client.invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=json.dumps(payload).encode(),
        )


s3_helper = _S3Helper()
lambda_helper = _LambdaHelper()


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Route dispatcher
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route admin API requests to the appropriate logic function."""
    request_id = getattr(context, "aws_request_id", "unknown")
    method = event.get("httpMethod", "")
    resource = event.get("resource", "")
    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters")
    employee_id = path_params.get("employeeId", "")
    user_id_path = path_params.get("userId", "")

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
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

    try:
        result = _dispatch(
            method, resource, employee_id, user_id_path,
            body, query_params, request_id,
        )
    except Exception:
        logger.exception("Unexpected error in admin handler")
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

    status_code = result.get("status_code", 200)
    if result["success"]:
        return _response(status_code, {
            "success": True,
            "data": result["data"],
            "error": None,
            "requestId": request_id,
        })

    return _response(status_code, {
        "success": False,
        "data": None,
        "error": result["error"],
        "requestId": request_id,
    })


def _dispatch(
    method: str,
    resource: str,
    employee_id: str,
    user_id_path: str,
    body: dict,
    query_params: dict | None,
    request_id: str,
) -> dict:
    """Map HTTP method + resource to the correct logic function."""

    # POST /twins
    if method == "POST" and resource == "/twins":
        return logic.create_twin(
            body, request_id,
            dynamo_module=dynamo_module,
            lambda_module=lambda_helper,
        )

    # GET /twins
    if method == "GET" and resource == "/twins":
        return logic.list_twins(query_params, dynamo_module=dynamo_module)

    # GET /twins/{employeeId}
    if method == "GET" and resource == "/twins/{employeeId}":
        return logic.get_twin(employee_id, dynamo_module=dynamo_module)

    # DELETE /twins/{employeeId}
    if method == "DELETE" and resource == "/twins/{employeeId}":
        return logic.delete_twin(
            employee_id, request_id,
            dynamo_module=dynamo_module,
            s3vectors_module=s3vectors_module,
            s3_module=s3_helper,
        )

    # POST /twins/{employeeId}/access
    if method == "POST" and resource == "/twins/{employeeId}/access":
        return logic.grant_access(
            employee_id, body, request_id,
            dynamo_module=dynamo_module,
        )

    # DELETE /twins/{employeeId}/access/{userId}
    if method == "DELETE" and resource == "/twins/{employeeId}/access/{userId}":
        return logic.revoke_access(
            employee_id, user_id_path, request_id,
            dynamo_module=dynamo_module,
        )

    return {
        "success": False,
        "status_code": 400,
        "error": {
            "code": "UNKNOWN_ROUTE",
            "message": f"No handler for {method} {resource}",
            "details": {},
        },
    }
