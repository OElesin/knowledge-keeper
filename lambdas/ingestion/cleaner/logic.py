"""Business logic for the cleaner Lambda.

Strips noise (signatures, disclaimers, calendar invites), discards
short messages, detects and redacts PII via Amazon Comprehend, and
prepares cleaned threads for the EmbedQueue.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# --- Signature patterns ---
# Lines starting with common sign-off phrases (case-insensitive).
_SIGNATURE_PATTERNS = re.compile(
    r"^(?:--|Best,|Thanks,|Regards,|Cheers,|Sincerely,|Kind regards,|Warm regards,)"
    r".*",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)

# --- Legal disclaimer patterns ---
# Matches common multi-line legal/confidentiality disclaimers.
_DISCLAIMER_PATTERNS = re.compile(
    r"(?:^|\n)"
    r"(?:CONFIDENTIALITY\s+NOTICE|DISCLAIMER|LEGAL\s+NOTICE|"
    r"This\s+(?:email|message|communication)\s+(?:is|and\s+any)\s+"
    r"(?:intended|confidential|privileged))"
    r".*",
    re.IGNORECASE | re.DOTALL,
)

MIN_BODY_LENGTH = 50

# PII entity types we redact.
_REDACT_PII_TYPES = frozenset({
    "SSN",
    "CREDIT_DEBIT_NUMBER",
    "PHONE",
    "BANK_ACCOUNT_NUMBER",
    "PIN",
})


def strip_signature(text: str) -> str:
    """Remove email signatures from the end of a message body.

    Cuts everything from the first recognised sign-off line onward.
    """
    match = _SIGNATURE_PATTERNS.search(text)
    if match:
        return text[: match.start()].rstrip()
    return text


def strip_disclaimer(text: str) -> str:
    """Remove legal / confidentiality disclaimers."""
    result = _DISCLAIMER_PATTERNS.sub("", text)
    return result.rstrip()


def is_calendar_invite(message: dict[str, Any]) -> bool:
    """Return True if the message is a calendar invite (text/calendar MIME)."""
    content_type = message.get("content_type", "")
    return "text/calendar" in content_type.lower()


def clean_message_body(body: str) -> str:
    """Apply all noise-stripping steps to a single message body."""
    cleaned = strip_signature(body)
    cleaned = strip_disclaimer(cleaned)
    return cleaned.strip()


def redact_pii(
    text: str,
    comprehend_client: Any | None = None,
    language_code: str = "en",
) -> tuple[str, bool]:
    """Detect and redact PII in *text* using Amazon Comprehend.

    Returns ``(redacted_text, pii_unverified)``.
    *pii_unverified* is ``True`` when the Comprehend call fails and PII
    status could not be determined.
    """
    if comprehend_client is None:
        return text, True  # no client → flag as unverified

    try:
        response = comprehend_client.detect_pii_entities(
            Text=text,
            LanguageCode=language_code,
        )
    except Exception:
        logger.exception("Comprehend detect_pii_entities failed")
        return text, True

    entities = response.get("Entities", [])
    if not entities:
        return text, False

    # Sort entities by offset descending so replacements don't shift indices.
    entities_to_redact = [
        e for e in entities if e["Type"] in _REDACT_PII_TYPES
    ]
    entities_to_redact.sort(key=lambda e: e["BeginOffset"], reverse=True)

    redacted = text
    for entity in entities_to_redact:
        start = entity["BeginOffset"]
        end = entity["EndOffset"]
        redacted = redacted[:start] + f"[REDACTED-{entity['Type']}]" + redacted[end:]

    return redacted, False


def clean_thread(
    thread: dict[str, Any],
    comprehend_client: Any | None = None,
) -> dict[str, Any] | None:
    """Clean a full thread payload from the CleanQueue.

    Steps per message:
    1. Skip calendar invites.
    2. Strip signatures and disclaimers.
    3. Discard messages with cleaned body < MIN_BODY_LENGTH characters.
    4. Redact PII via Comprehend.

    Returns the cleaned thread dict (with surviving messages), or ``None``
    if no messages survive cleaning.
    """
    cleaned_messages: list[dict[str, Any]] = []

    for msg in thread.get("messages", []):
        # Skip calendar invites
        if is_calendar_invite(msg):
            continue

        body = msg.get("body_text", "")
        cleaned_body = clean_message_body(body)

        # Discard short messages
        if len(cleaned_body) < MIN_BODY_LENGTH:
            continue

        # PII detection and redaction
        redacted_body, pii_unverified = redact_pii(
            cleaned_body, comprehend_client
        )

        cleaned_msg = {**msg}
        cleaned_msg["body_text"] = redacted_body
        cleaned_msg["pii_unverified"] = pii_unverified
        cleaned_messages.append(cleaned_msg)

    if not cleaned_messages:
        return None

    return {
        "employeeId": thread.get("employeeId", ""),
        "threadId": thread.get("threadId", ""),
        "subject": thread.get("subject", ""),
        "messages": cleaned_messages,
    }
