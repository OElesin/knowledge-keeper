"""Unit tests for shared S3 Vectors client wrapper."""
from unittest.mock import MagicMock

import pytest

from shared import s3vectors_client


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    monkeypatch.setattr(s3vectors_client, "VECTOR_BUCKET_NAME", "kk-test")
    monkeypatch.setattr(s3vectors_client, "VECTOR_INDEX_NAME", "kk-test-chunks")


class TestPutVectors:
    def test_put_vectors_calls_client_with_correct_params(self):
        mock_client = MagicMock()
        mock_client.put_vectors.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}

        vectors = [{
            "key": "chunk_001",
            "data": {"float32": [0.1] * 1024},
            "metadata": {"employee_id": "emp_001", "date": "2024-01-15"},
        }]

        result = s3vectors_client.put_vectors(vectors, client=mock_client)

        mock_client.put_vectors.assert_called_once_with(
            vectorBucketName="kk-test",
            indexName="kk-test-chunks",
            vectors=vectors,
        )
        assert result["ResponseMetadata"]["HTTPStatusCode"] == 200

    def test_put_vectors_with_custom_bucket_and_index(self):
        mock_client = MagicMock()
        mock_client.put_vectors.return_value = {}

        s3vectors_client.put_vectors(
            [{"key": "c1", "data": {"float32": [0.0]}, "metadata": {}}],
            bucket_name="custom-bucket",
            index_name="custom-index",
            client=mock_client,
        )

        call_kwargs = mock_client.put_vectors.call_args.kwargs
        assert call_kwargs["vectorBucketName"] == "custom-bucket"
        assert call_kwargs["indexName"] == "custom-index"


class TestQueryVectors:
    def test_query_vectors_calls_client_with_correct_params(self):
        mock_client = MagicMock()
        mock_client.query_vectors.return_value = {"vectors": []}

        query_emb = [0.5] * 1024
        result = s3vectors_client.query_vectors(
            query_emb,
            filter_expr={"employee_id": "emp_001"},
            top_k=5,
            client=mock_client,
        )

        call_kwargs = mock_client.query_vectors.call_args.kwargs
        assert call_kwargs["vectorBucketName"] == "kk-test"
        assert call_kwargs["indexName"] == "kk-test-chunks"
        assert call_kwargs["queryVector"] == {"float32": query_emb}
        assert call_kwargs["topK"] == 5
        assert call_kwargs["filter"] == {"employee_id": "emp_001"}
        assert call_kwargs["returnDistance"] is True
        assert call_kwargs["returnMetadata"] is True

    def test_query_vectors_without_filter(self):
        mock_client = MagicMock()
        mock_client.query_vectors.return_value = {"vectors": []}

        s3vectors_client.query_vectors([0.1] * 1024, client=mock_client)

        call_kwargs = mock_client.query_vectors.call_args.kwargs
        assert "filter" not in call_kwargs


class TestDeleteVectors:
    def test_delete_vectors_calls_client_with_correct_params(self):
        mock_client = MagicMock()
        mock_client.delete_vectors.return_value = {}

        keys = ["chunk_001", "chunk_002"]
        s3vectors_client.delete_vectors(keys, client=mock_client)

        mock_client.delete_vectors.assert_called_once_with(
            vectorBucketName="kk-test",
            indexName="kk-test-chunks",
            keys=keys,
        )
