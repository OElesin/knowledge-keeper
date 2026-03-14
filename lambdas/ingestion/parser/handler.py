"""Lambda handler for the parser.

Triggered by SQS ParseQueue. Downloads .mbox files from S3, parses
emails, reconstructs threads, and publishes each thread to CleanQueue.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from logic import (
    build_thread_payload,
    parse_mbox_bytes,
    reconstruct_threads,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CLEAN_QUEUE_URL = os.environ["CLEAN_QUEUE_URL"]
RAW_ARCHIVES_BUCKET = os.environ["RAW_ARCHIVES_BUCKET"]


def _get_s3_client():
    return boto3.client("s3")


def _get_sqs_client():
    return boto3.client("sqs")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for SQS ParseQueue events."""
    s3_client = _get_s3_client()
    sqs_client = _get_sqs_client()

    batch_failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        message_body = json.loads(record["body"])
        employee_id = message_body["employeeId"]
        s3_key = message_body["s3Key"]

        try:
            # Download .mbox from S3
            response = s3_client.get_object(
                Bucket=RAW_ARCHIVES_BUCKET,
                Key=s3_key,
            )
            mbox_bytes = response["Body"].read()

            # Parse emails from .mbox
            messages = parse_mbox_bytes(mbox_bytes)
            if not messages:
                logger.info(
                    "No parseable messages in %s for employee %s",
                    s3_key,
                    employee_id,
                )
                continue

            # Reconstruct threads
            threads = reconstruct_threads(messages)

            # Look up employee email from the Twin record or infer
            # from the most common "from" address in the batch.
            employee_email = _infer_employee_email(
                messages, message_body.get("employeeEmail", "")
            )

            # Publish each thread to CleanQueue
            for thread in threads:
                payload = build_thread_payload(
                    thread, employee_id, employee_email
                )
                sqs_client.send_message(
                    QueueUrl=CLEAN_QUEUE_URL,
                    MessageBody=json.dumps(payload, default=str),
                )

            logger.info(
                "Parsed %d messages into %d threads from %s (employee=%s)",
                len(messages),
                len(threads),
                s3_key,
                employee_id,
            )

        except Exception:
            logger.exception(
                "Failed to process %s for employee %s",
                s3_key,
                employee_id,
            )
            batch_failures.append(
                {"itemIdentifier": record["messageId"]}
            )

    # Return partial batch failure response so successfully processed
    # messages are deleted from the queue while failed ones are retried.
    return {"batchItemFailures": batch_failures}


def _infer_employee_email(
    messages: list[dict], provided_email: str
) -> str:
    """Return the employee email, falling back to the most common sender."""
    if provided_email:
        return provided_email

    from_counts: dict[str, int] = {}
    for msg in messages:
        addr = msg.get("from_addr", "").strip().lower()
        if addr:
            from_counts[addr] = from_counts.get(addr, 0) + 1

    if from_counts:
        return max(from_counts, key=from_counts.get)  # type: ignore[arg-type]
    return ""
