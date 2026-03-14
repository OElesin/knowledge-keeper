"""Unit tests for shared Pydantic models."""
import pytest
from datetime import date, datetime

from shared.models import Twin, EmailChunk, QueryResult, ChunkReference


class TestTwin:
    def test_create_twin_with_required_fields(self):
        twin = Twin(
            employee_id="emp_001",
            name="Jane Doe",
            email="jane@corp.com",
            role="Senior SRE",
            department="Engineering",
            tenure_start=date(2020, 1, 15),
            offboard_date=date(2024, 6, 30),
            retention_expiry=date(2027, 6, 30),
        )
        assert twin.employee_id == "emp_001"
        assert twin.status == "ingesting"
        assert twin.chunk_count == 0
        assert twin.topic_index == []

    def test_twin_status_validation_accepts_valid(self):
        for status in ("ingesting", "active", "expired", "deleted"):
            twin = Twin(
                employee_id="emp_001",
                name="Jane",
                email="jane@corp.com",
                role="SRE",
                department="Eng",
                tenure_start=date(2020, 1, 1),
                offboard_date=date(2024, 1, 1),
                retention_expiry=date(2027, 1, 1),
                status=status,
            )
            assert twin.status == status

    def test_twin_status_validation_rejects_invalid(self):
        with pytest.raises(Exception):
            Twin(
                employee_id="emp_001",
                name="Jane",
                email="jane@corp.com",
                role="SRE",
                department="Eng",
                tenure_start=date(2020, 1, 1),
                offboard_date=date(2024, 1, 1),
                retention_expiry=date(2027, 1, 1),
                status="unknown",
            )


class TestEmailChunk:
    def test_create_email_chunk(self):
        chunk = EmailChunk(
            chunk_id="chunk_001",
            employee_id="emp_001",
            thread_id="thread_001",
            subject="Re: Kafka lag issue",
            date=datetime(2023, 3, 15, 10, 0, 0),
            author_role="primary",
            content="The root cause is the consumer group rebalancing...",
        )
        assert chunk.chunk_id == "chunk_001"
        assert chunk.relevance_score == 0.0
        assert chunk.topics == []

    def test_email_chunk_author_role_rejects_invalid(self):
        with pytest.raises(Exception):
            EmailChunk(
                chunk_id="chunk_001",
                employee_id="emp_001",
                thread_id="thread_001",
                subject="Test",
                date=datetime(2023, 1, 1),
                author_role="sender",
                content="test",
            )


class TestQueryResult:
    def test_create_query_result_minimal(self):
        result = QueryResult(answer="The system uses Kafka for event streaming.")
        assert result.answer == "The system uses Kafka for event streaming."
        assert result.sources == []
        assert result.confidence == 0.0
        assert result.staleness_warning is None

    def test_create_query_result_with_sources_and_staleness(self):
        result = QueryResult(
            answer="The deployment uses blue-green strategy.",
            sources=[
                ChunkReference(
                    chunk_id="chunk_042",
                    date="2023-01-10",
                    subject="Re: Deployment strategy",
                    content_preview="We decided on blue-green...",
                )
            ],
            confidence=0.87,
            staleness_warning="Sources are older than 18 months.",
        )
        assert len(result.sources) == 1
        assert result.sources[0].chunk_id == "chunk_042"
        assert result.staleness_warning is not None
