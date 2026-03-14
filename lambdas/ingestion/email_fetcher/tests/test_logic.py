"""Unit tests for email_fetcher logic."""
from __future__ import annotations

import email
import json
import mailbox
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from lambdas.ingestion.email_fetcher.logic import (
    BATCH_SIZE,
    EXCLUDE_LABELS,
    _build_manifest,
    _extract_date_from_raw,
    _get_all_label_ids,
    _list_message_ids,
    _messages_to_mbox,
    fetch_and_upload_emails,
    get_google_credentials,
)


# --- Helpers ---

def _make_raw_email(
    subject: str = "Test Subject",
    from_addr: str = "sender@corp.com",
    to_addr: str = "recipient@corp.com",
    body: str = "This is a test email body.",
    date: str = "Mon, 15 Jan 2024 10:00:00 +0000",
) -> bytes:
    """Build a minimal RFC 2822 email as bytes."""
    msg = email.message.EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Date"] = date
    msg["Message-ID"] = f"<{subject.replace(' ', '-')}@test>"
    msg.set_content(body)
    return msg.as_bytes()


# --- get_google_credentials ---

class TestGetGoogleCredentials:
    @patch("lambdas.ingestion.email_fetcher.logic.service_account.Credentials")
    def test_returns_delegated_credentials(self, mock_creds_cls):
        mock_creds = MagicMock()
        mock_creds.with_subject.return_value = MagicMock()
        mock_creds_cls.from_service_account_info.return_value = mock_creds

        secrets_client = MagicMock()
        secrets_client.get_secret_value.return_value = {
            "SecretString": json.dumps({
                "type": "service_account",
                "project_id": "test",
                "private_key_id": "key123",
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n",
                "client_email": "sa@test.iam.gserviceaccount.com",
                "client_id": "123",
                "token_uri": "https://oauth2.googleapis.com/token",
            })
        }

        result = get_google_credentials(
            secret_name="kk/dev/google-workspace-creds",
            user_email="jane@corp.com",
            secrets_client=secrets_client,
        )

        secrets_client.get_secret_value.assert_called_once_with(
            SecretId="kk/dev/google-workspace-creds"
        )
        mock_creds.with_subject.assert_called_once_with("jane@corp.com")
        assert result is mock_creds.with_subject.return_value


# --- _get_all_label_ids ---

class TestGetAllLabelIds:
    def test_excludes_trash_and_spam(self):
        service = MagicMock()
        service.users().labels().list().execute.return_value = {
            "labels": [
                {"id": "INBOX", "name": "INBOX"},
                {"id": "SENT", "name": "SENT"},
                {"id": "TRASH", "name": "TRASH"},
                {"id": "SPAM", "name": "SPAM"},
                {"id": "Label_1", "name": "Projects"},
            ]
        }
        result = _get_all_label_ids(service)
        assert "TRASH" not in result
        assert "SPAM" not in result
        assert set(result) == {"INBOX", "SENT", "Label_1"}

    def test_empty_labels_returns_empty(self):
        service = MagicMock()
        service.users().labels().list().execute.return_value = {"labels": []}
        assert _get_all_label_ids(service) == []


# --- _list_message_ids ---

class TestListMessageIds:
    def test_single_page(self):
        service = MagicMock()
        service.users().messages().list().execute.return_value = {
            "messages": [{"id": "m1"}, {"id": "m2"}],
        }
        result = _list_message_ids(service)
        assert result == ["m1", "m2"]

    def test_multiple_pages(self):
        service = MagicMock()
        call = service.users().messages().list().execute
        call.side_effect = [
            {"messages": [{"id": "m1"}], "nextPageToken": "tok2"},
            {"messages": [{"id": "m2"}]},
        ]
        result = _list_message_ids(service)
        assert result == ["m1", "m2"]

    def test_no_messages_returns_empty(self):
        service = MagicMock()
        service.users().messages().list().execute.return_value = {}
        result = _list_message_ids(service)
        assert result == []


# --- _messages_to_mbox ---

class TestMessagesToMbox:
    def test_creates_valid_mbox_with_single_message(self):
        raw = _make_raw_email(subject="Hello")
        mbox_bytes = _messages_to_mbox([raw])
        assert len(mbox_bytes) > 0
        # Verify it's parseable as mbox
        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as f:
            f.write(mbox_bytes)
            f.flush()
            mbox = mailbox.mbox(f.name)
            messages = list(mbox)
            assert len(messages) == 1
            assert "Hello" in messages[0]["Subject"]
            mbox.close()

    def test_creates_mbox_with_multiple_messages(self):
        raws = [
            _make_raw_email(subject=f"Email {i}")
            for i in range(3)
        ]
        mbox_bytes = _messages_to_mbox(raws)
        with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as f:
            f.write(mbox_bytes)
            f.flush()
            mbox = mailbox.mbox(f.name)
            assert len(list(mbox)) == 3
            mbox.close()

    def test_empty_list_returns_empty_mbox(self):
        mbox_bytes = _messages_to_mbox([])
        assert isinstance(mbox_bytes, bytes)


# --- _extract_date_from_raw ---

class TestExtractDateFromRaw:
    def test_extracts_valid_date(self):
        raw = _make_raw_email(date="Mon, 15 Jan 2024 10:00:00 +0000")
        result = _extract_date_from_raw(raw)
        assert result is not None
        assert "2024" in result

    def test_returns_none_when_no_date_header(self):
        msg = email.message.EmailMessage()
        msg["Subject"] = "No date"
        msg.set_content("body")
        result = _extract_date_from_raw(msg.as_bytes())
        assert result is None


# --- _build_manifest ---

class TestBuildManifest:
    def test_manifest_with_dates(self):
        result = _build_manifest(
            employee_id="emp_001",
            total_count=200,
            batch_count=2,
            all_dates=["2024-03-01T00:00:00", "2024-01-15T00:00:00", "2024-06-01T00:00:00"],
            label_ids=["INBOX", "SENT"],
        )
        assert result["employeeId"] == "emp_001"
        assert result["totalCount"] == 200
        assert result["batchCount"] == 2
        assert result["dateRange"]["earliest"] == "2024-01-15T00:00:00"
        assert result["dateRange"]["latest"] == "2024-06-01T00:00:00"
        assert "fetchTimestamp" in result

    def test_manifest_with_no_dates(self):
        result = _build_manifest("emp_002", 0, 0, [], [])
        assert result["dateRange"]["earliest"] is None
        assert result["dateRange"]["latest"] is None
        assert result["totalCount"] == 0

    def test_manifest_with_single_date(self):
        result = _build_manifest("emp_003", 1, 1, ["2024-05-01T00:00:00"], ["INBOX"])
        assert result["dateRange"]["earliest"] == "2024-05-01T00:00:00"
        assert result["dateRange"]["latest"] == "2024-05-01T00:00:00"


# --- fetch_and_upload_emails ---

class TestFetchAndUploadEmails:
    @patch("lambdas.ingestion.email_fetcher.logic._build_gmail_service")
    @patch("lambdas.ingestion.email_fetcher.logic._get_all_label_ids")
    @patch("lambdas.ingestion.email_fetcher.logic._list_message_ids")
    @patch("lambdas.ingestion.email_fetcher.logic._get_raw_message")
    def test_uploads_batched_mbox_files(
        self, mock_get_raw, mock_list_ids, mock_labels, mock_build_svc
    ):
        mock_service = MagicMock()
        mock_build_svc.return_value = mock_service
        mock_labels.return_value = ["INBOX", "SENT"]
        # 3 messages — all in one batch (< BATCH_SIZE)
        mock_list_ids.return_value = ["m1", "m2", "m3"]
        mock_get_raw.side_effect = [
            _make_raw_email(subject="Email 1"),
            _make_raw_email(subject="Email 2"),
            _make_raw_email(subject="Email 3"),
        ]

        s3_client = MagicMock()
        credentials = MagicMock()

        result = fetch_and_upload_emails(
            employee_id="emp_001",
            user_email="jane@corp.com",
            bucket_name="test-bucket",
            credentials=credentials,
            s3_client=s3_client,
        )

        assert result["totalCount"] == 3
        assert result["batchCount"] == 1
        # 1 mbox upload + 1 manifest upload = 2 put_object calls
        assert s3_client.put_object.call_count == 2

        # Verify mbox upload key
        mbox_call = s3_client.put_object.call_args_list[0]
        assert mbox_call.kwargs["Key"] == "emp_001/batch_0000.mbox"

        # Verify manifest upload
        manifest_call = s3_client.put_object.call_args_list[1]
        assert manifest_call.kwargs["Key"] == "emp_001/manifest.json"

    @patch("lambdas.ingestion.email_fetcher.logic._build_gmail_service")
    @patch("lambdas.ingestion.email_fetcher.logic._get_all_label_ids")
    @patch("lambdas.ingestion.email_fetcher.logic._list_message_ids")
    def test_zero_messages_uploads_manifest_only(
        self, mock_list_ids, mock_labels, mock_build_svc
    ):
        mock_build_svc.return_value = MagicMock()
        mock_labels.return_value = ["INBOX"]
        mock_list_ids.return_value = []

        s3_client = MagicMock()

        result = fetch_and_upload_emails(
            employee_id="emp_002",
            user_email="bob@corp.com",
            bucket_name="test-bucket",
            credentials=MagicMock(),
            s3_client=s3_client,
        )

        assert result["totalCount"] == 0
        assert result["batchCount"] == 0
        # Only manifest upload
        assert s3_client.put_object.call_count == 1
        assert s3_client.put_object.call_args.kwargs["Key"] == "emp_002/manifest.json"

    @patch("lambdas.ingestion.email_fetcher.logic._build_gmail_service")
    @patch("lambdas.ingestion.email_fetcher.logic._get_all_label_ids")
    @patch("lambdas.ingestion.email_fetcher.logic._list_message_ids")
    @patch("lambdas.ingestion.email_fetcher.logic._get_raw_message")
    def test_skips_failed_message_fetch_continues(
        self, mock_get_raw, mock_list_ids, mock_labels, mock_build_svc
    ):
        mock_build_svc.return_value = MagicMock()
        mock_labels.return_value = ["INBOX"]
        mock_list_ids.return_value = ["m1", "m2"]
        mock_get_raw.side_effect = [
            Exception("API error"),
            _make_raw_email(subject="Good email"),
        ]

        s3_client = MagicMock()

        result = fetch_and_upload_emails(
            employee_id="emp_003",
            user_email="alice@corp.com",
            bucket_name="test-bucket",
            credentials=MagicMock(),
            s3_client=s3_client,
        )

        # 2 total IDs found, but only 1 fetched successfully
        assert result["totalCount"] == 2
        assert result["batchCount"] == 1
