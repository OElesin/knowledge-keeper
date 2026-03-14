"""Unit tests for ingest_trigger logic."""
from __future__ import annotations

import pytest

from lambdas.ingestion.trigger.logic import parse_s3_key, parse_s3_records


# --- Fixtures ---

def _s3_event(*keys: str, bucket: str = "kk-123456789-dev-raw-archives") -> dict:
    """Build a minimal S3 PutObject event with the given keys."""
    return {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                }
            }
            for key in keys
        ]
    }


# --- parse_s3_key ---

class TestParseS3Key:
    def test_valid_key_returns_employee_and_batch(self):
        result = parse_s3_key("emp_123/batch_0001.mbox")
        assert result == {"employee_id": "emp_123", "batch_number": "0001"}

    def test_batch_number_zero(self):
        result = parse_s3_key("emp_456/batch_0000.mbox")
        assert result == {"employee_id": "emp_456", "batch_number": "0000"}

    def test_large_batch_number(self):
        result = parse_s3_key("emp_789/batch_9999.mbox")
        assert result == {"employee_id": "emp_789", "batch_number": "9999"}

    def test_missing_batch_prefix_returns_none(self):
        assert parse_s3_key("emp_123/emails.mbox") is None

    def test_wrong_extension_returns_none(self):
        assert parse_s3_key("emp_123/batch_0001.eml") is None

    def test_nested_path_returns_none(self):
        assert parse_s3_key("org/emp_123/batch_0001.mbox") is None

    def test_empty_key_returns_none(self):
        assert parse_s3_key("") is None

    def test_no_slash_returns_none(self):
        assert parse_s3_key("batch_0001.mbox") is None

    def test_manifest_json_returns_none(self):
        assert parse_s3_key("emp_123/manifest.json") is None


# --- parse_s3_records ---

class TestParseS3Records:
    def test_single_valid_record(self):
        event = _s3_event("emp_001/batch_0001.mbox")
        result = parse_s3_records(event)
        assert len(result) == 1
        assert result[0] == {
            "employeeId": "emp_001",
            "s3Key": "emp_001/batch_0001.mbox",
            "batchNumber": "0001",
            "bucket": "kk-123456789-dev-raw-archives",
        }

    def test_multiple_valid_records(self):
        event = _s3_event(
            "emp_001/batch_0001.mbox",
            "emp_001/batch_0002.mbox",
        )
        result = parse_s3_records(event)
        assert len(result) == 2
        assert result[0]["batchNumber"] == "0001"
        assert result[1]["batchNumber"] == "0002"

    def test_skips_non_matching_keys(self):
        event = _s3_event(
            "emp_001/batch_0001.mbox",
            "emp_001/manifest.json",
        )
        result = parse_s3_records(event)
        assert len(result) == 1
        assert result[0]["s3Key"] == "emp_001/batch_0001.mbox"

    def test_empty_records_returns_empty(self):
        assert parse_s3_records({"Records": []}) == []

    def test_missing_records_key_returns_empty(self):
        assert parse_s3_records({}) == []

    def test_all_non_matching_returns_empty(self):
        event = _s3_event("readme.txt", "emp_001/manifest.json")
        assert parse_s3_records(event) == []

    def test_different_employees_in_same_event(self):
        event = _s3_event(
            "emp_001/batch_0001.mbox",
            "emp_002/batch_0001.mbox",
        )
        result = parse_s3_records(event)
        assert len(result) == 2
        assert result[0]["employeeId"] == "emp_001"
        assert result[1]["employeeId"] == "emp_002"

    def test_preserves_bucket_name(self):
        event = _s3_event("emp_001/batch_0001.mbox", bucket="my-custom-bucket")
        result = parse_s3_records(event)
        assert result[0]["bucket"] == "my-custom-bucket"
