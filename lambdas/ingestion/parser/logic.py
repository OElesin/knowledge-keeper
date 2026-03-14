"""Business logic for the parser Lambda.

Parses .mbox files into structured emails, reconstructs conversation
threads via message_id/in_reply_to graph traversal, and identifies
author roles per message.
"""
from __future__ import annotations

import email
import email.utils
import mailbox
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Literal

from bs4 import BeautifulSoup


def parse_mbox_bytes(mbox_bytes: bytes) -> list[dict[str, Any]]:
    """Parse raw .mbox bytes into a list of structured email dicts.

    Each dict contains: message_id, subject, from_addr, to, cc, date,
    body_text, in_reply_to, references.
    """
    messages: list[dict[str, Any]] = []

    with tempfile.NamedTemporaryFile(suffix=".mbox") as tmp:
        tmp.write(mbox_bytes)
        tmp.flush()
        mbox = mailbox.mbox(tmp.name)

        for msg in mbox:
            parsed = _parse_single_message(msg)
            if parsed is not None:
                messages.append(parsed)

    return messages


def _parse_single_message(msg: email.message.Message) -> dict[str, Any] | None:
    """Extract structured fields from a single email message.

    Returns None if the message has no message_id.
    """
    message_id = msg.get("Message-ID", "").strip()
    if not message_id:
        return None

    body_text = _extract_body_text(msg)

    # Parse date into ISO 8601
    date_str = msg.get("Date", "")
    parsed_date = _parse_date(date_str)

    return {
        "message_id": message_id,
        "subject": msg.get("Subject", ""),
        "from_addr": msg.get("From", ""),
        "to": msg.get("To", ""),
        "cc": msg.get("Cc", ""),
        "date": parsed_date,
        "body_text": body_text,
        "in_reply_to": msg.get("In-Reply-To", "").strip(),
        "references": msg.get("References", "").strip(),
    }


def _extract_body_text(msg: email.message.Message) -> str:
    """Extract plain text body from an email message.

    Prefers text/plain parts. Falls back to stripping HTML from
    text/html parts using BeautifulSoup, retaining whitespace.
    """
    if not msg.is_multipart():
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload is None:
            return ""
        text = payload.decode("utf-8", errors="replace")
        if content_type == "text/html":
            return _strip_html(text)
        return text

    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in msg.walk():
        content_type = part.get_content_type()
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode("utf-8", errors="replace")

        if content_type == "text/plain":
            plain_parts.append(text)
        elif content_type == "text/html":
            html_parts.append(text)

    if plain_parts:
        return "\n".join(plain_parts)

    if html_parts:
        return "\n".join(_strip_html(h) for h in html_parts)

    return ""


def _strip_html(html: str) -> str:
    """Strip HTML tags, retaining meaningful whitespace."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=False).strip()


def _parse_date(date_str: str) -> str:
    """Parse an email Date header into ISO 8601 format.

    Returns empty string if parsing fails.
    """
    if not date_str:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except (ValueError, TypeError):
        return ""


def reconstruct_threads(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Reconstruct email threads from a flat list of parsed messages.

    Builds a message_id → message lookup and an in_reply_to → parent graph,
    then walks depth-first from root messages (those with no parent) to
    produce ordered thread chains.

    Returns a list of threads, each thread being a chronologically ordered
    list of message dicts.
    """
    if not messages:
        return []

    by_id: dict[str, dict[str, Any]] = {}
    children: dict[str, list[str]] = {}

    for msg in messages:
        mid = msg["message_id"]
        by_id[mid] = msg
        parent = msg.get("in_reply_to", "")
        if parent:
            children.setdefault(parent, []).append(mid)

    # Roots are messages whose in_reply_to is empty or points to an
    # unknown message_id (not in this batch).
    roots: list[str] = []
    for msg in messages:
        parent = msg.get("in_reply_to", "")
        if not parent or parent not in by_id:
            roots.append(msg["message_id"])

    visited: set[str] = set()
    threads: list[list[dict[str, Any]]] = []

    for root_id in roots:
        thread: list[dict[str, Any]] = []
        _walk_thread(root_id, by_id, children, thread, visited)
        if thread:
            # Sort chronologically within each thread
            thread.sort(key=lambda m: m.get("date", ""))
            threads.append(thread)

    # Collect any orphaned messages not reached by the walk
    for msg in messages:
        if msg["message_id"] not in visited:
            threads.append([msg])
            visited.add(msg["message_id"])

    return threads


def _walk_thread(
    message_id: str,
    by_id: dict[str, dict[str, Any]],
    children: dict[str, list[str]],
    thread: list[dict[str, Any]],
    visited: set[str],
) -> None:
    """Depth-first walk from a message through its children."""
    if message_id in visited:
        return
    visited.add(message_id)

    msg = by_id.get(message_id)
    if msg is not None:
        thread.append(msg)

    for child_id in children.get(message_id, []):
        _walk_thread(child_id, by_id, children, thread, visited)


def identify_author_role(
    message: dict[str, Any],
    employee_email: str,
) -> Literal["primary", "cc", "bcc"]:
    """Determine the author role for a message relative to the employee.

    - "primary" if the employee is the sender (From field)
    - "cc" if the employee appears in the CC field
    - "bcc" otherwise (employee is not in From or CC, implying BCC)
    """
    normalised = employee_email.lower().strip()

    from_addr = message.get("from_addr", "")
    if _email_matches(from_addr, normalised):
        return "primary"

    cc = message.get("cc", "") or ""
    if _email_matches(cc, normalised):
        return "cc"

    return "bcc"


def _email_matches(header_value: str, target_email: str) -> bool:
    """Check if target_email appears in an email header value."""
    return target_email in header_value.lower()


def build_thread_payload(
    thread: list[dict[str, Any]],
    employee_id: str,
    employee_email: str,
) -> dict[str, Any]:
    """Build a JSON-serialisable thread payload for the CleanQueue.

    Attaches author_role to each message and wraps the thread with
    metadata for downstream processing.
    """
    enriched_messages = []
    for msg in thread:
        enriched = {**msg}
        enriched["author_role"] = identify_author_role(msg, employee_email)
        enriched_messages.append(enriched)

    # Use the subject from the first message as the thread subject
    thread_subject = enriched_messages[0].get("subject", "") if enriched_messages else ""
    # Use the root message_id as the thread_id
    thread_id = enriched_messages[0].get("message_id", "") if enriched_messages else ""

    return {
        "employeeId": employee_id,
        "threadId": thread_id,
        "subject": thread_subject,
        "messages": enriched_messages,
    }
