"""Business logic for the ingest_trigger Lambda.

Parses S3 PutObject events and extracts employee/batch metadata
for publishing to the ParseQueue.
"""
from __future__ import annotations

import re
from typing import Any

# Pattern: {employeeId}/batch_{NNNN}.mbox
_KEY_PATTERN = re.compile(r"^(?P<employee_id>[^/]+)/batch_(?P<batch_number>\d+)\.mbox$")


def parse_s3_records(event: dict[str, Any]) -> list[dict[str, str]]:
    """Extract ingestion messages from an S3 event.

    Returns a list of dicts with keys: employeeId, s3Key, batchNumber, bucket.
    Records whose key does not match the expected pattern are silently skipped.
    """
    messages: list[dict[str, str]] = []
    for record in event.get("Records", []):
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", "")
        key = s3_info.get("object", {}).get("key", "")

        parsed = parse_s3_key(key)
        if parsed is None:
            continue

        messages.append(
            {
                "employeeId": parsed["employee_id"],
                "s3Key": key,
                "batchNumber": parsed["batch_number"],
                "bucket": bucket,
            }
        )
    return messages


def parse_s3_key(key: str) -> dict[str, str] | None:
    """Parse an S3 key into employee_id and batch_number.

    Returns None if the key does not match the expected pattern.
    """
    match = _KEY_PATTERN.match(key)
    if not match:
        return None
    return {
        "employee_id": match.group("employee_id"),
        "batch_number": match.group("batch_number"),
    }
