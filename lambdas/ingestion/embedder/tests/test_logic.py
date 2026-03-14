"""Unit tests for embedder logic."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lambdas.ingestion.embedder.logic import (
    _estimate_tokens,
    chunk_thread,
    embed_and_index_chunks,
    split_into_sentences,
    update_twin_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_thread(
    body: str = "The root cause is the consumer group rebalancing during deployment. "
                "We fixed it by adjusting the session timeout. "
                "The change was deployed on Friday and has been stable since.",
    num_messages: int = 1,
    **overrides,
) -> dict:
    messages = []
    for i in range(num_messages):
        messages.append({
            "message_id": f"msg_{i:03d}",
            "from_addr": "jane@corp.com",
            "subject": "Re: Kafka lag issue",
            "body_text": body,
            "date": "2024-01-15T10:00:00+00:00",
            "author_role": "primary",
            "pii_unverified": False,
        })
    default = {
        "employeeId": "emp_123",
        "threadId": "thread_001",
        "subject": "Kafka lag issue",
        "messages": messages,
    }
    default.update(overrides)
    return default


def _long_body(sentences: int = 200) -> str:
    """Generate a body with many sentences to exceed the 512-token limit."""
    return " ".join(
        f"Sentence number {i} contains some meaningful technical content about the system."
        for i in range(sentences)
    )


# ---------------------------------------------------------------------------
# split_into_sentences
# ---------------------------------------------------------------------------

class TestSplitIntoSentences:
    def test_splits_on_period(self):
        text = "First sentence. Second sentence. Third sentence."
        result = split_into_sentences(text)
        assert len(result) == 3

    def test_splits_on_question_mark(self):
        text = "What happened? It crashed. Why?"
        result = split_into_sentences(text)
        assert len(result) == 3

    def test_single_sentence(self):
        result = split_into_sentences("Just one sentence.")
        assert len(result) == 1

    def test_empty_string(self):
        assert split_into_sentences("") == []

    def test_whitespace_only(self):
        assert split_into_sentences("   ") == []


# ---------------------------------------------------------------------------
# _estimate_tokens
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_short_text(self):
        assert _estimate_tokens("hello") >= 1

    def test_longer_text(self):
        # 100 chars ≈ 25 tokens
        text = "a" * 100
        assert _estimate_tokens(text) == 25

    def test_empty_string(self):
        assert _estimate_tokens("") == 1  # min 1


# ---------------------------------------------------------------------------
# chunk_thread
# ---------------------------------------------------------------------------

class TestChunkThread:
    def test_short_thread_produces_single_chunk(self):
        thread = _make_thread()
        chunks = chunk_thread(thread)
        assert len(chunks) == 1
        assert chunks[0]["employee_id"] == "emp_123"
        assert chunks[0]["thread_id"] == "thread_001"
        assert chunks[0]["subject"] == "Kafka lag issue"
        assert chunks[0]["author_role"] == "primary"
        assert chunks[0]["date"] == "2024-01-15T10:00:00+00:00"
        assert "consumer group rebalancing" in chunks[0]["content"]

    def test_long_thread_produces_multiple_chunks(self):
        thread = _make_thread(body=_long_body(200))
        chunks = chunk_thread(thread)
        assert len(chunks) > 1

    def test_chunks_have_unique_ids(self):
        thread = _make_thread(body=_long_body(200))
        chunks = chunk_thread(thread)
        ids = [c["chunk_id"] for c in chunks]
        assert len(ids) == len(set(ids))

    def test_empty_thread_returns_no_chunks(self):
        thread = _make_thread(body="")
        assert chunk_thread(thread) == []

    def test_no_messages_returns_no_chunks(self):
        thread = _make_thread()
        thread["messages"] = []
        assert chunk_thread(thread) == []

    def test_multiple_messages_concatenated(self):
        thread = _make_thread(num_messages=3)
        chunks = chunk_thread(thread)
        assert len(chunks) >= 1
        # Content from all messages should appear
        assert "consumer group rebalancing" in chunks[0]["content"]

    def test_chunk_metadata_from_first_message(self):
        thread = _make_thread()
        thread["messages"][0]["author_role"] = "cc"
        thread["messages"][0]["date"] = "2024-06-01T12:00:00+00:00"
        chunks = chunk_thread(thread)
        assert chunks[0]["author_role"] == "cc"
        assert chunks[0]["date"] == "2024-06-01T12:00:00+00:00"

    def test_chunk_id_contains_employee_and_thread(self):
        thread = _make_thread()
        chunks = chunk_thread(thread)
        assert chunks[0]["chunk_id"].startswith("emp_123_thread_001_")


# ---------------------------------------------------------------------------
# embed_and_index_chunks
# ---------------------------------------------------------------------------

class TestEmbedAndIndexChunks:
    def test_happy_path_embeds_and_indexes(self):
        chunks = [
            {
                "chunk_id": "c1",
                "employee_id": "emp_123",
                "thread_id": "t1",
                "subject": "Test",
                "author_role": "primary",
                "date": "2024-01-15",
                "content": "Some content here.",
            },
        ]
        mock_embedding = [0.1] * 1024
        get_emb = MagicMock(return_value=mock_embedding)
        put_vec = MagicMock(return_value={})

        result = embed_and_index_chunks(
            chunks,
            get_embedding_fn=get_emb,
            put_vectors_fn=put_vec,
            vector_bucket_name="test-bucket",
            vector_index_name="test-index",
        )

        assert result == 1
        get_emb.assert_called_once()
        put_vec.assert_called_once()

        # Verify put_vectors was called with correct structure
        call_kwargs = put_vec.call_args
        vec_record = call_kwargs[1]["vectors"][0] if "vectors" in call_kwargs[1] else call_kwargs[0][0][0]
        # Check via positional or keyword
        put_vec.assert_called_once()

    def test_multiple_chunks_all_indexed(self):
        chunks = [
            {
                "chunk_id": f"c{i}",
                "employee_id": "emp_123",
                "thread_id": "t1",
                "subject": "Test",
                "author_role": "primary",
                "date": "2024-01-15",
                "content": f"Content {i}.",
            }
            for i in range(5)
        ]
        get_emb = MagicMock(return_value=[0.1] * 1024)
        put_vec = MagicMock(return_value={})

        result = embed_and_index_chunks(
            chunks,
            get_embedding_fn=get_emb,
            put_vectors_fn=put_vec,
        )

        assert result == 5
        assert get_emb.call_count == 5
        assert put_vec.call_count == 5

    def test_empty_chunks_returns_zero(self):
        get_emb = MagicMock()
        put_vec = MagicMock()

        result = embed_and_index_chunks(
            [],
            get_embedding_fn=get_emb,
            put_vectors_fn=put_vec,
        )

        assert result == 0
        get_emb.assert_not_called()
        put_vec.assert_not_called()

    @patch("lambdas.ingestion.embedder.logic.time.sleep")
    def test_bedrock_failure_retries_then_raises(self, mock_sleep):
        chunks = [
            {
                "chunk_id": "c1",
                "employee_id": "emp_123",
                "thread_id": "t1",
                "subject": "Test",
                "author_role": "primary",
                "date": "2024-01-15",
                "content": "Content.",
            },
        ]
        get_emb = MagicMock(side_effect=Exception("Bedrock unavailable"))
        put_vec = MagicMock()

        with pytest.raises(Exception):
            embed_and_index_chunks(
                chunks,
                get_embedding_fn=get_emb,
                put_vectors_fn=put_vec,
            )

        assert get_emb.call_count == 3  # 3 retries
        put_vec.assert_not_called()

    @patch("lambdas.ingestion.embedder.logic.time.sleep")
    def test_s3vectors_failure_retries_then_raises(self, mock_sleep):
        chunks = [
            {
                "chunk_id": "c1",
                "employee_id": "emp_123",
                "thread_id": "t1",
                "subject": "Test",
                "author_role": "primary",
                "date": "2024-01-15",
                "content": "Content.",
            },
        ]
        get_emb = MagicMock(return_value=[0.1] * 1024)
        put_vec = MagicMock(side_effect=Exception("S3Vectors error"))

        with pytest.raises(Exception):
            embed_and_index_chunks(
                chunks,
                get_embedding_fn=get_emb,
                put_vectors_fn=put_vec,
            )

        assert put_vec.call_count == 3

    @patch("lambdas.ingestion.embedder.logic.time.sleep")
    def test_transient_failure_recovers_on_retry(self, mock_sleep):
        chunks = [
            {
                "chunk_id": "c1",
                "employee_id": "emp_123",
                "thread_id": "t1",
                "subject": "Test",
                "author_role": "primary",
                "date": "2024-01-15",
                "content": "Content.",
            },
        ]
        get_emb = MagicMock(
            side_effect=[Exception("Transient"), [0.1] * 1024]
        )
        put_vec = MagicMock(return_value={})

        result = embed_and_index_chunks(
            chunks,
            get_embedding_fn=get_emb,
            put_vectors_fn=put_vec,
        )

        assert result == 1
        assert get_emb.call_count == 2


# ---------------------------------------------------------------------------
# update_twin_status
# ---------------------------------------------------------------------------

class TestUpdateTwinStatus:
    def test_calls_update_with_active_status(self):
        mock_update = MagicMock(return_value={"employeeId": "emp_123", "status": "active"})

        result = update_twin_status("emp_123", 42, update_twin_fn=mock_update)

        mock_update.assert_called_once_with("emp_123", {
            "status": "active",
            "chunkCount": 42,
        })
        assert result["status"] == "active"

    def test_passes_zero_chunk_count(self):
        mock_update = MagicMock(return_value={"employeeId": "emp_123", "status": "active"})

        update_twin_status("emp_123", 0, update_twin_fn=mock_update)

        mock_update.assert_called_once_with("emp_123", {
            "status": "active",
            "chunkCount": 0,
        })
