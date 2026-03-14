"""Lambda handler for ingest_trigger.

Triggered by S3 PutObject events on the raw-archives bucket.
Parses the event, publishes a message to ParseQueue, and updates
the Twin status to 'processing' in DynamoDB.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from logic import parse_s3_records

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

PARSE_QUEUE_URL = os.environ["PARSE_QUEUE_URL"]
TWINS_TABLE_NAME = os.environ["TWINS_TABLE_NAME"]


def _get_sqs_client():
    return boto3.client("sqs")


def _get_dynamo_resource():
    return boto3.resource("dynamodb")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for S3 PutObject events."""
    messages = parse_s3_records(event)

    if not messages:
        logger.info("No matching S3 keys found in event — nothing to do.")
        return {"statusCode": 200, "processed": 0}

    sqs_client = _get_sqs_client()
    dynamo = _get_dynamo_resource()
    twins_table = dynamo.Table(TWINS_TABLE_NAME)

    processed = 0
    for msg in messages:
        # Publish to ParseQueue
        sqs_client.send_message(
            QueueUrl=PARSE_QUEUE_URL,
            MessageBody=json.dumps(
                {
                    "employeeId": msg["employeeId"],
                    "s3Key": msg["s3Key"],
                    "batchNumber": msg["batchNumber"],
                }
            ),
        )
        logger.info(
            "Published to ParseQueue: employeeId=%s, s3Key=%s",
            msg["employeeId"],
            msg["s3Key"],
        )

        # Update Twin status to 'processing' (conditional to avoid overwriting
        # a later status like 'active' if batches arrive out of order).
        try:
            twins_table.update_item(
                Key={"employeeId": msg["employeeId"]},
                UpdateExpression="SET #s = :processing",
                ConditionExpression="#s IN (:ingesting, :processing)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":processing": "processing",
                    ":ingesting": "ingesting",
                },
            )
        except dynamo.meta.client.exceptions.ConditionalCheckFailedException:
            logger.info(
                "Twin %s status not updated — already past processing stage.",
                msg["employeeId"],
            )

        processed += 1

    return {"statusCode": 200, "processed": processed}
