"""Business logic for the email_fetcher Lambda.

Fetches emails from Google Workspace using the Admin SDK with
domain-wide delegation, batches them into .mbox files, and uploads
to S3. Pure business logic — AWS SDK clients are injected.
"""
from __future__ import annotations

import email
import json
import logging
import mailbox
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Protocol

from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
EXCLUDE_LABELS = {"TRASH", "SPAM"}


class S3Client(Protocol):
    """Protocol for S3 put_object calls."""

    def put_object(self, **kwargs: Any) -> Any: ...


class SecretsClient(Protocol):
    """Protocol for Secrets Manager get_secret_value calls."""

    def get_secret_value(self, **kwargs: Any) -> dict: ...


def get_google_credentials(
    secret_name: str,
    user_email: str,
    secrets_client: SecretsClient,
) -> service_account.Credentials:
    """Retrieve Google service account credentials from Secrets Manager
    and create delegated credentials for the target user."""
    resp = secrets_client.get_secret_value(SecretId=secret_name)
    creds_json = json.loads(resp["SecretString"])
    credentials = service_account.Credentials.from_service_account_info(
        creds_json, scopes=SCOPES
    )
    return credentials.with_subject(user_email)


def _build_gmail_service(credentials: service_account.Credentials):
    """Build a Gmail API service client."""
    return build("gmail", "v1", credentials=credentials)


def _get_all_label_ids(
    service,
    user_id: str = "me",
) -> list[str]:
    """Return label IDs for all labels except TRASH and SPAM."""
    resp = service.users().labels().list(userId=user_id).execute()
    labels = resp.get("labels", [])
    return [
        lbl["id"]
        for lbl in labels
        if lbl["name"] not in EXCLUDE_LABELS
    ]


def _list_message_ids(
    service,
    user_id: str = "me",
    label_ids: list[str] | None = None,
) -> list[str]:
    """Page through Gmail list API and collect all message IDs."""
    ids: list[str] = []
    page_token: str | None = None

    while True:
        kwargs: dict[str, Any] = {"userId": user_id}
        if label_ids:
            kwargs["labelIds"] = label_ids
        if page_token:
            kwargs["pageToken"] = page_token

        resp = service.users().messages().list(**kwargs).execute()
        for msg in resp.get("messages", []):
            ids.append(msg["id"])

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return ids


def _get_raw_message(service, message_id: str, user_id: str = "me") -> bytes:
    """Fetch a single message in RFC 2822 raw format."""
    resp = (
        service.users()
        .messages()
        .get(userId=user_id, id=message_id, format="raw")
        .execute()
    )
    import base64

    return base64.urlsafe_b64decode(resp["raw"])


def _messages_to_mbox(raw_messages: list[bytes]) -> bytes:
    """Convert a list of raw RFC 2822 messages into an mbox-format byte string."""
    with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as tmp:
        tmp_path = tmp.name

    mbox = mailbox.mbox(tmp_path)
    try:
        for raw in raw_messages:
            msg = email.message_from_bytes(raw)
            mbox_msg = mailbox.mboxMessage(msg)
            mbox.add(mbox_msg)
        mbox.flush()

        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        mbox.close()
        import os
        os.unlink(tmp_path)


def _extract_date_from_raw(raw: bytes) -> str | None:
    """Extract the Date header from a raw email, return ISO string or None."""
    msg = email.message_from_bytes(raw)
    date_str = msg.get("Date")
    if not date_str:
        return None
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.isoformat()
    except Exception:
        return date_str


def fetch_and_upload_emails(
    employee_id: str,
    user_email: str,
    bucket_name: str,
    credentials: service_account.Credentials,
    s3_client: S3Client,
) -> dict[str, Any]:
    """Fetch all emails for a user from Gmail and upload as batched .mbox files.

    Returns a manifest dict with total count, date range, batch count,
    and fetch timestamp.
    """
    service = _build_gmail_service(credentials)

    # Get labels excluding Trash/Spam
    label_ids = _get_all_label_ids(service)

    # Collect all message IDs
    message_ids = _list_message_ids(service, label_ids=label_ids)
    total_count = len(message_ids)
    logger.info(
        "Found %d messages for %s (employee=%s)",
        total_count,
        user_email,
        employee_id,
    )

    if total_count == 0:
        manifest = _build_manifest(employee_id, 0, 0, [], [])
        _upload_manifest(s3_client, bucket_name, employee_id, manifest)
        return manifest

    # Fetch and upload in batches
    batch_number = 0
    all_dates: list[str] = []
    label_counts: dict[str, int] = {}

    for i in range(0, total_count, BATCH_SIZE):
        batch_ids = message_ids[i : i + BATCH_SIZE]
        raw_messages: list[bytes] = []

        for msg_id in batch_ids:
            try:
                raw = _get_raw_message(service, msg_id)
                raw_messages.append(raw)

                date_str = _extract_date_from_raw(raw)
                if date_str:
                    all_dates.append(date_str)
            except Exception:
                logger.exception(
                    "Failed to fetch message %s for employee %s",
                    msg_id,
                    employee_id,
                )
                continue

        if not raw_messages:
            continue

        mbox_bytes = _messages_to_mbox(raw_messages)
        s3_key = f"{employee_id}/batch_{batch_number:04d}.mbox"

        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=mbox_bytes,
        )
        logger.info(
            "Uploaded %s (%d messages, %d bytes)",
            s3_key,
            len(raw_messages),
            len(mbox_bytes),
        )
        batch_number += 1

    manifest = _build_manifest(
        employee_id, total_count, batch_number, all_dates, label_ids
    )
    _upload_manifest(s3_client, bucket_name, employee_id, manifest)

    return manifest


def _build_manifest(
    employee_id: str,
    total_count: int,
    batch_count: int,
    all_dates: list[str],
    label_ids: list[str],
) -> dict[str, Any]:
    """Build the manifest.json content."""
    sorted_dates = sorted(all_dates) if all_dates else []
    return {
        "employeeId": employee_id,
        "totalCount": total_count,
        "batchCount": batch_count,
        "dateRange": {
            "earliest": sorted_dates[0] if sorted_dates else None,
            "latest": sorted_dates[-1] if sorted_dates else None,
        },
        "labelIds": label_ids,
        "fetchTimestamp": datetime.now(timezone.utc).isoformat(),
    }


def _upload_manifest(
    s3_client: S3Client,
    bucket_name: str,
    employee_id: str,
    manifest: dict[str, Any],
) -> None:
    """Upload manifest.json to S3."""
    s3_client.put_object(
        Bucket=bucket_name,
        Key=f"{employee_id}/manifest.json",
        Body=json.dumps(manifest, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    logger.info("Uploaded manifest for employee %s", employee_id)
