"""Unit tests for cleaner logic."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lambdas.ingestion.cleaner.logic import (
    clean_message_body,
    clean_thread,
    is_calendar_invite,
    redact_pii,
    strip_disclaimer,
    strip_signature,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_thread(messages: list[dict] | None = None) -> dict:
    """Build a minimal thread payload."""
    if messages is None:
        messages = [_make_message()]
    return {
        "employeeId": "emp_123",
        "threadId": "thread_001",
        "subject": "Kafka lag issue",
        "messages": messages,
    }


def _make_message(
    body: str = "The root cause is the consumer group rebalancing during deployment.",
    **overrides,
) -> dict:
    default = {
        "message_id": "msg_001",
        "from_addr": "jane@corp.com",
        "subject": "Re: Kafka lag issue",
        "body_text": body,
        "date": "2024-01-15T10:00:00+00:00",
        "author_role": "primary",
        "content_type": "text/plain",
    }
    default.update(overrides)
    return default


def _mock_comprehend(entities: list[dict] | None = None):
    """Return a mock Comprehend client with canned detect_pii_entities."""
    client = MagicMock()
    client.detect_pii_entities.return_value = {
        "Entities": entities or [],
    }
    return client


def _mock_comprehend_error():
    """Return a mock Comprehend client that raises on detect_pii_entities."""
    client = MagicMock()
    client.detect_pii_entities.side_effect = Exception("Service unavailable")
    return client


# ---------------------------------------------------------------------------
# strip_signature
# ---------------------------------------------------------------------------

class TestStripSignature:
    def test_strips_best_regards(self):
        text = "Important info here.\n\nBest,\nJane Smith\nSenior SRE"
        result = strip_signature(text)
        assert "Important info here." in result
        assert "Jane Smith" not in result

    def test_strips_double_dash(self):
        text = "Content above.\n-- \nJane Smith"
        result = strip_signature(text)
        assert "Content above." in result
        assert "Jane Smith" not in result

    def test_strips_thanks(self):
        text = "Here is the info.\n\nThanks,\nBob"
        result = strip_signature(text)
        assert "Here is the info." in result
        assert "Bob" not in result

    def test_no_signature_returns_unchanged(self):
        text = "Just a normal message with no sign-off pattern."
        assert strip_signature(text) == text

    def test_empty_string(self):
        assert strip_signature("") == ""


# ---------------------------------------------------------------------------
# strip_disclaimer
# ---------------------------------------------------------------------------

class TestStripDisclaimer:
    def test_strips_confidentiality_notice(self):
        text = (
            "Real content here.\n\n"
            "CONFIDENTIALITY NOTICE: This email is intended only for the "
            "named recipient. If you are not the intended recipient, "
            "please delete this email."
        )
        result = strip_disclaimer(text)
        assert "Real content here." in result
        assert "CONFIDENTIALITY NOTICE" not in result

    def test_strips_this_email_is_confidential(self):
        text = (
            "Actual message.\n\n"
            "This email is confidential and may be privileged. "
            "If you received this in error, please notify the sender."
        )
        result = strip_disclaimer(text)
        assert "Actual message." in result
        assert "confidential" not in result

    def test_no_disclaimer_returns_unchanged(self):
        text = "Normal email body without any legal text."
        assert strip_disclaimer(text) == text


# ---------------------------------------------------------------------------
# is_calendar_invite
# ---------------------------------------------------------------------------

class TestIsCalendarInvite:
    def test_calendar_invite_detected(self):
        msg = _make_message(content_type="text/calendar; method=REQUEST")
        assert is_calendar_invite(msg) is True

    def test_plain_text_not_calendar(self):
        msg = _make_message(content_type="text/plain")
        assert is_calendar_invite(msg) is False

    def test_missing_content_type(self):
        msg = _make_message()
        del msg["content_type"]
        msg["content_type"] = ""
        assert is_calendar_invite(msg) is False


# ---------------------------------------------------------------------------
# clean_message_body
# ---------------------------------------------------------------------------

class TestCleanMessageBody:
    def test_strips_signature_and_disclaimer(self):
        body = (
            "Important technical detail about the migration.\n\n"
            "Best,\nJane\n\n"
            "CONFIDENTIALITY NOTICE: This is privileged."
        )
        result = clean_message_body(body)
        assert "Important technical detail" in result
        assert "Best," not in result
        assert "CONFIDENTIALITY" not in result

    def test_preserves_clean_body(self):
        body = "This is a perfectly clean message with enough content to pass."
        assert clean_message_body(body) == body


# ---------------------------------------------------------------------------
# redact_pii
# ---------------------------------------------------------------------------

class TestRedactPii:
    def test_redacts_ssn(self):
        text = "My SSN is 123-45-6789 and that is private."
        client = _mock_comprehend([
            {"Type": "SSN", "BeginOffset": 10, "EndOffset": 21, "Score": 0.99},
        ])
        result, unverified = redact_pii(text, client)
        assert "[REDACTED-SSN]" in result
        assert "123-45-6789" not in result
        assert unverified is False

    def test_redacts_multiple_entities(self):
        text = "SSN: 111-22-3333, Card: 4111111111111111"
        client = _mock_comprehend([
            {"Type": "SSN", "BeginOffset": 5, "EndOffset": 16, "Score": 0.99},
            {"Type": "CREDIT_DEBIT_NUMBER", "BeginOffset": 24, "EndOffset": 40, "Score": 0.99},
        ])
        result, unverified = redact_pii(text, client)
        assert "[REDACTED-SSN]" in result
        assert "[REDACTED-CREDIT_DEBIT_NUMBER]" in result
        assert unverified is False

    def test_ignores_non_target_pii_types(self):
        text = "Contact jane@corp.com for details."
        client = _mock_comprehend([
            {"Type": "EMAIL", "BeginOffset": 8, "EndOffset": 21, "Score": 0.99},
        ])
        result, unverified = redact_pii(text, client)
        assert result == text  # EMAIL is not in our redact set
        assert unverified is False

    def test_no_entities_returns_unchanged(self):
        text = "Nothing sensitive here at all."
        client = _mock_comprehend([])
        result, unverified = redact_pii(text, client)
        assert result == text
        assert unverified is False

    def test_comprehend_failure_flags_unverified(self):
        text = "Some text that cannot be checked."
        client = _mock_comprehend_error()
        result, unverified = redact_pii(text, client)
        assert result == text
        assert unverified is True

    def test_no_client_flags_unverified(self):
        text = "No client provided."
        result, unverified = redact_pii(text, None)
        assert result == text
        assert unverified is True


# ---------------------------------------------------------------------------
# clean_thread
# ---------------------------------------------------------------------------

class TestCleanThread:
    def test_happy_path_cleans_and_returns_thread(self):
        thread = _make_thread()
        client = _mock_comprehend()
        result = clean_thread(thread, client)
        assert result is not None
        assert result["employeeId"] == "emp_123"
        assert len(result["messages"]) == 1
        assert result["messages"][0]["pii_unverified"] is False

    def test_discards_short_messages(self):
        thread = _make_thread([_make_message(body="Too short.")])
        client = _mock_comprehend()
        result = clean_thread(thread, client)
        assert result is None

    def test_discards_calendar_invites(self):
        thread = _make_thread([
            _make_message(content_type="text/calendar; method=REQUEST"),
        ])
        client = _mock_comprehend()
        result = clean_thread(thread, client)
        assert result is None

    def test_mixed_messages_keeps_valid_discards_short(self):
        messages = [
            _make_message(body="Short."),
            _make_message(
                body="This message has enough content to survive the minimum length filter easily.",
                message_id="msg_002",
            ),
        ]
        thread = _make_thread(messages)
        client = _mock_comprehend()
        result = clean_thread(thread, client)
        assert result is not None
        assert len(result["messages"]) == 1
        assert result["messages"][0]["message_id"] == "msg_002"

    def test_pii_redaction_applied(self):
        body = "My SSN is 123-45-6789 and I need help with the deployment process today."
        thread = _make_thread([_make_message(body=body)])
        client = _mock_comprehend([
            {"Type": "SSN", "BeginOffset": 10, "EndOffset": 21, "Score": 0.99},
        ])
        result = clean_thread(thread, client)
        assert result is not None
        assert "[REDACTED-SSN]" in result["messages"][0]["body_text"]

    def test_comprehend_failure_flags_pii_unverified(self):
        thread = _make_thread()
        client = _mock_comprehend_error()
        result = clean_thread(thread, client)
        assert result is not None
        assert result["messages"][0]["pii_unverified"] is True

    def test_empty_thread_returns_none(self):
        thread = _make_thread([])
        client = _mock_comprehend()
        result = clean_thread(thread, client)
        assert result is None

    def test_signature_stripped_before_length_check(self):
        # Body is long enough only because of the signature.
        # After stripping, it should be < 50 chars and get discarded.
        body = "Hi.\n\nBest,\nJane Smith\nSenior SRE at Corp Inc, Platform Team"
        thread = _make_thread([_make_message(body=body)])
        client = _mock_comprehend()
        result = clean_thread(thread, client)
        assert result is None

    def test_preserves_thread_metadata(self):
        thread = _make_thread()
        client = _mock_comprehend()
        result = clean_thread(thread, client)
        assert result["threadId"] == "thread_001"
        assert result["subject"] == "Kafka lag issue"
