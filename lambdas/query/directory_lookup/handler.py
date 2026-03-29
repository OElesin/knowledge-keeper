"""Directory lookup Lambda — GET /directory/lookup.

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
    """Handle GET /directory/lookup requests."""
    request_id = getattr(context, "aws_request_id", "unknown")

    try:
        params = event.get("queryStringParameters") or {}
        query = params.get("query", "")

        env_provider = os.environ.get("DIRECTORY_PROVIDER", "")
        env_secret_name = os.environ.get("DIRECTORY_SECRET_NAME", "")
        table_name = os.environ.get("TWINS_TABLE_NAME", "")

        dynamo_client = boto3.client("dynamodb")
        try:
            provider, secret_name = logic.resolve_provider_config(
                dynamo_client=dynamo_client,
                table_name=table_name,
                env_provider=env_provider,
                env_secret_name=env_secret_name,
            )
        except logic.ProviderNotConfiguredError:
            return _response(500, {
                "success": False,
                "data": None,
                "error": {
                    "code": "PROVIDER_NOT_CONFIGURED",
                    "message": "No directory provider is configured",
                    "details": {},
                },
                "requestId": request_id,
            })

        logger.info(
            "Directory lookup request",
            extra={
                "employee_query_type": "email" if "@" in query else "id",
                "provider": provider,
            },
        )

        secrets_client = boto3.client("secretsmanager")
        result = logic.lookup_employee(
            query=query,
            provider=provider,
            secret_name=secret_name,
            secrets_client=secrets_client,
        )

        if result["success"]:
            return _response(result["status_code"], {
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

    except Exception:
        logger.exception("Unexpected error in directory_lookup")
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
