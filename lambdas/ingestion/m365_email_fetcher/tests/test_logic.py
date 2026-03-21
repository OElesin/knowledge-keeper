"""Unit tests for m365_email_fetcher logic."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from lambdas.ingestion.m365_email_fetcher.logic import (
    SecretsClient,
    S3Client,
    _build_manifest,
    _extract_date,
    _format_address,
    _graph_request,
    _html_to_plain,
    acquire_token,
    fetch_and_upload_emails,
    fetch_folder_messages,
    graph_message_to_rfc2822,
    get_m365_credentials,
    list_mail_folders,
    messages_to_mbox,
)


class TestFormatAddress:
    def test_format_address_with_name(self):
        addr = {"emailAddress": {"name": "John Doe", "address": "john@example.com"}}
        result = _format_address(addr)
        assert result == '"John Doe" <john@example.com>'

    def test_format_address_without_name(self):
        addr = {"emailAddress": {"address": "john@example.com"}}
        result = _format_address(addr)
        assert result == "john@example.com"


class TestHtmlToPlain:
    def test_simple_html(self):
        html = "<p>Hello <b>World</b></p>"
        result = _html_to_plain(html)
        assert "Hello" in result
        assert "World" in result

    def test_br_tags(self):
        html = "Line 1<br>Line 2"
        result = _html_to_plain(html)
        assert "\n" in result


class TestGraphMessageToRfc2822:
    def test_text_body_conversion(self):
        msg = {
            "internetMessageId": "<msg123@example.com>",
            "subject": "Test Subject",
            "from": {"emailAddress": {"name": "John", "address": "john@example.com"}},
            "body": {"contentType": "text", "content": "Test body"},
        }
        result = graph_message_to_rfc2822(msg)
        assert b"Message-ID: <msg123@example.com>" in result
        assert b"Subject: Test Subject" in result
        # Body is base64 encoded in RFC 2822 format - check for base64 of "Test body"
        assert b"VGVzdCBib2R5" in result

    def test_html_body_conversion(self):
        msg = {
            "internetMessageId": "<msg456@example.com>",
            "subject": "HTML Email",
            "from": {"emailAddress": {"address": "sender@example.com"}},
            "body": {"contentType": "html", "content": "<p>HTML content</p>"},
        }
        result = graph_message_to_rfc2822(msg)
        assert b"multipart/alternative" in result
        assert b"Content-Type: text/html" in result


class TestMessagesToMbox:
    def test_empty_list(self):
        result = messages_to_mbox([])
        # Empty mbox returns empty bytes (no messages to add)
        assert len(result) == 0

    def test_single_message(self):
        msg = b"From: sender@example.com\nSubject: Test\n\nBody"
        result = messages_to_mbox([msg])
        assert b"From: sender@example.com" in result


class TestExtractDate:
    def test_valid_iso_date(self):
        msg = {"receivedDateTime": "2024-01-15T10:30:00Z"}
        result = _extract_date(msg)
        assert result == "2024-01-15T10:30:00+00:00"

    def test_missing_date(self):
        msg = {}
        result = _extract_date(msg)
        assert result is None


class TestBuildManifest:
    def test_with_data(self):
        result = _build_manifest(
            employee_id="emp_123",
            total_count=100,
            batch_count=2,
            all_dates=["2024-01-01T00:00:00+00:00", "2024-01-15T00:00:00+00:00"],
            folder_breakdown={"Inbox": 80},
        )
        assert result["employeeId"] == "emp_123"
        assert result["totalCount"] == 100
        assert result["dateRange"]["earliest"] == "2024-01-01T00:00:00+00:00"


class TestAcquireToken:
    @patch("lambdas.ingestion.m365_email_fetcher.logic.msal")
    def test_success(self, mock_msal):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {
            "access_token": "test_token_123"
        }
        result = acquire_token(mock_app)
        assert result == "test_token_123"

    @patch("lambdas.ingestion.m365_email_fetcher.logic.msal")
    def test_failure(self, mock_msal):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {
            "error": "invalid_client",
            "error_description": "Client secret is invalid"
        }
        with pytest.raises(RuntimeError, match="Failed to acquire M365 token"):
            acquire_token(mock_app)


class TestGraphRequest:
    @patch("lambdas.ingestion.m365_email_fetcher.logic.requests")
    def test_success(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"value": [{"id": "1"}]}
        mock_requests.get.return_value = mock_response

        result = _graph_request("https://graph.microsoft.com/v1.0/test", "token123")
        assert result == {"value": [{"id": "1"}]}

    @patch("lambdas.ingestion.m365_email_fetcher.logic.requests")
    def test_auth_error(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_requests.get.return_value = mock_response

        with pytest.raises(PermissionError, match="Graph API auth error 401"):
            _graph_request("https://graph.microsoft.com/v1.0/test", "token")


class TestListMailFolders:
    @patch("lambdas.ingestion.m365_email_fetcher.logic._graph_request")
    def test_excludes_special_folders(self, mock_graph_request):
        mock_graph_request.return_value = {
            "value": [
                {"id": "inbox", "displayName": "Inbox"},
                {"id": "deleted", "displayName": "Deleted Items"},
            ],
            "@odata.nextLink": None,
        }

        result = list_mail_folders("token", "user@example.com")
        display_names = [f["displayName"] for f in result]
        assert "Inbox" in display_names
        assert "Deleted Items" not in display_names


class TestFetchFolderMessages:
    @patch("lambdas.ingestion.m365_email_fetcher.logic._graph_request")
    def test_fetches_messages(self, mock_graph_request):
        mock_graph_request.return_value = {
            "value": [{"id": "msg1"}],
            "@odata.nextLink": None,
        }

        result = fetch_folder_messages("token", "user@example.com", "folder123")
        assert len(result) == 1
        assert result[0]["id"] == "msg1"


class TestGetM365Credentials:
    @patch("lambdas.ingestion.m365_email_fetcher.logic.msal")
    def test_success(self, mock_msal):
        mock_app = MagicMock()
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_secrets_client = MagicMock(spec=SecretsClient)
        mock_secrets_client.get_secret_value.return_value = {
            "SecretString": json.dumps({
                "tenant_id": "tenant-123",
                "client_id": "client-123",
                "client_secret": "secret-123",
            })
        }

        result = get_m365_credentials("kk/dev/m365-credentials", mock_secrets_client)
        assert result is not None
        mock_msal.ConfidentialClientApplication.assert_called_once()


class TestFetchAndUploadEmails:
    @patch("lambdas.ingestion.m365_email_fetcher.logic.acquire_token")
    @patch("lambdas.ingestion.m365_email_fetcher.logic.list_mail_folders")
    @patch("lambdas.ingestion.m365_email_fetcher.logic.fetch_folder_messages")
    @patch("lambdas.ingestion.m365_email_fetcher.logic.graph_message_to_rfc2822")
    @patch("lambdas.ingestion.m365_email_fetcher.logic.messages_to_mbox")
    @patch("lambdas.ingestion.m365_email_fetcher.logic._upload_to_s3_with_retry")
    def test_happy_path(
        self,
        mock_upload,
        mock_mbox,
        mock_convert,
        mock_fetch_messages,
        mock_list_folders,
        mock_acquire_token,
    ):
        mock_acquire_token.return_value = "token"
        mock_list_folders.return_value = [{"id": "inbox", "displayName": "Inbox"}]
        mock_fetch_messages.return_value = [{
            "id": "msg1",
            "internetMessageId": "<msg1@example.com>",
            "subject": "Test",
            "from": {"emailAddress": {"address": "sender@example.com"}},
            "body": {"contentType": "text", "content": "Body"},
            "receivedDateTime": "2024-01-15T10:00:00Z",
        }]
        mock_convert.return_value = b"From: sender@example.com\nSubject: Test\n\nBody"
        mock_mbox.return_value = b"mbox content"

        mock_s3_client = MagicMock(spec=S3Client)

        result = fetch_and_upload_emails(
            employee_id="emp_123",
            user_email="user@example.com",
            bucket_name="kk-123-dev-raw-archives",
            credentials=MagicMock(),
            s3_client=mock_s3_client,
        )

        assert result["totalCount"] == 1
        assert result["batchCount"] == 1
        assert mock_upload.call_count == 2

    @patch("lambdas.ingestion.m365_email_fetcher.logic.acquire_token")
    @patch("lambdas.ingestion.m365_email_fetcher.logic.list_mail_folders")
    @patch("lambdas.ingestion.m365_email_fetcher.logic.fetch_folder_messages")
    @patch("lambdas.ingestion.m365_email_fetcher.logic._upload_to_s3_with_retry")
    def test_zero_messages(
        self,
        mock_upload,
        mock_fetch_messages,
        mock_list_folders,
        mock_acquire_token,
    ):
        mock_acquire_token.return_value = "token"
        mock_list_folders.return_value = [{"id": "inbox", "displayName": "Inbox"}]
        mock_fetch_messages.return_value = []

        mock_s3_client = MagicMock(spec=S3Client)

        result = fetch_and_upload_emails(
            employee_id="emp_456",
            user_email="user@example.com",
            bucket_name="kk-123-dev-raw-archives",
            credentials=MagicMock(),
            s3_client=mock_s3_client,
        )

        assert result["totalCount"] == 0
        assert result["batchCount"] == 0
        # Manifest should be uploaded
        mock_upload.assert_called_once()
