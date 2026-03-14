"""Unit tests for shared DynamoDB helpers."""
import os
import pytest
import boto3
from moto import mock_aws

from shared import dynamo


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    monkeypatch.setenv("TWINS_TABLE_NAME", "KKTestTwins")
    monkeypatch.setenv("AUDIT_TABLE_NAME", "KKTestAudit")
    monkeypatch.setenv("ACCESS_TABLE_NAME", "KKTestAccess")
    # Reload module-level env vars
    dynamo.TWINS_TABLE_NAME = "KKTestTwins"
    dynamo.AUDIT_TABLE_NAME = "KKTestAudit"
    dynamo.ACCESS_TABLE_NAME = "KKTestAccess"


@pytest.fixture
def ddb_resource():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")

        ddb.create_table(
            TableName="KKTestTwins",
            KeySchema=[{"AttributeName": "employeeId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "employeeId", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "offboardDate", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "status-offboardDate-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "offboardDate", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )

        ddb.create_table(
            TableName="KKTestAudit",
            KeySchema=[
                {"AttributeName": "requestId", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "requestId", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        ddb.create_table(
            TableName="KKTestAccess",
            KeySchema=[
                {"AttributeName": "userId", "KeyType": "HASH"},
                {"AttributeName": "employeeId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "userId", "AttributeType": "S"},
                {"AttributeName": "employeeId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        yield ddb


# ---------------------------------------------------------------------------
# Twin CRUD
# ---------------------------------------------------------------------------

class TestTwinCRUD:
    def test_create_and_get_twin(self, ddb_resource):
        item = {
            "employeeId": "emp_001",
            "name": "Jane Doe",
            "status": "ingesting",
            "offboardDate": "2024-06-30",
        }
        dynamo.create_twin(item, resource=ddb_resource)
        result = dynamo.get_twin("emp_001", resource=ddb_resource)
        assert result["name"] == "Jane Doe"
        assert result["status"] == "ingesting"

    def test_get_twin_returns_none_when_missing(self, ddb_resource):
        result = dynamo.get_twin("nonexistent", resource=ddb_resource)
        assert result is None

    def test_create_twin_rejects_duplicate(self, ddb_resource):
        item = {"employeeId": "emp_001", "name": "Jane"}
        dynamo.create_twin(item, resource=ddb_resource)
        with pytest.raises(Exception):
            dynamo.create_twin(item, resource=ddb_resource)

    def test_update_twin(self, ddb_resource):
        dynamo.create_twin(
            {"employeeId": "emp_001", "status": "ingesting", "chunk_count": 0},
            resource=ddb_resource,
        )
        updated = dynamo.update_twin(
            "emp_001",
            {"status": "active", "chunk_count": 2341},
            resource=ddb_resource,
        )
        assert updated["status"] == "active"
        assert updated["chunk_count"] == 2341

    def test_delete_twin(self, ddb_resource):
        dynamo.create_twin(
            {"employeeId": "emp_001", "name": "Jane"},
            resource=ddb_resource,
        )
        dynamo.delete_twin("emp_001", resource=ddb_resource)
        assert dynamo.get_twin("emp_001", resource=ddb_resource) is None

    def test_list_twins_returns_all(self, ddb_resource):
        dynamo.create_twin(
            {"employeeId": "emp_001", "name": "Jane", "status": "active", "offboardDate": "2024-06-30"},
            resource=ddb_resource,
        )
        dynamo.create_twin(
            {"employeeId": "emp_002", "name": "John", "status": "ingesting", "offboardDate": "2024-07-15"},
            resource=ddb_resource,
        )
        result = dynamo.list_twins(resource=ddb_resource)
        assert len(result) == 2

    def test_list_twins_with_status_filter(self, ddb_resource):
        dynamo.create_twin(
            {"employeeId": "emp_001", "status": "active", "offboardDate": "2024-06-30"},
            resource=ddb_resource,
        )
        dynamo.create_twin(
            {"employeeId": "emp_002", "status": "ingesting", "offboardDate": "2024-07-15"},
            resource=ddb_resource,
        )
        result = dynamo.list_twins(status_filter="active", resource=ddb_resource)
        assert len(result) == 1
        assert result[0]["employeeId"] == "emp_001"


# ---------------------------------------------------------------------------
# Access table
# ---------------------------------------------------------------------------

class TestAccessTable:
    def test_grant_and_check_access(self, ddb_resource):
        dynamo.grant_access("user_01", "emp_001", "viewer", resource=ddb_resource)
        record = dynamo.check_access("user_01", "emp_001", resource=ddb_resource)
        assert record is not None
        assert record["role"] == "viewer"

    def test_check_access_returns_none_when_missing(self, ddb_resource):
        result = dynamo.check_access("user_01", "emp_001", resource=ddb_resource)
        assert result is None

    def test_revoke_access(self, ddb_resource):
        dynamo.grant_access("user_01", "emp_001", resource=ddb_resource)
        dynamo.revoke_access("user_01", "emp_001", resource=ddb_resource)
        assert dynamo.check_access("user_01", "emp_001", resource=ddb_resource) is None


# ---------------------------------------------------------------------------
# Audit table
# ---------------------------------------------------------------------------

class TestAuditTable:
    def test_write_audit_log(self, ddb_resource):
        item = dynamo.write_audit_log(
            request_id="req_001",
            action="query",
            details={"employee_id": "emp_001", "query": "What is the deploy process?"},
            resource=ddb_resource,
        )
        assert item["requestId"] == "req_001"
        assert item["action"] == "query"
        assert "timestamp" in item

    def test_write_audit_log_with_ttl(self, ddb_resource):
        item = dynamo.write_audit_log(
            request_id="req_002",
            action="delete_twin",
            details={"employee_id": "emp_001"},
            ttl=1893456000,
            resource=ddb_resource,
        )
        assert item["ttl"] == 1893456000
