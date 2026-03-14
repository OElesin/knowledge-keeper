"""Lambda handler for the cleaner.

Triggered by SQS CleanQueue. Strips noise, detects and redacts PII,
discards low-signal messages, and publishes surviving threads to
EmbedQueue.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from logic import clean_thread

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

EMBED_QUEUE_URL = os.environ["EMBED_QUEUE_URL"]


def _get_sqs_client():
    return boto3.client("sqs")


def _get_comprehend_client():
    return boto3.client("comprehend")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for SQS CleanQueue events."""
    sqs_client = _get_sqs_client()
    comprehend_client = _get_comprehend_client()

    batch_failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        try:
            thread = json.loads(record["body"])
            employee_id = thread.get("employeeId", "unknown")
            thread_id = thread.get("threadId", "unknown")

            cleaned = clean_thread(thread, comprehend_client)

            if cleaned is None:
                logger.info(
                    "Thread %s for employee %s discarded (no surviving messages)",
                    thread_id,
                    employee_id,
                )
                continue

            sqs_client.send_message(
                QueueUrl=EMBED_QUEUE_URL,
                MessageBody=json.dumps(cleaned, default=str),
            )

            logger.info(
                "Cleaned thread %s for employee %s — %d messages survived",
                thread_id,
                employee_id,
                len(cleaned["messages"]),
            )

        except Exception:
            logger.exception(
                "Failed to process record %s", record.get("messageId", "")
            )
            batch_failures.append(
                {"itemIdentifier": record["messageId"]}
            )

    return {"batchItemFailures": batch_failures}
