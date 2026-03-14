"""Lambda handler for the embedder.

Triggered by SQS EmbedQueue. Chunks cleaned threads, generates
embeddings via Nova Multimodal Embeddings, indexes in S3 Vectors,
and updates Twin status in DynamoDB.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from logic import chunk_thread, embed_and_index_chunks, update_twin_status

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

VECTOR_BUCKET_NAME = os.environ.get("VECTOR_BUCKET_NAME", "")
VECTOR_INDEX_NAME = os.environ.get("VECTOR_INDEX_NAME", "")
TWINS_TABLE_NAME = os.environ.get("TWINS_TABLE_NAME", "")


def _get_bedrock_client():
    return boto3.client("bedrock-runtime")


def _get_s3vectors_client():
    return boto3.client("s3vectors")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for SQS EmbedQueue events."""
    bedrock_client = _get_bedrock_client()
    s3vectors_client = _get_s3vectors_client()

    batch_failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        try:
            thread = json.loads(record["body"])
            employee_id = thread.get("employeeId", "unknown")
            thread_id = thread.get("threadId", "unknown")

            chunks = chunk_thread(thread)
            if not chunks:
                logger.info(
                    "Thread %s for employee %s produced no chunks",
                    thread_id,
                    employee_id,
                )
                continue

            indexed = embed_and_index_chunks(
                chunks,
                bedrock_client=bedrock_client,
                s3vectors_client=s3vectors_client,
                vector_bucket_name=VECTOR_BUCKET_NAME,
                vector_index_name=VECTOR_INDEX_NAME,
            )

            update_twin_status(employee_id, indexed)

            logger.info(
                "Embedded and indexed %d chunks for thread %s (employee=%s)",
                indexed,
                thread_id,
                employee_id,
            )

        except Exception:
            logger.exception(
                "Failed to process record %s", record.get("messageId", "")
            )
            batch_failures.append(
                {"itemIdentifier": record["messageId"]}
            )

    return {"batchItemFailures": batch_failures}
