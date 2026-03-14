"""Unit tests for admin logic."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from lambdas.query.admin.logic import (
    create_twin,
    delete_twin,
    get_twin,
    grant_access,
    list_twins,
    revoke_access,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_twin(**overrides) -> dict:
    """Build a minimal twin record."""
    twin = {
        "employeeId": "emp_123",
        "name": "Jane Doe",
        "email": "jane@corp.com",
        "role": "Senior SRE",
        "department": "Platform",
        "offboardDate": "2024-06-30",
        "status": "active",
        "chunkCount": 500,
        "retentionExpiry": "2027-06-29",
        "provider": "upload",
    }
    twin.update(overrides)
    return twin


def _valid_create_body(**overrides) -> dict:
    """Build a valid POST /twins request body."""
    body = {
        "employeeId": "emp_456",
        "name": "John Smith",
        "email": "john@corp.com",
        "role": "Staff Engineer",
        "department": "Backend",
        "offboardDate": "2025-03-01",
    }
    body.update(overrides)
    return body


def _mock_dynamo(twin=None, twins_list=None):
    """Return a mock dynamo module."""
    mod = MagicMock()
    mod.get_twin.return_value = twin
    mod.list_twins.return_value = twins_list or []
    mod.create_twin.return_value = None
    mod.delete_twin.return_value = None
    mod.grant_access.side_effect = lambda uid, eid, role: {
        "userId": uid, "employeeId": eid, "role": role,
    }
    mod.revoke_access.return_value = None
    mod.delete_access_for_employee.return_value = None
    mod.write_audit_log.return_value = {}
    return mod


def _mock_s3vectors():
    """Return a mock s3vectors module."""
    mod = MagicMock()
    mod.delete_vectors_for_employee.return_value = None
    return mod


def _mock_s3():
    """Return a mock S3 helper."""
    mod = MagicMock()
    mod.delete_objects_with_prefix.return_value = None
    return mod


def _mock_lambda():
    """Return a mock Lambda invoke helper."""
    mod = MagicMock()
    mod.invoke_async.return_value = None
    return mod


# ---------------------------------------------------------------------------
# create_twin
# ---------------------------------------------------------------------------

class TestCreateTwin:
    def test_happy_path_creates_twin(self):
        dynamo = _mock_dynamo(twin=None)
        body = _valid_create_body()
        result = create_twin(body, "req_001", dynamo_module=dynamo)

        assert result["success"] is True
        assert result["status_code"] == 201
        assert result["data"]["employeeId"] == "emp_456"
        assert result["data"]["status"] == "ingesting"
        assert result["data"]["retentionExpiry"] == "2028-02-29"
        dynamo.create_twin.assert_called_once()
        dynamo.write_audit_log.assert_called_once()

    def test_missing_required_fields_returns_400(self):
        dynamo = _mock_dynamo()
        body = {"employeeId": "emp_456"}  # missing most fields
        result = create_twin(body, "req_001", dynamo_module=dynamo)

        assert result["success"] is False
        assert result["status_code"] == 400
        assert result["error"]["code"] == "VALIDATION_ERROR"
        assert "name" in result["error"]["details"]["missing"]

    def test_existing_twin_returns_409(self):
        dynamo = _mock_dynamo(twin=_make_twin(employeeId="emp_456"))
        body = _valid_create_body()
        result = create_twin(body, "req_001", dynamo_module=dynamo)

        assert result["success"] is False
        assert result["status_code"] == 409
        assert result["error"]["code"] == "TWIN_ALREADY_EXISTS"

    def test_invalid_offboard_date_returns_400(self):
        dynamo = _mock_dynamo(twin=None)
        body = _valid_create_body(offboardDate="not-a-date")
        result = create_twin(body, "req_001", dynamo_module=dynamo)

        assert result["success"] is False
        assert result["status_code"] == 400
        assert "ISO date" in result["error"]["message"]

    def test_google_provider_invokes_email_fetcher(self):
        dynamo = _mock_dynamo(twin=None)
        lam = _mock_lambda()
        body = _valid_create_body(provider="google")

        with patch.dict(os.environ, {"EMAIL_FETCHER_FN_NAME": "kk-dev-email-fetcher"}):
            result = create_twin(
                body, "req_001",
                dynamo_module=dynamo, lambda_module=lam,
            )

        assert result["success"] is True
        lam.invoke_async.assert_called_once()
        call_kwargs = lam.invoke_async.call_args[1]
        assert call_kwargs["payload"]["employeeId"] == "emp_456"

    def test_upload_provider_does_not_invoke_fetcher(self):
        dynamo = _mock_dynamo(twin=None)
        lam = _mock_lambda()
        body = _valid_create_body(provider="upload")

        result = create_twin(
            body, "req_001",
            dynamo_module=dynamo, lambda_module=lam,
        )

        assert result["success"] is True
        lam.invoke_async.assert_not_called()


    def test_retention_expiry_uses_env_override(self):
        dynamo = _mock_dynamo(twin=None)
        body = _valid_create_body(offboardDate="2025-01-01")

        with patch.dict(os.environ, {"RETENTION_YEARS": "5"}):
            result = create_twin(body, "req_001", dynamo_module=dynamo)

        assert result["success"] is True
        assert result["data"]["retentionExpiry"] == "2029-12-31"

    def test_tenure_start_included_when_provided(self):
        dynamo = _mock_dynamo(twin=None)
        body = _valid_create_body(tenureStart="2020-01-15")
        result = create_twin(body, "req_001", dynamo_module=dynamo)

        assert result["success"] is True
        assert result["data"]["tenureStart"] == "2020-01-15"

    def test_dynamo_create_failure_returns_500(self):
        dynamo = _mock_dynamo(twin=None)
        dynamo.create_twin.side_effect = Exception("DynamoDB error")
        body = _valid_create_body()
        result = create_twin(body, "req_001", dynamo_module=dynamo)

        assert result["success"] is False
        assert result["status_code"] == 500


# ---------------------------------------------------------------------------
# list_twins
# ---------------------------------------------------------------------------

class TestListTwins:
    def test_returns_all_twins(self):
        twins = [_make_twin(), _make_twin(employeeId="emp_789")]
        dynamo = _mock_dynamo(twins_list=twins)
        result = list_twins(None, dynamo_module=dynamo)

        assert result["success"] is True
        assert len(result["data"]["twins"]) == 2
        dynamo.list_twins.assert_called_once_with(status_filter=None)

    def test_filters_by_status(self):
        dynamo = _mock_dynamo(twins_list=[_make_twin()])
        result = list_twins({"status": "active"}, dynamo_module=dynamo)

        assert result["success"] is True
        dynamo.list_twins.assert_called_once_with(status_filter="active")

    def test_empty_list(self):
        dynamo = _mock_dynamo(twins_list=[])
        result = list_twins(None, dynamo_module=dynamo)

        assert result["success"] is True
        assert result["data"]["twins"] == []


# ---------------------------------------------------------------------------
# get_twin
# ---------------------------------------------------------------------------

class TestGetTwin:
    def test_returns_twin_when_found(self):
        twin = _make_twin()
        dynamo = _mock_dynamo(twin=twin)
        result = get_twin("emp_123", dynamo_module=dynamo)

        assert result["success"] is True
        assert result["data"]["employeeId"] == "emp_123"

    def test_returns_404_when_not_found(self):
        dynamo = _mock_dynamo(twin=None)
        result = get_twin("emp_999", dynamo_module=dynamo)

        assert result["success"] is False
        assert result["status_code"] == 404
        assert result["error"]["code"] == "TWIN_NOT_FOUND"


# ---------------------------------------------------------------------------
# delete_twin
# ---------------------------------------------------------------------------

class TestDeleteTwin:
    def test_happy_path_deletes_all_resources(self):
        twin = _make_twin()
        dynamo = _mock_dynamo(twin=twin)
        s3v = _mock_s3vectors()
        s3 = _mock_s3()

        with patch.dict(os.environ, {"RAW_ARCHIVES_BUCKET": "test-bucket"}):
            result = delete_twin(
                "emp_123", "req_001",
                dynamo_module=dynamo, s3vectors_module=s3v, s3_module=s3,
            )

        assert result["success"] is True
        assert result["data"]["employeeId"] == "emp_123"
        assert "deletedAt" in result["data"]
        s3v.delete_vectors_for_employee.assert_called_once_with("emp_123")
        s3.delete_objects_with_prefix.assert_called_once_with("test-bucket", "emp_123/")
        dynamo.delete_twin.assert_called_once_with("emp_123")
        dynamo.delete_access_for_employee.assert_called_once_with("emp_123")
        dynamo.write_audit_log.assert_called_once()

    def test_returns_404_when_twin_not_found(self):
        dynamo = _mock_dynamo(twin=None)
        result = delete_twin(
            "emp_999", "req_001",
            dynamo_module=dynamo, s3vectors_module=_mock_s3vectors(), s3_module=_mock_s3(),
        )

        assert result["success"] is False
        assert result["status_code"] == 404

    def test_continues_when_vector_delete_fails(self):
        twin = _make_twin()
        dynamo = _mock_dynamo(twin=twin)
        s3v = _mock_s3vectors()
        s3v.delete_vectors_for_employee.side_effect = Exception("S3Vectors error")

        with patch.dict(os.environ, {"RAW_ARCHIVES_BUCKET": "test-bucket"}):
            result = delete_twin(
                "emp_123", "req_001",
                dynamo_module=dynamo, s3vectors_module=s3v, s3_module=_mock_s3(),
            )

        # Should still succeed — deletion is best-effort for vectors/S3
        assert result["success"] is True
        dynamo.delete_twin.assert_called_once()

    def test_continues_when_s3_delete_fails(self):
        twin = _make_twin()
        dynamo = _mock_dynamo(twin=twin)
        s3 = _mock_s3()
        s3.delete_objects_with_prefix.side_effect = Exception("S3 error")

        with patch.dict(os.environ, {"RAW_ARCHIVES_BUCKET": "test-bucket"}):
            result = delete_twin(
                "emp_123", "req_001",
                dynamo_module=dynamo, s3vectors_module=_mock_s3vectors(), s3_module=s3,
            )

        assert result["success"] is True
        dynamo.delete_twin.assert_called_once()


# ---------------------------------------------------------------------------
# grant_access
# ---------------------------------------------------------------------------

class TestGrantAccess:
    def test_happy_path_grants_viewer(self):
        dynamo = _mock_dynamo(twin=_make_twin())
        body = {"userId": "user_1", "role": "viewer"}
        result = grant_access("emp_123", body, "req_001", dynamo_module=dynamo)

        assert result["success"] is True
        assert result["data"]["role"] == "viewer"
        dynamo.grant_access.assert_called_once_with("user_1", "emp_123", "viewer")
        dynamo.write_audit_log.assert_called_once()

    def test_grants_admin_role(self):
        dynamo = _mock_dynamo(twin=_make_twin())
        body = {"userId": "user_1", "role": "admin"}
        result = grant_access("emp_123", body, "req_001", dynamo_module=dynamo)

        assert result["success"] is True
        assert result["data"]["role"] == "admin"

    def test_missing_user_id_returns_400(self):
        dynamo = _mock_dynamo(twin=_make_twin())
        body = {"role": "viewer"}
        result = grant_access("emp_123", body, "req_001", dynamo_module=dynamo)

        assert result["success"] is False
        assert result["status_code"] == 400
        assert "userId" in result["error"]["message"]

    def test_invalid_role_returns_400(self):
        dynamo = _mock_dynamo(twin=_make_twin())
        body = {"userId": "user_1", "role": "superadmin"}
        result = grant_access("emp_123", body, "req_001", dynamo_module=dynamo)

        assert result["success"] is False
        assert result["status_code"] == 400

    def test_twin_not_found_returns_404(self):
        dynamo = _mock_dynamo(twin=None)
        body = {"userId": "user_1", "role": "viewer"}
        result = grant_access("emp_999", body, "req_001", dynamo_module=dynamo)

        assert result["success"] is False
        assert result["status_code"] == 404

    def test_defaults_to_viewer_role(self):
        dynamo = _mock_dynamo(twin=_make_twin())
        body = {"userId": "user_1"}
        result = grant_access("emp_123", body, "req_001", dynamo_module=dynamo)

        assert result["success"] is True
        assert result["data"]["role"] == "viewer"


# ---------------------------------------------------------------------------
# revoke_access
# ---------------------------------------------------------------------------

class TestRevokeAccess:
    def test_happy_path_revokes_access(self):
        dynamo = _mock_dynamo()
        result = revoke_access("emp_123", "user_1", "req_001", dynamo_module=dynamo)

        assert result["success"] is True
        assert result["data"]["employeeId"] == "emp_123"
        assert result["data"]["userId"] == "user_1"
        dynamo.revoke_access.assert_called_once_with("user_1", "emp_123")
        dynamo.write_audit_log.assert_called_once()

    def test_audit_log_contains_details(self):
        dynamo = _mock_dynamo()
        revoke_access("emp_123", "user_1", "req_002", dynamo_module=dynamo)

        call_kwargs = dynamo.write_audit_log.call_args[1]
        assert call_kwargs["request_id"] == "req_002"
        assert call_kwargs["action"] == "revoke_access"
        assert call_kwargs["details"]["userId"] == "user_1"
