"""Lambda handler for m365_email_fetcher.

Invoked asynchronously by the admin Lambda to fetch emails from
Microsoft 365 for a departing employee and upload them as
batched .mbox files to the raw-archives S3 bucket.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import boto3

from logic import fetch_and_upload_emails, get_m365_credentials

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

RAW_ARCHIVES_BUCKET = os.environ["RAW_ARCHIVES_BUCKET"]
M365_CREDS_SECRET = os.environ["M365_CREDS_SECRET"]
TWINS_TABLE_NAME = os.environ["TWINS_TABLE_NAME"]


def _get_s3_client():
    return boto3.client("s3")


def _get_secrets_client():
    return boto3.client("secretsmanager")


def _get_dynamo_resource():
    return boto3.resource("dynamodb")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point.

    Expected event shape:
        {"employeeId": "emp_123", "email": "jane@corp.com"}
    """
    employee_id = event["employeeId"]
    user_email = event["email"]

    logger.info(
        "Starting M365 email fetch for employee=%s email=%s",
        employee_id,
        user_email,
    )

    secrets_client = _get_secrets_client()
    s3_client = _get_s3_client()
    dynamo = _get_dynamo_resource()
    twins_table = dynamo.Table(TWINS_TABLE_NAME)

    try:
        twins_table.update_item(
            Key={"employeeId": employee_id},
            UpdateExpression="SET #s = :ingesting",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":ingesting": "ingesting"},
        )

        credentials = get_m365_credentials(
            secret_name=M365_CREDS_SECRET,
            secrets_client=secrets_client,
        )

        manifest = fetch_and_upload_emails(
            employee_id=employee_id,
            user_email=user_email,
            bucket_name=RAW_ARCHIVES_BUCKET,
            credentials=credentials,
            s3_client=s3_client,
        )

        logger.info(
            "Completed M365 fetch for employee=%s: %d emails in %d batches",
            employee_id,
            manifest["totalCount"],
            manifest["batchCount"],
        )

        return {
            "statusCode": 200,
            "employeeId": employee_id,
            "totalCount": manifest["totalCount"],
            "batchCount": manifest["batchCount"],
        }

    except Exception:
        logger.exception(
            "Failed to fetch M365 emails for employee=%s", employee_id
        )
        try:
            twins_table.update_item(
                Key={"employeeId": employee_id},
                UpdateExpression="SET #s = :error",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":error": "error"},
            )
        except Exception:
            logger.exception(
                "Failed to update Twin status to error for employee=%s",
                employee_id,
            )
        raise
