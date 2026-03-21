"""Business logic for the m365_email_fetcher Lambda.

Fetches emails from Microsoft 365 using the Graph API with
client credentials (application permissions), batches them into
.mbox files, and uploads to S3. Pure business logic — AWS SDK
clients are injected.
"""
from __future__ import annotations

import email as email_mod
import json
import logging
import mailbox
import tempfile
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import format_datetime
from html import unescape
from re import sub as re_sub
from typing import Any, Protocol

import msal
import requests

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
EXCLUDED_FOLDERS = {"Deleted Items", "Junk Email"}
MAX_RETRIES_GRAPH = 5
MAX_RETRIES_S3 = 3


SELECT_FIELDS = (
    "id,internetMessageId,subject,from,toRecipients,ccRecipients,"
    "bccRecipients,body,receivedDateTime,internetMessageHeaders,conversationId"
)


class S3Client(Protocol):
    """Protocol for S3 put_object calls."""

    def put_object(self, **kwargs: Any) -> Any: ...


class SecretsClient(Protocol):
    """Protocol for Secrets Manager get_secret_value calls."""

    def get_secret_value(self, **kwargs: Any) -> dict: ...


def get_m365_credentials(
    secret_name: str,
    secrets_client: SecretsClient,
) -> msal.ConfidentialClientApplication:
    """Retrieve M365 app credentials from Secrets Manager and return
    a configured MSAL ConfidentialClientApplication."""
    resp = secrets_client.get_secret_value(SecretId=secret_name)
    creds = json.loads(resp["SecretString"])
    tenant_id = creds["tenant_id"]
    client_id = creds["client_id"]
    client_secret = creds["client_secret"]

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )


def acquire_token(app: msal.ConfidentialClientApplication) -> str:
    """Acquire an OAuth 2.0 access token via client credentials flow.

    MSAL handles token caching and automatic refresh internally,
    so calling this repeatedly is safe and efficient.
    """
    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in result:
        error = result.get("error", "unknown")
        error_desc = result.get("error_description", "")
        raise RuntimeError(
            f"Failed to acquire M365 token: {error} — {error_desc}"
        )
    return result["access_token"]


def _graph_request(
    url: str,
    token: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Make a GET request to the Graph API with rate-limit retry.

    Retries up to MAX_RETRIES_GRAPH times on HTTP 429, respecting
    the Retry-After header. Raises on 401/403 auth errors.
    """
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(MAX_RETRIES_GRAPH + 1):
        resp = requests.get(url, headers=headers, params=params, timeout=30)

        if resp.status_code == 429:
            if attempt >= MAX_RETRIES_GRAPH:
                resp.raise_for_status()
            retry_after = int(resp.headers.get("Retry-After", 1))
            logger.warning(
                "Graph API rate limited (attempt %d/%d), retrying in %ds",
                attempt + 1,
                MAX_RETRIES_GRAPH,
                retry_after,
            )
            time.sleep(retry_after)
            continue

        if resp.status_code in (401, 403):
            raise PermissionError(
                f"Graph API auth error {resp.status_code}: {resp.text}"
            )

        resp.raise_for_status()
        return resp.json()

    # Should not reach here, but satisfy type checker
    raise RuntimeError("Exhausted Graph API retries")


def list_mail_folders(
    token: str,
    user_email: str,
) -> list[dict[str, Any]]:
    """Enumerate all mail folders for a user, excluding Deleted Items
    and Junk Email. Paginates via @odata.nextLink."""
    url = f"{GRAPH_BASE_URL}/users/{user_email}/mailFolders"
    folders: list[dict[str, Any]] = []

    while url:
        data = _graph_request(url, token)
        for folder in data.get("value", []):
            if folder.get("displayName") not in EXCLUDED_FOLDERS:
                folders.append(folder)
        url = data.get("@odata.nextLink")

    return folders


def fetch_folder_messages(
    token: str,
    user_email: str,
    folder_id: str,
) -> list[dict[str, Any]]:
    """Fetch all messages from a single mail folder with pagination.

    Uses $select to request only the required fields and $top=100
    for page size. Paginates via @odata.nextLink.
    """
    url = (
        f"{GRAPH_BASE_URL}/users/{user_email}"
        f"/mailFolders/{folder_id}/messages"
    )
    params = {"$select": SELECT_FIELDS, "$top": "100"}
    messages: list[dict[str, Any]] = []

    while url:
        data = _graph_request(url, token, params=params)
        messages.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        # nextLink already contains query params, so clear them
        params = None

    return messages


def _format_address(addr: dict[str, Any]) -> str:
    """Format a Graph API emailAddress object as 'Name <email>'."""
    ea = addr.get("emailAddress", addr)
    name = ea.get("name", "")
    address = ea.get("address", "")
    if name:
        return f'"{name}" <{address}>'
    return address


def _html_to_plain(html: str) -> str:
    """Crude HTML-to-plain-text conversion: strip tags and unescape."""
    text = re_sub(r"<br\s*/?>", "\n", html, flags=0)
    text = re_sub(r"<[^>]+>", "", text)
    return unescape(text)


def graph_message_to_rfc2822(msg: dict[str, Any]) -> bytes:
    """Convert a single Graph API message JSON to RFC 2822 bytes.

    Maps fields per the design document field mapping table.
    Raises on conversion failure so the caller can skip and log.
    """
    body = msg.get("body", {})
    content_type = body.get("contentType", "text").lower()
    content = body.get("content", "")

    if content_type == "html":
        mime = MIMEMultipart("alternative")
        plain_part = MIMEText(_html_to_plain(content), "plain", "utf-8")
        html_part = MIMEText(content, "html", "utf-8")
        mime.attach(plain_part)
        mime.attach(html_part)
    else:
        mime = MIMEText(content, "plain", "utf-8")

    # Map headers per design doc
    if msg.get("internetMessageId"):
        mime["Message-ID"] = msg["internetMessageId"]
    if msg.get("conversationId"):
        mime["Thread-ID"] = msg["conversationId"]
    if msg.get("subject"):
        mime["Subject"] = msg["subject"]
    if msg.get("from"):
        mime["From"] = _format_address(msg["from"])

    to_recips = msg.get("toRecipients", [])
    if to_recips:
        mime["To"] = ", ".join(_format_address(r) for r in to_recips)

    cc_recips = msg.get("ccRecipients", [])
    if cc_recips:
        mime["Cc"] = ", ".join(_format_address(r) for r in cc_recips)

    if msg.get("receivedDateTime"):
        try:
            dt = datetime.fromisoformat(
                msg["receivedDateTime"].replace("Z", "+00:00")
            )
            mime["Date"] = format_datetime(dt)
        except (ValueError, TypeError):
            mime["Date"] = msg["receivedDateTime"]

    return mime.as_bytes()


def messages_to_mbox(rfc2822_messages: list[bytes]) -> bytes:
    """Convert a list of raw RFC 2822 messages into an mbox-format byte string.

    Follows the same pattern as email_fetcher/logic.py::_messages_to_mbox().
    """
    with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as tmp:
        tmp_path = tmp.name

    mbox = mailbox.mbox(tmp_path)
    try:
        for raw in rfc2822_messages:
            msg = email_mod.message_from_bytes(raw)
            mbox_msg = mailbox.mboxMessage(msg)
            mbox.add(mbox_msg)
        mbox.flush()

        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        mbox.close()
        import os

        os.unlink(tmp_path)


def _upload_to_s3_with_retry(
    s3_client: S3Client,
    bucket_name: str,
    key: str,
    body: bytes,
    content_type: str | None = None,
) -> None:
    """Upload to S3 with retry and exponential backoff (1s, 2s, 4s)."""
    kwargs: dict[str, Any] = {
        "Bucket": bucket_name, "Key": key, "Body": body,
    }
    if content_type:
        kwargs["ContentType"] = content_type

    for attempt in range(MAX_RETRIES_S3):
        try:
            s3_client.put_object(**kwargs)
            return
        except Exception:
            if attempt >= MAX_RETRIES_S3 - 1:
                raise
            wait = 2**attempt  # 1, 2, 4
            logger.warning(
                "S3 upload failed for %s (attempt %d/%d), "
                "retrying in %ds",
                key, attempt + 1, MAX_RETRIES_S3, wait,
            )
            time.sleep(wait)


def _extract_date(msg: dict[str, Any]) -> str | None:
    """Extract receivedDateTime from a Graph API message as ISO string."""
    dt_str = msg.get("receivedDateTime")
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.isoformat()
    except (ValueError, TypeError):
        return dt_str


def _build_manifest(
    employee_id: str,
    total_count: int,
    batch_count: int,
    all_dates: list[str],
    folder_breakdown: dict[str, int],
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
        "folderBreakdown": folder_breakdown,
        "fetchTimestamp": datetime.now(timezone.utc).isoformat(),
    }


def fetch_and_upload_emails(
    employee_id: str,
    user_email: str,
    bucket_name: str,
    credentials: msal.ConfidentialClientApplication,
    s3_client: S3Client,
) -> dict[str, Any]:
    """Orchestrator: enumerate folders, fetch messages, batch into
    groups of 100, convert to RFC 2822, package as .mbox, upload to S3.

    Returns a manifest dict with totalCount, batchCount, dateRange,
    folderBreakdown, and fetchTimestamp.
    """
    token = acquire_token(credentials)

    # Enumerate folders (excludes Deleted Items and Junk Email)
    folders = list_mail_folders(token, user_email)
    logger.info(
        "Found %d folders for %s (employee=%s)",
        len(folders), user_email, employee_id,
    )

    # Fetch all messages across folders
    all_messages: list[dict[str, Any]] = []
    folder_breakdown: dict[str, int] = {}

    for folder in folders:
        folder_id = folder["id"]
        folder_name = folder.get("displayName", folder_id)
        messages = fetch_folder_messages(token, user_email, folder_id)
        if messages:
            folder_breakdown[folder_name] = len(messages)
            all_messages.extend(messages)

    total_fetched = len(all_messages)
    logger.info(
        "Found %d messages for %s (employee=%s)",
        total_fetched, user_email, employee_id,
    )

    # Collect dates for manifest
    all_dates: list[str] = []
    for msg in all_messages:
        date_str = _extract_date(msg)
        if date_str:
            all_dates.append(date_str)

    # Zero messages — write manifest only
    if total_fetched == 0:
        manifest = _build_manifest(
            employee_id, 0, 0, [], folder_breakdown,
        )
        _upload_to_s3_with_retry(
            s3_client, bucket_name,
            f"{employee_id}/manifest.json",
            json.dumps(manifest, indent=2).encode("utf-8"),
            content_type="application/json",
        )
        return manifest

    # Batch, convert, and upload
    batch_number = 0
    converted_count = 0

    for i in range(0, total_fetched, BATCH_SIZE):
        batch = all_messages[i : i + BATCH_SIZE]
        rfc2822_messages: list[bytes] = []

        for msg in batch:
            try:
                rfc2822_messages.append(graph_message_to_rfc2822(msg))
            except Exception:
                msg_id = msg.get("id", "unknown")
                logger.exception(
                    "Failed to convert message %s for employee %s",
                    msg_id, employee_id,
                )
                continue

        if not rfc2822_messages:
            continue

        mbox_bytes = messages_to_mbox(rfc2822_messages)
        s3_key = f"{employee_id}/batch_{batch_number:04d}.mbox"

        _upload_to_s3_with_retry(
            s3_client, bucket_name, s3_key, mbox_bytes,
        )
        logger.info(
            "Uploaded %s (%d messages, %d bytes)",
            s3_key, len(rfc2822_messages), len(mbox_bytes),
        )
        converted_count += len(rfc2822_messages)
        batch_number += 1

    # Write manifest
    manifest = _build_manifest(
        employee_id, converted_count, batch_number,
        all_dates, folder_breakdown,
    )
    _upload_to_s3_with_retry(
        s3_client, bucket_name,
        f"{employee_id}/manifest.json",
        json.dumps(manifest, indent=2).encode("utf-8"),
        content_type="application/json",
    )

    return manifest
