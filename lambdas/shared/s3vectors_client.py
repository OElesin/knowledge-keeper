"""S3 Vectors client wrapper for put, query, and delete operations."""
from __future__ import annotations

import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)

VECTOR_BUCKET_NAME = os.environ.get("VECTOR_BUCKET_NAME", "")
VECTOR_INDEX_NAME = os.environ.get("VECTOR_INDEX_NAME", "")


def _get_client():
    """Return an S3 Vectors client."""
    return boto3.client("s3vectors")


def put_vectors(
    vectors: list[dict[str, Any]],
    bucket_name: str | None = None,
    index_name: str | None = None,
    client=None,
) -> dict:
    """Store vectors in S3 Vectors index.

    Args:
        vectors: List of vector dicts, each with:
            - key: unique chunk ID
            - data: {"float32": [floats]}
            - metadata: dict of filterable/non-filterable keys
        bucket_name: Override vector bucket name.
        index_name: Override vector index name.
        client: Optional pre-configured s3vectors client.

    Returns:
        The put_vectors API response.
    """
    if client is None:
        client = _get_client()

    return client.put_vectors(
        vectorBucketName=bucket_name or VECTOR_BUCKET_NAME,
        indexName=index_name or VECTOR_INDEX_NAME,
        vectors=vectors,
    )


def query_vectors(
    query_embedding: list[float],
    filter_expr: dict[str, str] | None = None,
    top_k: int = 10,
    bucket_name: str | None = None,
    index_name: str | None = None,
    client=None,
) -> list[dict]:
    """Query S3 Vectors index for similar vectors.

    Args:
        query_embedding: The query vector (1024-dim float32).
        filter_metadata: Metadata filter (e.g. {"employee_id": "emp_123"}).
        top_k: Number of results to return.
        bucket_name: Override vector bucket name.
        index_name: Override vector index name.
        client: Optional pre-configured s3vectors client.

    Returns:
        List of matching vector results with metadata and distances.
    """
    if client is None:
        client = _get_client()

    kwargs: dict[str, Any] = {
        "vectorBucketName": bucket_name or VECTOR_BUCKET_NAME,
        "indexName": index_name or VECTOR_INDEX_NAME,
        "queryVector": {"float32": query_embedding},
        "topK": top_k,
        "returnDistance": True,
        "returnMetadata": True,
    }
    if filter_expr:
        kwargs["filter"] = filter_expr

    response = client.query_vectors(**kwargs)
    return response.get("vectors", [])


def delete_vectors(
    keys: list[str],
    bucket_name: str | None = None,
    index_name: str | None = None,
    client=None,
) -> dict:
    """Delete vectors by their keys from S3 Vectors index.

    Args:
        keys: List of chunk IDs to delete.
        bucket_name: Override vector bucket name.
        index_name: Override vector index name.
        client: Optional pre-configured s3vectors client.

    Returns:
        The delete_vectors API response.
    """
    if client is None:
        client = _get_client()

    return client.delete_vectors(
        vectorBucketName=bucket_name or VECTOR_BUCKET_NAME,
        indexName=index_name or VECTOR_INDEX_NAME,
        keys=keys,
    )
