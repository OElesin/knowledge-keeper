"""Unit tests for directory_lookup logic."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from lambdas.query.directory_lookup.logic import (
    SecretsClient,
    lookup_employee,
    _is_email,
    _normalize_microsoft,
    _normalize_google,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_secrets_client(creds: dict) -> MagicMock:
    """Create a mock SecretsClient that returns the given credentials."""
    client = MagicMock(spec=SecretsClient)
    client.get_secret_value.return_value = {
        "SecretString": json.dumps(creds),
    }
    return client


MICROSOFT_CREDS = {
    "tenant_id": "tenant-abc",
    "client_id": "client-abc",
    "client_secret": "secret-abc",
}

GOOGLE_CREDS = {
    "type": "service_account",
    "project_id": "proj-1",
    "private_key_id": "key-1",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIBogIBAAJBALRiMLAH\n-----END RSA PRIVATE KEY-----\n",
    "client_email": "sa@proj-1.iam.gserviceaccount.com",
    "client_id": "111",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "delegated_admin": "admin@corp.com",
}

SECRET_NAME = "kk/dev/directory-creds"


# ---------------------------------------------------------------------------
# _is_email
# ---------------------------------------------------------------------------

class TestIsEmail:
    def test_email_with_at(self):
        assert _is_email("jane@corp.com") is True

    def test_plain_id(self):
        assert _is_email("emp-123") is False


# ---------------------------------------------------------------------------
# _normalize_microsoft
# ---------------------------------------------------------------------------

class TestNormalizeMicrosoft:
    def test_full_response(self):
        graph_user = {
            "id": "abc-123",
            "displayName": "Jane Doe",
            "mail": "jane@corp.com",
            "jobTitle": "Senior Engineer",
            "department": "Engineering",
        }
        record = _normalize_microsoft(graph_user)
        assert record == {
            "employeeId": "abc-123",
            "name": "Jane Doe",
            "email": "jane@corp.com",
            "role": "Senior Engineer",
            "department": "Engineering",
        }

    def test_null_fields_become_empty_strings(self):
        graph_user = {
            "id": "abc-123",
            "displayName": None,
            "mail": None,
            "jobTitle": None,
            "department": None,
        }
        record = _normalize_microsoft(graph_user)
        assert record["name"] == ""
        assert record["email"] == ""
        assert record["role"] == ""
        assert record["department"] == ""

    def test_missing_fields_become_empty_strings(self):
        graph_user = {"id": "abc-123"}
        record = _normalize_microsoft(graph_user)
        assert record["employeeId"] == "abc-123"
        assert record["name"] == ""
        assert record["email"] == ""
        assert record["role"] == ""
        assert record["department"] == ""


# ---------------------------------------------------------------------------
# _normalize_google
# ---------------------------------------------------------------------------

class TestNormalizeGoogle:
    def test_full_response(self):
        directory_user = {
            "id": "g-456",
            "name": {"fullName": "John Smith"},
            "primaryEmail": "john@corp.com",
            "organizations": [
                {"title": "Staff Engineer", "department": "Platform"},
            ],
        }
        record = _normalize_google(directory_user)
        assert record == {
            "employeeId": "g-456",
            "name": "John Smith",
            "email": "john@corp.com",
            "role": "Staff Engineer",
            "department": "Platform",
        }

    def test_empty_organizations_array(self):
        directory_user = {
            "id": "g-789",
            "name": {"fullName": "No Org User"},
            "primaryEmail": "noorg@corp.com",
            "organizations": [],
        }
        record = _normalize_google(directory_user)
        assert record["role"] == ""
        assert record["department"] == ""

    def test_missing_organizations_key(self):
        directory_user = {
            "id": "g-000",
            "name": {"fullName": "Minimal User"},
            "primaryEmail": "min@corp.com",
        }
        record = _normalize_google(directory_user)
        assert record["role"] == ""
        assert record["department"] == ""

    def test_null_name_object(self):
        directory_user = {"id": "g-111", "name": None, "primaryEmail": "x@y.com"}
        record = _normalize_google(directory_user)
        assert record["name"] == ""


# ---------------------------------------------------------------------------
# lookup_employee — validation
# ---------------------------------------------------------------------------

class TestLookupValidation:
    def test_empty_query_returns_validation_error(self):
        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("", "microsoft", SECRET_NAME, client)
        assert result["success"] is False
        assert result["status_code"] == 400
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_whitespace_only_query_returns_validation_error(self):
        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("   \t\n  ", "microsoft", SECRET_NAME, client)
        assert result["success"] is False
        assert result["status_code"] == 400
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_invalid_provider_returns_provider_not_configured(self):
        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("jane@corp.com", "okta", SECRET_NAME, client)
        assert result["success"] is False
        assert result["status_code"] == 500
        assert result["error"]["code"] == "PROVIDER_NOT_CONFIGURED"

    def test_none_provider_returns_provider_not_configured(self):
        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("jane@corp.com", None, SECRET_NAME, client)
        assert result["success"] is False
        assert result["status_code"] == 500
        assert result["error"]["code"] == "PROVIDER_NOT_CONFIGURED"

    def test_empty_provider_returns_provider_not_configured(self):
        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("jane@corp.com", "", SECRET_NAME, client)
        assert result["success"] is False
        assert result["status_code"] == 500
        assert result["error"]["code"] == "PROVIDER_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# lookup_employee — Microsoft happy paths
# ---------------------------------------------------------------------------

class TestLookupMicrosoft:
    @patch("lambdas.query.directory_lookup.logic.requests")
    @patch("lambdas.query.directory_lookup.logic.msal")
    def test_email_query_returns_employee_record(self, mock_msal, mock_requests):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "abc-123",
            "displayName": "Jane Doe",
            "mail": "jane@corp.com",
            "jobTitle": "Senior Engineer",
            "department": "Engineering",
        }
        mock_requests.get.return_value = mock_resp
        mock_requests.Timeout = Exception

        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("jane@corp.com", "microsoft", SECRET_NAME, client)

        assert result["success"] is True
        assert result["status_code"] == 200
        assert result["data"]["employeeId"] == "abc-123"
        assert result["data"]["name"] == "Jane Doe"
        assert result["data"]["email"] == "jane@corp.com"

        # Verify email-based URL was used (direct user lookup)
        call_args = mock_requests.get.call_args
        assert "/users/jane@corp.com" in call_args[0][0]

    @patch("lambdas.query.directory_lookup.logic.requests")
    @patch("lambdas.query.directory_lookup.logic.msal")
    def test_id_query_uses_filter(self, mock_msal, mock_requests):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "value": [
                {
                    "id": "emp-999",
                    "displayName": "Bob Builder",
                    "mail": "bob@corp.com",
                    "jobTitle": "Architect",
                    "department": "Construction",
                },
            ],
        }
        mock_requests.get.return_value = mock_resp
        mock_requests.Timeout = Exception

        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("emp-999", "microsoft", SECRET_NAME, client)

        assert result["success"] is True
        assert result["data"]["employeeId"] == "emp-999"
        assert result["data"]["name"] == "Bob Builder"

        # Verify filter-based URL was used
        call_args = mock_requests.get.call_args
        assert "/users" in call_args[0][0]
        assert "$filter" in call_args[1].get("params", {})

    @patch("lambdas.query.directory_lookup.logic.requests")
    @patch("lambdas.query.directory_lookup.logic.msal")
    def test_id_query_no_results_returns_not_found(self, mock_msal, mock_requests):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"value": []}
        mock_requests.get.return_value = mock_resp
        mock_requests.Timeout = Exception

        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("nonexistent", "microsoft", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 404
        assert result["error"]["code"] == "EMPLOYEE_NOT_FOUND"

    @patch("lambdas.query.directory_lookup.logic.requests")
    @patch("lambdas.query.directory_lookup.logic.msal")
    def test_null_fields_in_graph_response(self, mock_msal, mock_requests):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "abc-null",
            "displayName": None,
            "mail": None,
            "jobTitle": None,
            "department": None,
        }
        mock_requests.get.return_value = mock_resp
        mock_requests.Timeout = Exception

        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("null@corp.com", "microsoft", SECRET_NAME, client)

        assert result["success"] is True
        assert result["data"]["employeeId"] == "abc-null"
        assert result["data"]["name"] == ""
        assert result["data"]["email"] == ""
        assert result["data"]["role"] == ""
        assert result["data"]["department"] == ""


# ---------------------------------------------------------------------------
# lookup_employee — Microsoft error cases
# ---------------------------------------------------------------------------

class TestLookupMicrosoftErrors:
    @patch("lambdas.query.directory_lookup.logic.requests")
    @patch("lambdas.query.directory_lookup.logic.msal")
    def test_directory_auth_error_401(self, mock_msal, mock_requests):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_requests.get.return_value = mock_resp
        mock_requests.Timeout = Exception

        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("jane@corp.com", "microsoft", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 502
        assert result["error"]["code"] == "DIRECTORY_AUTH_ERROR"

    @patch("lambdas.query.directory_lookup.logic.requests")
    @patch("lambdas.query.directory_lookup.logic.msal")
    def test_directory_auth_error_403(self, mock_msal, mock_requests):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_requests.get.return_value = mock_resp
        mock_requests.Timeout = Exception

        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("jane@corp.com", "microsoft", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 502
        assert result["error"]["code"] == "DIRECTORY_AUTH_ERROR"

    @patch("lambdas.query.directory_lookup.logic.requests")
    @patch("lambdas.query.directory_lookup.logic.msal")
    def test_directory_rate_limited_429(self, mock_msal, mock_requests):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_requests.get.return_value = mock_resp
        mock_requests.Timeout = Exception

        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("jane@corp.com", "microsoft", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 429
        assert result["error"]["code"] == "DIRECTORY_RATE_LIMITED"

    @patch("lambdas.query.directory_lookup.logic.requests")
    @patch("lambdas.query.directory_lookup.logic.msal")
    def test_directory_server_error_500(self, mock_msal, mock_requests):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_requests.get.return_value = mock_resp
        mock_requests.Timeout = Exception

        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("jane@corp.com", "microsoft", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 502
        assert result["error"]["code"] == "DIRECTORY_UNAVAILABLE"

    @patch("lambdas.query.directory_lookup.logic.requests")
    @patch("lambdas.query.directory_lookup.logic.msal")
    def test_directory_not_found_404(self, mock_msal, mock_requests):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_requests.get.return_value = mock_resp
        mock_requests.Timeout = Exception

        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("ghost@corp.com", "microsoft", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 404
        assert result["error"]["code"] == "EMPLOYEE_NOT_FOUND"

    @patch("lambdas.query.directory_lookup.logic.requests")
    @patch("lambdas.query.directory_lookup.logic.msal")
    def test_directory_timeout(self, mock_msal, mock_requests):
        import requests as real_requests

        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        mock_msal.ConfidentialClientApplication.return_value = mock_app

        mock_requests.Timeout = real_requests.Timeout
        mock_requests.get.side_effect = real_requests.Timeout("Connection timed out")

        client = _make_secrets_client(MICROSOFT_CREDS)
        result = lookup_employee("jane@corp.com", "microsoft", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 504
        assert result["error"]["code"] == "DIRECTORY_TIMEOUT"

    def test_secrets_manager_failure(self):
        client = MagicMock(spec=SecretsClient)
        client.get_secret_value.side_effect = Exception("Access denied")

        result = lookup_employee("jane@corp.com", "microsoft", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 500
        assert result["error"]["code"] == "CREDENTIALS_UNAVAILABLE"


# ---------------------------------------------------------------------------
# lookup_employee — Google happy path
# ---------------------------------------------------------------------------

def _patch_google():
    """Return context managers that patch the Google SDK imports used inside _lookup_google."""
    return (
        patch("google.oauth2.service_account.Credentials.from_service_account_info"),
        patch("googleapiclient.discovery.build"),
    )


class TestLookupGoogle:
    def test_email_query_returns_employee_record(self):
        mock_user = {
            "id": "g-100",
            "name": {"fullName": "Alice Wong"},
            "primaryEmail": "alice@corp.com",
            "organizations": [
                {"title": "Tech Lead", "department": "Platform"},
            ],
        }

        client = _make_secrets_client(GOOGLE_CREDS)
        p_sa, p_build = _patch_google()

        with p_sa as mock_from_sa, p_build as mock_build:
            mock_creds = MagicMock()
            mock_from_sa.return_value = mock_creds
            mock_creds.with_subject.return_value = mock_creds

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.users.return_value.get.return_value.execute.return_value = (
                mock_user
            )

            result = lookup_employee("alice@corp.com", "google", SECRET_NAME, client)

        assert result["success"] is True
        assert result["status_code"] == 200
        assert result["data"]["employeeId"] == "g-100"
        assert result["data"]["name"] == "Alice Wong"
        assert result["data"]["email"] == "alice@corp.com"
        assert result["data"]["role"] == "Tech Lead"
        assert result["data"]["department"] == "Platform"

    def test_empty_organizations_returns_empty_role_department(self):
        mock_user = {
            "id": "g-200",
            "name": {"fullName": "No Org Person"},
            "primaryEmail": "noorg@corp.com",
            "organizations": [],
        }

        client = _make_secrets_client(GOOGLE_CREDS)
        p_sa, p_build = _patch_google()

        with p_sa as mock_from_sa, p_build as mock_build:
            mock_creds = MagicMock()
            mock_from_sa.return_value = mock_creds
            mock_creds.with_subject.return_value = mock_creds

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.users.return_value.get.return_value.execute.return_value = (
                mock_user
            )

            result = lookup_employee("noorg@corp.com", "google", SECRET_NAME, client)

        assert result["success"] is True
        assert result["data"]["role"] == ""
        assert result["data"]["department"] == ""


# ---------------------------------------------------------------------------
# lookup_employee — Google error cases
# ---------------------------------------------------------------------------

class TestLookupGoogleErrors:
    def test_google_not_found(self):
        from googleapiclient.errors import HttpError

        client = _make_secrets_client(GOOGLE_CREDS)
        p_sa, p_build = _patch_google()

        with p_sa as mock_from_sa, p_build as mock_build:
            mock_creds = MagicMock()
            mock_from_sa.return_value = mock_creds
            mock_creds.with_subject.return_value = mock_creds

            mock_service = MagicMock()
            mock_build.return_value = mock_service

            resp = MagicMock()
            resp.status = 404
            mock_service.users.return_value.get.return_value.execute.side_effect = (
                HttpError(resp=resp, content=b"Not Found")
            )

            result = lookup_employee("ghost@corp.com", "google", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 404
        assert result["error"]["code"] == "EMPLOYEE_NOT_FOUND"

    def test_google_auth_error(self):
        from googleapiclient.errors import HttpError

        client = _make_secrets_client(GOOGLE_CREDS)
        p_sa, p_build = _patch_google()

        with p_sa as mock_from_sa, p_build as mock_build:
            mock_creds = MagicMock()
            mock_from_sa.return_value = mock_creds
            mock_creds.with_subject.return_value = mock_creds

            mock_service = MagicMock()
            mock_build.return_value = mock_service

            resp = MagicMock()
            resp.status = 403
            mock_service.users.return_value.get.return_value.execute.side_effect = (
                HttpError(resp=resp, content=b"Forbidden")
            )

            result = lookup_employee("jane@corp.com", "google", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 502
        assert result["error"]["code"] == "DIRECTORY_AUTH_ERROR"

    def test_google_timeout(self):
        client = _make_secrets_client(GOOGLE_CREDS)
        p_sa, p_build = _patch_google()

        with p_sa as mock_from_sa, p_build as mock_build:
            mock_creds = MagicMock()
            mock_from_sa.return_value = mock_creds
            mock_creds.with_subject.return_value = mock_creds

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.users.return_value.get.return_value.execute.side_effect = (
                Exception("Connection timed out")
            )

            result = lookup_employee("jane@corp.com", "google", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 504
        assert result["error"]["code"] == "DIRECTORY_TIMEOUT"

    def test_google_secrets_manager_failure(self):
        client = MagicMock(spec=SecretsClient)
        client.get_secret_value.side_effect = Exception("Throttled")

        result = lookup_employee("jane@corp.com", "google", SECRET_NAME, client)

        assert result["success"] is False
        assert result["status_code"] == 500
        assert result["error"]["code"] == "CREDENTIALS_UNAVAILABLE"
