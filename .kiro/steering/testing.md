---
inclusion: fileMatch
fileMatchPattern: "**/*.py"
---

# KnowledgeKeeper — Testing Standards

## Testing Philosophy

Every Lambda function has two layers: a thin `handler.py` (handles AWS event parsing) and a `logic.py` (pure Python business logic). **Unit tests target `logic.py` only.** Handlers are tested via integration tests.

## Unit Test Standards

- **Framework**: `pytest`
- **AWS Mocking**: `moto` for all AWS service calls (S3, DynamoDB, SQS, Comprehend)
- **Bedrock Mocking**: `unittest.mock.patch` — Bedrock is not supported by moto
- **Coverage target**: 80% minimum on `logic.py` files
- **Test file location**: `lambdas/{layer}/{function}/tests/test_logic.py`

## Test Structure Pattern

```python
# tests/test_logic.py
import pytest
from moto import mock_aws
from unittest.mock import patch, MagicMock
from logic import process_thread  # import the pure function

@pytest.fixture
def sample_thread():
    return {
        "thread_id": "thread_001",
        "messages": [
            {
                "message_id": "msg_001",
                "from": "jane@corp.com",
                "subject": "Re: Kafka lag issue",
                "body_text": "The root cause is the consumer group rebalancing...",
                "date": "2023-03-15T10:00:00Z"
            }
        ]
    }

class TestProcessThread:
    def test_strips_signature(self, sample_thread):
        # Arrange
        sample_thread["messages"][0]["body_text"] += "\n\nBest,\nJane Smith\nSenior SRE"
        # Act
        result = process_thread(sample_thread)
        # Assert
        assert "Best,\nJane Smith" not in result["cleaned_text"]

    def test_discards_short_threads(self, sample_thread):
        sample_thread["messages"][0]["body_text"] = "Thanks!"
        result = process_thread(sample_thread)
        assert result is None  # discarded
```

## Fixture Files

- Keep representative .eml and .mbox fixtures in `tests/fixtures/`
- Create fixtures for: typical technical thread, noisy calendar thread, thread with PII, very long thread (> 512 tokens), orphaned reply (no parent)
- Never use real employee data in fixtures — use synthetic data only

## Integration Test Standards

- Integration tests live in `tests/integration/`
- They test full Lambda handler → AWS service chains
- Use LocalStack where possible; use real AWS dev account for OpenSearch
- Integration tests are not run in CI on every PR — only on merge to `main`

## What Kiro Must Always Do When Writing Tests

1. Test the happy path first
2. Test the most likely failure modes (API errors, empty responses, malformed input)
3. Test boundary conditions (0 emails, 1 email, max batch size)
4. Never test implementation details — test observable behaviour
5. Each test method tests exactly one thing
6. Use descriptive test names: `test_{what}_{when}_{expected}`
