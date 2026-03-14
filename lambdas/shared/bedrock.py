"""Bedrock client wrappers for Nova Embeddings and Nova Pro generation."""
from __future__ import annotations

import json
import logging
from typing import Literal

import boto3

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_ID = "amazon.nova-2-multimodal-embeddings-v1:0"
GENERATION_MODEL_ID = "amazon.nova-pro-v1:0"


def _get_bedrock_client():
    """Return a Bedrock Runtime client."""
    return boto3.client("bedrock-runtime")


def get_embedding(
    text: str,
    purpose: Literal["GENERIC_INDEX", "GENERIC_RETRIEVAL"] = "GENERIC_INDEX",
    dimension: int = 1024,
    client=None,
) -> list[float]:
    """Generate a single embedding using Nova Multimodal Embeddings.

    Args:
        text: The text to embed.
        purpose: GENERIC_INDEX for indexing, GENERIC_RETRIEVAL for querying.
        dimension: Embedding dimension (default 1024).
        client: Optional pre-configured bedrock-runtime client.

    Returns:
        List of floats representing the embedding vector.
    """
    if client is None:
        client = _get_bedrock_client()

    body = json.dumps({
        "taskType": "SINGLE_EMBEDDING",
        "singleEmbeddingParams": {
            "embeddingPurpose": purpose,
            "embeddingDimension": dimension,
        },
        "text": {
            "truncationMode": "END",
            "value": text,
        },
    })

    response = client.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )

    response_body = json.loads(response["body"].read())
    return response_body["embeddings"][0]["embedding"]


def generate_response(
    system_prompt: str,
    user_message: str,
    client=None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> str:
    """Generate a response using Amazon Nova Pro via the Converse API.

    Args:
        system_prompt: System instructions for the model.
        user_message: The user's query with context.
        client: Optional pre-configured bedrock-runtime client.
        max_tokens: Maximum tokens in the response.
        temperature: Sampling temperature.

    Returns:
        The generated text response.
    """
    if client is None:
        client = _get_bedrock_client()

    response = client.converse(
        modelId=GENERATION_MODEL_ID,
        system=[{"text": system_prompt}],
        messages=[
            {
                "role": "user",
                "content": [{"text": user_message}],
            }
        ],
        inferenceConfig={
            "maxTokens": max_tokens,
            "temperature": temperature,
        },
    )

    return response["output"]["message"]["content"][0]["text"]
