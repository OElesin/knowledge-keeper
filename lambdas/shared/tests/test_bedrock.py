"""Unit tests for shared Bedrock wrappers."""
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from shared.bedrock import get_embedding, generate_response


class TestGetEmbedding:
    def test_returns_embedding_vector(self):
        mock_embedding = [0.1] * 1024
        response_body = json.dumps({
            "embeddings": [{"embedding": mock_embedding}]
        }).encode()

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {
            "body": BytesIO(response_body),
        }

        result = get_embedding("test text", "GENERIC_INDEX", client=mock_client)

        assert result == mock_embedding
        assert len(result) == 1024

    def test_passes_correct_params_for_index(self):
        mock_embedding = [0.0] * 1024
        response_body = json.dumps({
            "embeddings": [{"embedding": mock_embedding}]
        }).encode()

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {
            "body": BytesIO(response_body),
        }

        get_embedding("hello world", "GENERIC_INDEX", client=mock_client)

        call_args = mock_client.invoke_model.call_args
        body = json.loads(call_args.kwargs["body"])
        assert body["taskType"] == "SINGLE_EMBEDDING"
        assert body["singleEmbeddingParams"]["embeddingPurpose"] == "GENERIC_INDEX"
        assert body["singleEmbeddingParams"]["embeddingDimension"] == 1024
        assert body["text"]["value"] == "hello world"
        assert body["text"]["truncationMode"] == "END"

    def test_passes_correct_params_for_retrieval(self):
        mock_embedding = [0.0] * 1024
        response_body = json.dumps({
            "embeddings": [{"embedding": mock_embedding}]
        }).encode()

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {
            "body": BytesIO(response_body),
        }

        get_embedding("query text", "GENERIC_RETRIEVAL", client=mock_client)

        call_args = mock_client.invoke_model.call_args
        body = json.loads(call_args.kwargs["body"])
        assert body["singleEmbeddingParams"]["embeddingPurpose"] == "GENERIC_RETRIEVAL"


class TestGenerateResponse:
    def test_returns_generated_text(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "The system uses Kafka."}]
                }
            }
        }

        result = generate_response(
            system_prompt="You are a helpful assistant.",
            user_message="What messaging system is used?",
            client=mock_client,
        )

        assert result == "The system uses Kafka."

    def test_passes_correct_converse_params(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "answer"}]
                }
            }
        }

        generate_response(
            system_prompt="system",
            user_message="user query",
            client=mock_client,
            max_tokens=512,
        )

        call_args = mock_client.converse.call_args
        assert call_args.kwargs["system"] == [{"text": "system"}]
        assert call_args.kwargs["messages"][0]["role"] == "user"
        assert call_args.kwargs["messages"][0]["content"] == [{"text": "user query"}]
        assert call_args.kwargs["inferenceConfig"]["maxTokens"] == 512
