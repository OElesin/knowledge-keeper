"""Unit tests for query_handler logic."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from lambdas.query.query_handler.logic import (
    build_rag_prompt,
    build_system_prompt,
    calculate_confidence,
    check_access,
    check_staleness,
    execute_query,
    format_sources,
    get_active_twin,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_twin(**overrides) -> dict:
    """Build a minimal twin record."""
    twin = {
        "employeeId": "emp_123",
        "name": "Jane Doe",
        "email": "jane@corp.com",
        "role": "Senior SRE",
        "department": "Platform",
        "tenureStart": "2020-01-15",
        "offboardDate": "2024-06-30",
        "status": "active",
        "chunkCount": 500,
    }
    twin.update(overrides)
    return twin


def _make_chunk(key: str = "chunk_001", distance: float = 0.2, **meta_overrides) -> dict:
    """Build a minimal S3 Vectors result chunk."""
    metadata = {
        "employee_id": "emp_123",
        "thread_id": "thread_001",
        "author_role": "primary",
        "date": "2024-03-15T10:00:00+00:00",
        "content": "The root cause is the consumer group rebalancing during deployment.",
        "subject": "Re: Kafka lag issue",
    }
    metadata.update(meta_overrides)
    return {"key": key, "distance": distance, "metadata": metadata}


def _mock_dynamo(access_record=None, twin=None):
    """Return a mock dynamo module."""
    mod = MagicMock()
    mod.check_access.return_value = access_record
    mod.get_twin.return_value = twin
    mod.write_audit_log.return_value = {}
    return mod


def _mock_bedrock(embedding=None, answer="The answer is 42."):
    """Return a mock bedrock module."""
    mod = MagicMock()
    mod.get_embedding.return_value = embedding or [0.1] * 1024
    mod.generate_response.return_value = answer
    return mod


def _mock_s3vectors(chunks=None):
    """Return a mock s3vectors module."""
    mod = MagicMock()
    mod.query_vectors.return_value = chunks if chunks is not None else [_make_chunk()]
    return mod


# ---------------------------------------------------------------------------
# check_access
# ---------------------------------------------------------------------------

class TestCheckAccess:
    def test_returns_record_when_access_exists(self):
        dynamo = _mock_dynamo(access_record={"userId": "user_1", "employeeId": "emp_123", "role": "viewer"})
        result = check_access("user_1", "emp_123", dynamo)
        assert result is not None
        assert result["role"] == "viewer"

    def test_returns_none_when_no_access(self):
        dynamo = _mock_dynamo(access_record=None)
        result = check_access("user_1", "emp_123", dynamo)
        assert result is None


# ---------------------------------------------------------------------------
# get_active_twin
# ---------------------------------------------------------------------------

class TestGetActiveTwin:
    def test_returns_twin_when_active(self):
        twin = _make_twin()
        dynamo = _mock_dynamo(twin=twin)
        result, error = get_active_twin("emp_123", dynamo)
        assert result is not None
        assert error is None

    def test_returns_error_when_not_found(self):
        dynamo = _mock_dynamo(twin=None)
        result, error = get_active_twin("emp_123", dynamo)
        assert result is None
        assert error == "TWIN_NOT_FOUND"

    def test_returns_error_when_not_active(self):
        twin = _make_twin(status="ingesting")
        dynamo = _mock_dynamo(twin=twin)
        result, error = get_active_twin("emp_123", dynamo)
        assert result is not None
        assert error == "TWIN_NOT_ACTIVE"


# ---------------------------------------------------------------------------
# build_rag_prompt
# ---------------------------------------------------------------------------

class TestBuildRagPrompt:
    def test_includes_context_and_query(self):
        twin = _make_twin()
        chunks = [_make_chunk()]
        result = build_rag_prompt(twin, "What caused the Kafka lag?", chunks)
        assert "Kafka lag" in result
        assert "consumer group rebalancing" in result
        assert "chunk_001" in result

    def test_empty_chunks_shows_no_context(self):
        twin = _make_twin()
        result = build_rag_prompt(twin, "Any question?", [])
        assert "(no context found)" in result

    def test_multiple_chunks_separated(self):
        chunks = [_make_chunk(key="c1"), _make_chunk(key="c2")]
        result = build_rag_prompt(_make_twin(), "query", chunks)
        assert "c1" in result
        assert "c2" in result
        assert "---" in result


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_includes_twin_metadata(self):
        twin = _make_twin()
        result = build_system_prompt(twin)
        assert "Jane Doe" in result
        assert "Senior SRE" in result
        assert "Platform" in result


# ---------------------------------------------------------------------------
# calculate_confidence
# ---------------------------------------------------------------------------

class TestCalculateConfidence:
    def test_perfect_similarity(self):
        chunks = [_make_chunk(distance=0.0)]
        assert calculate_confidence(chunks) == 1.0

    def test_zero_similarity(self):
        chunks = [_make_chunk(distance=1.0)]
        assert calculate_confidence(chunks) == 0.0

    def test_average_of_multiple(self):
        chunks = [_make_chunk(distance=0.2), _make_chunk(distance=0.4)]
        # similarities: 0.8, 0.6 → avg = 0.7
        assert calculate_confidence(chunks) == 0.7

    def test_empty_chunks_returns_zero(self):
        assert calculate_confidence([]) == 0.0

    def test_negative_distance_clamped(self):
        chunks = [_make_chunk(distance=1.5)]
        assert calculate_confidence(chunks) == 0.0


# ---------------------------------------------------------------------------
# check_staleness
# ---------------------------------------------------------------------------

class TestCheckStaleness:
    def test_no_warning_for_recent_sources(self):
        recent = datetime.now(timezone.utc).isoformat()
        chunks = [_make_chunk(date=recent)]
        assert check_staleness(chunks) is None

    def test_warning_for_old_sources(self):
        chunks = [_make_chunk(date="2020-01-01T00:00:00+00:00")]
        result = check_staleness(chunks)
        assert result is not None
        assert "outdated" in result

    def test_empty_chunks(self):
        result = check_staleness([])
        assert result is not None
        assert "No source data" in result

    def test_unparseable_dates(self):
        chunks = [_make_chunk(date="not-a-date")]
        result = check_staleness(chunks)
        assert result is not None
        assert "Unable to determine" in result


# ---------------------------------------------------------------------------
# format_sources
# ---------------------------------------------------------------------------

class TestFormatSources:
    def test_formats_chunk_to_source(self):
        chunks = [_make_chunk()]
        sources = format_sources(chunks)
        assert len(sources) == 1
        assert sources[0]["chunkId"] == "chunk_001"
        assert sources[0]["subject"] == "Re: Kafka lag issue"
        assert len(sources[0]["contentPreview"]) > 0

    def test_truncates_long_content(self):
        chunks = [_make_chunk(content="x" * 500)]
        sources = format_sources(chunks)
        assert len(sources[0]["contentPreview"]) == 200

    def test_empty_chunks(self):
        assert format_sources([]) == []


# ---------------------------------------------------------------------------
# execute_query (integration of all steps)
# ---------------------------------------------------------------------------

class TestExecuteQuery:
    def test_happy_path(self):
        dynamo = _mock_dynamo(
            access_record={"userId": "user_1", "employeeId": "emp_123", "role": "viewer"},
            twin=_make_twin(),
        )
        bedrock = _mock_bedrock()
        s3vectors = _mock_s3vectors()

        result = execute_query(
            user_id="user_1",
            employee_id="emp_123",
            query_text="What caused the Kafka lag?",
            request_id="req_001",
            dynamo_module=dynamo,
            bedrock_module=bedrock,
            s3vectors_module=s3vectors,
        )

        assert result["success"] is True
        assert "answer" in result["data"]
        assert result["data"]["answer"] == "The answer is 42."
        assert len(result["data"]["sources"]) == 1
        assert isinstance(result["data"]["confidence"], float)
        dynamo.write_audit_log.assert_called_once()

    def test_access_denied_when_no_access(self):
        dynamo = _mock_dynamo(access_record=None)
        result = execute_query(
            user_id="user_1",
            employee_id="emp_123",
            query_text="query",
            request_id="req_001",
            dynamo_module=dynamo,
            bedrock_module=_mock_bedrock(),
            s3vectors_module=_mock_s3vectors(),
        )
        assert result["success"] is False
        assert result["status_code"] == 403
        assert result["error"]["code"] == "ACCESS_DENIED"

    def test_access_denied_when_twin_not_found(self):
        dynamo = _mock_dynamo(
            access_record={"userId": "user_1", "employeeId": "emp_123", "role": "viewer"},
            twin=None,
        )
        result = execute_query(
            user_id="user_1",
            employee_id="emp_123",
            query_text="query",
            request_id="req_001",
            dynamo_module=dynamo,
            bedrock_module=_mock_bedrock(),
            s3vectors_module=_mock_s3vectors(),
        )
        # Returns 403 to avoid revealing twin existence
        assert result["success"] is False
        assert result["status_code"] == 403

    def test_twin_not_active(self):
        dynamo = _mock_dynamo(
            access_record={"userId": "user_1", "employeeId": "emp_123", "role": "viewer"},
            twin=_make_twin(status="ingesting"),
        )
        result = execute_query(
            user_id="user_1",
            employee_id="emp_123",
            query_text="query",
            request_id="req_001",
            dynamo_module=dynamo,
            bedrock_module=_mock_bedrock(),
            s3vectors_module=_mock_s3vectors(),
        )
        assert result["success"] is False
        assert result["status_code"] == 400
        assert result["error"]["code"] == "TWIN_NOT_ACTIVE"

    def test_empty_vector_results(self):
        dynamo = _mock_dynamo(
            access_record={"userId": "user_1", "employeeId": "emp_123", "role": "viewer"},
            twin=_make_twin(),
        )
        s3vectors = _mock_s3vectors(chunks=[])

        result = execute_query(
            user_id="user_1",
            employee_id="emp_123",
            query_text="query",
            request_id="req_001",
            dynamo_module=dynamo,
            bedrock_module=_mock_bedrock(),
            s3vectors_module=s3vectors,
        )
        assert result["success"] is True
        assert result["data"]["confidence"] == 0.0
        assert result["data"]["sources"] == []

    def test_audit_log_contains_query_details(self):
        dynamo = _mock_dynamo(
            access_record={"userId": "user_1", "employeeId": "emp_123", "role": "viewer"},
            twin=_make_twin(),
        )
        execute_query(
            user_id="user_1",
            employee_id="emp_123",
            query_text="What is the deploy process?",
            request_id="req_002",
            dynamo_module=dynamo,
            bedrock_module=_mock_bedrock(),
            s3vectors_module=_mock_s3vectors(),
        )
        call_kwargs = dynamo.write_audit_log.call_args[1]
        assert call_kwargs["request_id"] == "req_002"
        assert call_kwargs["action"] == "query"
        assert call_kwargs["details"]["query"] == "What is the deploy process?"
