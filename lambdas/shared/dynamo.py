"""DynamoDB helper functions for Twin CRUD, Access lookups, Audit writes."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

TWINS_TABLE_NAME = os.environ.get("TWINS_TABLE_NAME", "")
AUDIT_TABLE_NAME = os.environ.get("AUDIT_TABLE_NAME", "")
ACCESS_TABLE_NAME = os.environ.get("ACCESS_TABLE_NAME", "")


def _get_resource():
    """Return a DynamoDB resource."""
    return boto3.resource("dynamodb")


# --- Twin operations ---


def create_twin(
    item: dict[str, Any],
    resource=None,
) -> dict:
    """Create a new Twin record. Raises if employeeId already exists."""
    ddb = resource or _get_resource()
    table = ddb.Table(TWINS_TABLE_NAME)
    table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(employeeId)",
    )
    return item


def get_twin(employee_id: str, resource=None) -> dict | None:
    """Get a Twin by employeeId. Returns None if not found."""
    ddb = resource or _get_resource()
    table = ddb.Table(TWINS_TABLE_NAME)
    resp = table.get_item(Key={"employeeId": employee_id})
    return resp.get("Item")


def update_twin(
    employee_id: str,
    updates: dict[str, Any],
    resource=None,
) -> dict:
    """Update Twin attributes and return the updated item."""
    ddb = resource or _get_resource()
    table = ddb.Table(TWINS_TABLE_NAME)

    expr_names = {}
    expr_values = {}
    update_parts = []

    for i, (k, v) in enumerate(updates.items()):
        alias = f"#a{i}"
        val_alias = f":v{i}"
        expr_names[alias] = k
        expr_values[val_alias] = v
        update_parts.append(f"{alias} = {val_alias}")

    resp = table.update_item(
        Key={"employeeId": employee_id},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW",
    )
    return resp["Attributes"]


def delete_twin(employee_id: str, resource=None) -> None:
    """Delete a Twin record."""
    ddb = resource or _get_resource()
    table = ddb.Table(TWINS_TABLE_NAME)
    table.delete_item(Key={"employeeId": employee_id})


def list_twins(
    status_filter: str | None = None,
    resource=None,
) -> list[dict]:
    """List twins. Optionally filter by status using the GSI."""
    ddb = resource or _get_resource()
    table = ddb.Table(TWINS_TABLE_NAME)

    if status_filter:
        resp = table.query(
            IndexName="status-offboardDate-index",
            KeyConditionExpression=Key("status").eq(status_filter),
        )
    else:
        resp = table.scan()

    return resp.get("Items", [])


# --- Access operations ---


def check_access(
    user_id: str, employee_id: str, resource=None
) -> dict | None:
    """Check if a user has access to a twin. Returns the record or None."""
    ddb = resource or _get_resource()
    table = ddb.Table(ACCESS_TABLE_NAME)
    resp = table.get_item(Key={"userId": user_id, "employeeId": employee_id})
    return resp.get("Item")


def grant_access(
    user_id: str,
    employee_id: str,
    role: str = "viewer",
    resource=None,
) -> dict:
    """Grant a user access to a twin."""
    ddb = resource or _get_resource()
    table = ddb.Table(ACCESS_TABLE_NAME)
    item = {"userId": user_id, "employeeId": employee_id, "role": role}
    table.put_item(Item=item)
    return item


def revoke_access(
    user_id: str, employee_id: str, resource=None
) -> None:
    """Revoke a user's access to a twin."""
    ddb = resource or _get_resource()
    table = ddb.Table(ACCESS_TABLE_NAME)
    table.delete_item(Key={"userId": user_id, "employeeId": employee_id})


# --- Audit operations ---


def write_audit_log(
    request_id: str,
    action: str,
    details: dict[str, Any] | None = None,
    ttl: int | None = None,
    resource=None,
) -> dict:
    """Write an audit log entry. Returns the written item."""
    ddb = resource or _get_resource()
    table = ddb.Table(AUDIT_TABLE_NAME)
    now = datetime.now(timezone.utc).isoformat()
    item: dict[str, Any] = {
        "requestId": request_id,
        "timestamp": now,
        "action": action,
        "details": details or {},
    }
    if ttl is not None:
        item["ttl"] = ttl
    table.put_item(Item=item)
    return item


def delete_access_for_employee(
    employee_id: str, resource=None
) -> None:
    """Delete all access records for an employee (scan + batch delete)."""
    ddb = resource or _get_resource()
    table = ddb.Table(ACCESS_TABLE_NAME)

    # Scan for all records with this employeeId (sort key)
    items = []
    scan_kwargs: dict[str, Any] = {
        "FilterExpression": Key("employeeId").eq(employee_id),
    }
    while True:
        resp = table.scan(**scan_kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"userId": item["userId"], "employeeId": item["employeeId"]})
