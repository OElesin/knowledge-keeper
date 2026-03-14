"""Unit tests for parser logic."""
from __future__ import annotations

import email
import mailbox
import tempfile
from datetime import datetime, timezone

import pytest

from lambdas.ingestion.parser.logic import (
    build_thread_payload,
    identify_author_role,
    parse_mbox_bytes,
    reconstruct_threads,
    _strip_html,
    _parse_date,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mbox_bytes(*raw_messages: str) -> bytes:
    """Create an .mbox file in memory from raw RFC 2822 message strings."""
    with tempfile.NamedTemporaryFile(suffix=".mbox") as tmp:
        mbox = mailbox.mbox(tmp.name)
        for raw in raw_messages:
            msg = email.message_from_string(raw)
            mbox.add(msg)
        mbox.flush()
        tmp.seek(0)
        return tmp.read()


SIMPLE_EMAIL = """\
From: jane@corp.com
To: bob@corp.com
Subject: Kafka lag issue
Message-ID: <msg001@corp.com>
Date: Mon, 15 Jan 2024 10:00:00 +0000
Content-Type: text/plain

The root cause is the consumer group rebalancing.
"""

REPLY_EMAIL = """\
From: bob@corp.com
To: jane@corp.com
Subject: Re: Kafka lag issue
Message-ID: <msg002@corp.com>
In-Reply-To: <msg001@corp.com>
Date: Mon, 15 Jan 2024 11:00:00 +0000
Content-Type: text/plain

Thanks for the analysis. Should we increase partitions?
"""

SECOND_REPLY_EMAIL = """\
From: jane@corp.com
To: bob@corp.com
Cc: alice@corp.com
Subject: Re: Re: Kafka lag issue
Message-ID: <msg003@corp.com>
In-Reply-To: <msg002@corp.com>
Date: Mon, 15 Jan 2024 12:00:00 +0000
Content-Type: text/plain

Yes, let's bump to 12 partitions. I'll handle the migration.
"""

HTML_EMAIL = """\
From: jane@corp.com
To: bob@corp.com
Subject: HTML test
Message-ID: <msg_html@corp.com>
Date: Mon, 15 Jan 2024 10:00:00 +0000
Content-Type: text/html

<html><body><p>Hello <b>world</b></p><p>Second paragraph</p></body></html>
"""

NO_MESSAGE_ID_EMAIL = """\
From: jane@corp.com
To: bob@corp.com
Subject: Missing ID
Date: Mon, 15 Jan 2024 10:00:00 +0000
Content-Type: text/plain

This email has no Message-ID header.
"""


# ---------------------------------------------------------------------------
# parse_mbox_bytes
# ---------------------------------------------------------------------------

class TestParseMboxBytes:
    def test_parses_single_email(self):
        mbox_data = _make_mbox_bytes(SIMPLE_EMAIL)
        result = parse_mbox_bytes(mbox_data)
        assert len(result) == 1
        msg = result[0]
        assert msg["message_id"] == "<msg001@corp.com>"
        assert msg["subject"] == "Kafka lag issue"
        assert msg["from_addr"] == "jane@corp.com"
        assert msg["to"] == "bob@corp.com"
        assert "consumer group rebalancing" in msg["body_text"]

    def test_parses_multiple_emails(self):
        mbox_data = _make_mbox_bytes(SIMPLE_EMAIL, REPLY_EMAIL)
        result = parse_mbox_bytes(mbox_data)
        assert len(result) == 2

    def test_extracts_in_reply_to(self):
        mbox_data = _make_mbox_bytes(REPLY_EMAIL)
        result = parse_mbox_bytes(mbox_data)
        assert result[0]["in_reply_to"] == "<msg001@corp.com>"

    def test_strips_html_body(self):
        mbox_data = _make_mbox_bytes(HTML_EMAIL)
        result = parse_mbox_bytes(mbox_data)
        body = result[0]["body_text"]
        assert "<html>" not in body
        assert "<b>" not in body
        assert "Hello" in body
        assert "world" in body

    def test_skips_messages_without_message_id(self):
        mbox_data = _make_mbox_bytes(NO_MESSAGE_ID_EMAIL)
        result = parse_mbox_bytes(mbox_data)
        assert len(result) == 0

    def test_empty_mbox_returns_empty(self):
        mbox_data = _make_mbox_bytes()
        result = parse_mbox_bytes(mbox_data)
        assert result == []

    def test_parses_date_to_iso(self):
        mbox_data = _make_mbox_bytes(SIMPLE_EMAIL)
        result = parse_mbox_bytes(mbox_data)
        date_str = result[0]["date"]
        assert date_str != ""
        # Should be parseable as ISO 8601
        dt = datetime.fromisoformat(date_str)
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------

class TestStripHtml:
    def test_removes_tags(self):
        assert "Hello" in _strip_html("<p>Hello</p>")
        assert "<p>" not in _strip_html("<p>Hello</p>")

    def test_preserves_whitespace_between_blocks(self):
        result = _strip_html("<p>First</p><p>Second</p>")
        assert "First" in result
        assert "Second" in result

    def test_empty_html(self):
        assert _strip_html("") == ""


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_valid_rfc2822_date(self):
        result = _parse_date("Mon, 15 Jan 2024 10:00:00 +0000")
        assert "2024-01-15" in result

    def test_empty_string_returns_empty(self):
        assert _parse_date("") == ""

    def test_invalid_date_returns_empty(self):
        assert _parse_date("not a date") == ""


# ---------------------------------------------------------------------------
# reconstruct_threads
# ---------------------------------------------------------------------------

class TestReconstructThreads:
    def test_single_message_becomes_single_thread(self):
        messages = [
            {"message_id": "<a>", "in_reply_to": "", "date": "2024-01-01"},
        ]
        threads = reconstruct_threads(messages)
        assert len(threads) == 1
        assert len(threads[0]) == 1

    def test_reply_chain_grouped_into_one_thread(self):
        messages = [
            {"message_id": "<a>", "in_reply_to": "", "date": "2024-01-01T10:00:00"},
            {"message_id": "<b>", "in_reply_to": "<a>", "date": "2024-01-01T11:00:00"},
            {"message_id": "<c>", "in_reply_to": "<b>", "date": "2024-01-01T12:00:00"},
        ]
        threads = reconstruct_threads(messages)
        assert len(threads) == 1
        assert len(threads[0]) == 3
        # Chronological order
        assert threads[0][0]["message_id"] == "<a>"
        assert threads[0][2]["message_id"] == "<c>"

    def test_two_independent_threads(self):
        messages = [
            {"message_id": "<a>", "in_reply_to": "", "date": "2024-01-01"},
            {"message_id": "<b>", "in_reply_to": "", "date": "2024-01-02"},
        ]
        threads = reconstruct_threads(messages)
        assert len(threads) == 2

    def test_orphan_reply_becomes_separate_thread(self):
        """Reply whose parent is not in the batch becomes its own thread root."""
        messages = [
            {"message_id": "<a>", "in_reply_to": "", "date": "2024-01-01"},
            {"message_id": "<orphan>", "in_reply_to": "<unknown>", "date": "2024-01-02"},
        ]
        threads = reconstruct_threads(messages)
        assert len(threads) == 2

    def test_empty_messages_returns_empty(self):
        assert reconstruct_threads([]) == []

    def test_branching_thread(self):
        """Two replies to the same parent form one thread."""
        messages = [
            {"message_id": "<root>", "in_reply_to": "", "date": "2024-01-01T10:00:00"},
            {"message_id": "<r1>", "in_reply_to": "<root>", "date": "2024-01-01T11:00:00"},
            {"message_id": "<r2>", "in_reply_to": "<root>", "date": "2024-01-01T12:00:00"},
        ]
        threads = reconstruct_threads(messages)
        assert len(threads) == 1
        assert len(threads[0]) == 3


# ---------------------------------------------------------------------------
# identify_author_role
# ---------------------------------------------------------------------------

class TestIdentifyAuthorRole:
    def test_primary_when_employee_is_sender(self):
        msg = {"from_addr": "jane@corp.com", "cc": ""}
        assert identify_author_role(msg, "jane@corp.com") == "primary"

    def test_cc_when_employee_in_cc(self):
        msg = {"from_addr": "bob@corp.com", "cc": "jane@corp.com, alice@corp.com"}
        assert identify_author_role(msg, "jane@corp.com") == "cc"

    def test_bcc_when_employee_not_in_from_or_cc(self):
        msg = {"from_addr": "bob@corp.com", "cc": "alice@corp.com"}
        assert identify_author_role(msg, "jane@corp.com") == "bcc"

    def test_case_insensitive_match(self):
        msg = {"from_addr": "Jane@Corp.com", "cc": ""}
        assert identify_author_role(msg, "jane@corp.com") == "primary"

    def test_empty_cc_field(self):
        msg = {"from_addr": "bob@corp.com", "cc": None}
        assert identify_author_role(msg, "jane@corp.com") == "bcc"


# ---------------------------------------------------------------------------
# build_thread_payload
# ---------------------------------------------------------------------------

class TestBuildThreadPayload:
    def test_builds_payload_with_metadata(self):
        thread = [
            {
                "message_id": "<msg001>",
                "subject": "Test subject",
                "from_addr": "jane@corp.com",
                "cc": "",
                "date": "2024-01-15T10:00:00+00:00",
                "body_text": "Hello world",
                "in_reply_to": "",
            },
        ]
        payload = build_thread_payload(thread, "emp_123", "jane@corp.com")
        assert payload["employeeId"] == "emp_123"
        assert payload["threadId"] == "<msg001>"
        assert payload["subject"] == "Test subject"
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["author_role"] == "primary"

    def test_multiple_messages_get_roles(self):
        thread = [
            {"message_id": "<a>", "subject": "S", "from_addr": "jane@corp.com", "cc": "", "date": "", "body_text": "", "in_reply_to": ""},
            {"message_id": "<b>", "subject": "Re: S", "from_addr": "bob@corp.com", "cc": "jane@corp.com", "date": "", "body_text": "", "in_reply_to": "<a>"},
        ]
        payload = build_thread_payload(thread, "emp_123", "jane@corp.com")
        assert payload["messages"][0]["author_role"] == "primary"
        assert payload["messages"][1]["author_role"] == "cc"

    def test_empty_thread(self):
        payload = build_thread_payload([], "emp_123", "jane@corp.com")
        assert payload["messages"] == []
        assert payload["threadId"] == ""
        assert payload["subject"] == ""
