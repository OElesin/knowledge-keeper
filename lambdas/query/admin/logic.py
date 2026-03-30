"""Business logic for the admin Lambda.

Handles twin CRUD, access management, twin deletion (right to erasure),
and directory provider configuration.
All AWS SDK interactions are injected as module dependencies for testability.
"""
from __future__ import annotations

import json as _json
import logging
import os
import urllib.request
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_YEARS = 3

REQUIRED_TWIN_FIELDS = ("employeeId", "name", "email", "role", "department", "offboardDate")

VALID_PROVIDERS = {"google", "upload", "microsoft"}

VALID_DIRECTORY_PROVIDERS = {"microsoft", "google", "ldap"}

MICROSOFT_REQUIRED_FIELDS = ("tenant_id", "client_id", "client_secret")
GOOGLE_REQUIRED_FIELDS = ("service_account_key",)
LDAP_REQUIRED_FIELDS = ("server_url", "bind_dn", "bind_password", "search_base_dn")

SETTINGS_KEY = "SETTINGS#directory"


# ---------------------------------------------------------------------------
# GET /admin/directory-config
# ---------------------------------------------------------------------------

def get_directory_config(
    *,
    dynamo_module: Any,
    secrets_module: Any,
) -> dict:
    """Return current directory provider and whether credentials are configured.

    Never returns credential values (Req 1.2, 8.2).
    Returns provider=None, credentials_configured=False when no record exists (Req 1.3).
    """
    record = dynamo_module.get_twin(SETTINGS_KEY)

    if record is None:
        return {
            "success": True,
            "status_code": 200,
            "data": {"provider": None, "credentials_configured": False},
        }

    provider = record.get("provider")
    secret_name = record.get("secret_name", "")

    # Check secret existence — graceful degradation if call fails
    credentials_configured = False
    if secret_name:
        try:
            secrets_module.describe_secret(secret_name)
            credentials_configured = True
        except Exception:
            logger.warning("Unable to verify secret existence for %s", secret_name)

    return {
        "success": True,
        "status_code": 200,
        "data": {"provider": provider, "credentials_configured": credentials_configured},
    }


# ---------------------------------------------------------------------------
# Credential validation
# ---------------------------------------------------------------------------

def validate_credential_payload(provider: str, credentials: dict) -> list[str]:
    """Validate directory provider credentials.

    Returns a list of missing/invalid field names. Empty list means valid.
    For unknown provider types, returns ``["VALIDATION_ERROR"]``.
    """
    if provider not in VALID_DIRECTORY_PROVIDERS:
        return ["VALIDATION_ERROR"]

    if provider == "microsoft":
        return [
            f for f in MICROSOFT_REQUIRED_FIELDS
            if not credentials.get(f, "").strip()
        ]

    if provider == "ldap":
        return [
            f for f in LDAP_REQUIRED_FIELDS
            if not credentials.get(f, "").strip()
        ]

    # provider == "google"
    missing: list[str] = []
    raw_key = credentials.get("service_account_key", "").strip()
    if not raw_key:
        missing.append("service_account_key")
    else:
        try:
            _json.loads(raw_key)
        except (ValueError, TypeError):
            missing.append("service_account_key")
    return missing


# ---------------------------------------------------------------------------
# PUT /admin/directory-config
# ---------------------------------------------------------------------------

def save_directory_config(
    body: dict[str, Any],
    request_id: str,
    *,
    dynamo_module: Any,
    secrets_module: Any,
) -> dict:
    """Validate, store credentials in Secrets Manager, save settings to DynamoDB.

    Never logs credential values (Req 8.1).
    Overwrites any previously stored credentials (Req 2.7).
    Writes audit log entry on success (Req 2.8).
    """
    provider = body.get("provider", "")
    credentials = body.get("credentials", {})

    # Validate provider and credentials
    invalid_fields = validate_credential_payload(provider, credentials)
    if invalid_fields:
        # Unknown provider returns ["VALIDATION_ERROR"]
        if invalid_fields == ["VALIDATION_ERROR"]:
            return {
                "success": False,
                "status_code": 400,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"Invalid provider '{provider}'. Valid providers: google, ldap, microsoft",
                    "details": {},
                },
            }
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"Missing required fields: {', '.join(invalid_fields)}",
                "details": {"missing": invalid_fields},
            },
        }

    # Apply LDAP defaults for optional fields before storing (Req 3.2, 3.3, 3.5)
    if provider == "ldap":
        if not credentials.get("port", "").strip():
            credentials["port"] = "389"
        if not credentials.get("search_filter_template", "").strip():
            credentials["search_filter_template"] = "(|(mail={query})(uid={query}))"

    env = os.environ.get("ENVIRONMENT", "dev")
    secret_name = f"kk/{env}/directory-creds"
    now = datetime.now(timezone.utc)

    # Store credentials in Secrets Manager (overwrites previous — Req 2.7)
    try:
        try:
            secrets_module.put_secret_value(
                secret_name,
                _json.dumps(credentials),
            )
        except Exception as put_err:
            # Secret may not exist yet — try creating it
            err_code = getattr(put_err, "response", {}).get("Error", {}).get("Code", "")
            if err_code == "ResourceNotFoundException":
                secrets_module.create_secret(
                    secret_name,
                    _json.dumps(credentials),
                )
            else:
                raise
    except Exception:
        logger.exception("Failed to store directory credentials")
        return {
            "success": False,
            "status_code": 500,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to store credentials",
                "details": {},
            },
        }

    # Save settings record to DynamoDB
    try:
        dynamo_module.update_twin(
            SETTINGS_KEY,
            {
                "provider": provider,
                "secret_name": secret_name,
                "updated_at": now.isoformat(),
                "updated_by": request_id,
            },
        )
    except Exception:
        logger.exception("Failed to save directory settings record")
        return {
            "success": False,
            "status_code": 500,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to save directory configuration",
                "details": {},
            },
        }

    # Audit log — never log credential values (Req 8.1)
    dynamo_module.write_audit_log(
        request_id=request_id,
        action="save_directory_config",
        details={"provider": provider},
    )

    return {
        "success": True,
        "status_code": 200,
        "data": {"provider": provider, "credentials_configured": True},
    }


CONNECTION_TIMEOUT_SECONDS = 10


# ---------------------------------------------------------------------------
# POST /admin/directory-config/test
# ---------------------------------------------------------------------------

def _test_microsoft_connection(credentials: dict) -> dict:
    """Acquire an OAuth2 client-credentials token from Microsoft Entra ID.

    Returns ``{test_passed, message}``.  Never persists credentials (Req 3.4).
    """
    tenant_id = credentials["tenant_id"]
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    form_data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": credentials["client_id"],
        "client_secret": credentials["client_secret"],
        "scope": "https://graph.microsoft.com/.default",
    }).encode()

    req = urllib.request.Request(token_url, data=form_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=CONNECTION_TIMEOUT_SECONDS) as resp:
            if resp.status == 200:
                return {"test_passed": True, "message": "Connection successful"}
            return {"test_passed": False, "message": f"Unexpected status {resp.status}"}
    except urllib.error.HTTPError as exc:
        return {"test_passed": False, "message": f"Authentication failed: {exc.reason}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
        if "timed out" in reason.lower() or isinstance(exc, TimeoutError):
            return {
                "test_passed": False,
                "message": "Connection timed out after 10 seconds",
            }
        return {"test_passed": False, "message": f"Connection failed: {reason}"}


def _test_google_connection(credentials: dict) -> dict:
    """Build service-account credentials and call a lightweight Directory API endpoint.

    Returns ``{test_passed, message}``.  Never persists credentials (Req 3.4).
    """
    import time
    import base64

    sa_key = _json.loads(credentials["service_account_key"])

    # Build a self-signed JWT for the directory API scope
    now = int(time.time())
    header = base64.urlsafe_b64encode(
        _json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=")

    claim_set = {
        "iss": sa_key.get("client_email", ""),
        "scope": "https://www.googleapis.com/auth/admin.directory.user.readonly",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 300,
    }
    delegated_admin = credentials.get("delegated_admin", "")
    if delegated_admin:
        claim_set["sub"] = delegated_admin

    payload = base64.urlsafe_b64encode(
        _json.dumps(claim_set).encode()
    ).rstrip(b"=")

    signing_input = header + b"." + payload

    # Sign with the service account private key
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        private_key = serialization.load_pem_private_key(
            sa_key["private_key"].encode(), password=None,
        )
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")
    except Exception as exc:
        return {
            "test_passed": False,
            "message": f"Failed to sign JWT: {exc}",
        }

    jwt_token = (signing_input + b"." + sig_b64).decode()

    # Exchange JWT for access token
    token_url = "https://oauth2.googleapis.com/token"
    form_data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt_token,
    }).encode()

    req = urllib.request.Request(token_url, data=form_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=CONNECTION_TIMEOUT_SECONDS) as resp:
            if resp.status == 200:
                return {"test_passed": True, "message": "Connection successful"}
            return {"test_passed": False, "message": f"Unexpected status {resp.status}"}
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode()
            err = _json.loads(body)
            detail = err.get("error_description", exc.reason)
        except Exception:
            detail = exc.reason
        return {"test_passed": False, "message": f"Authentication failed: {detail}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
        if "timed out" in reason.lower() or isinstance(exc, TimeoutError):
            return {
                "test_passed": False,
                "message": "Connection timed out after 10 seconds",
            }
        return {"test_passed": False, "message": f"Connection failed: {reason}"}


def _test_ldap_connection(credentials: dict) -> dict:
    """Connect to an LDAP server and perform a simple bind.

    Returns ``{test_passed, message}``.  10-second timeout.
    Never persists credentials (Req 4.4).
    """
    import ldap3
    from ldap3.core.exceptions import LDAPBindError, LDAPSocketOpenError, LDAPSocketReceiveError

    server_url = credentials["server_url"]
    port = int(credentials.get("port") or 389)
    bind_dn = credentials["bind_dn"]
    bind_password = credentials["bind_password"]

    try:
        server = ldap3.Server(server_url, port=port, connect_timeout=CONNECTION_TIMEOUT_SECONDS)
        conn = ldap3.Connection(
            server,
            user=bind_dn,
            password=bind_password,
            auto_bind=True,
            receive_timeout=CONNECTION_TIMEOUT_SECONDS,
        )
        conn.unbind()
        return {"test_passed": True, "message": "Connection successful"}
    except LDAPBindError as exc:
        return {"test_passed": False, "message": f"LDAP bind failed: {exc}"}
    except LDAPSocketOpenError as exc:
        return {"test_passed": False, "message": f"LDAP server unreachable: {exc}"}
    except (LDAPSocketReceiveError, TimeoutError) as exc:
        return {"test_passed": False, "message": "Connection timed out after 10 seconds"}
    except Exception as exc:
        return {"test_passed": False, "message": f"Connection failed: {exc}"}


def test_directory_connection(body: dict[str, Any]) -> dict:
    """Test directory provider credentials without persisting anything.

    Validates the payload, then attempts a lightweight authentication call
    against the selected provider with a 10-second timeout.

    Never stores credentials in Secrets Manager or DynamoDB (Req 3.4).
    Never logs credential values (Req 8.1).
    """
    provider = body.get("provider", "")
    credentials = body.get("credentials", {})

    invalid_fields = validate_credential_payload(provider, credentials)
    if invalid_fields:
        if invalid_fields == ["VALIDATION_ERROR"]:
            return {
                "success": False,
                "status_code": 400,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"Invalid provider '{provider}'. Valid providers: google, ldap, microsoft",
                    "details": {},
                },
            }
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"Missing required fields: {', '.join(invalid_fields)}",
                "details": {"missing": invalid_fields},
            },
        }

    if provider == "microsoft":
        result = _test_microsoft_connection(credentials)
    elif provider == "ldap":
        result = _test_ldap_connection(credentials)
    else:
        result = _test_google_connection(credentials)

    return {
        "success": True,
        "status_code": 200,
        "data": result,
    }


# ---------------------------------------------------------------------------
# POST /twins — create twin
# ---------------------------------------------------------------------------

def create_twin(
    body: dict[str, Any],
    request_id: str,
    *,
    dynamo_module: Any,
    lambda_module: Any | None = None,
) -> dict:
    """Create a new Twin record.

    Returns {"success": True, "status_code": 201, "data": {...}}
    or      {"success": False, "status_code": int, "error": {...}}
    """
    # Validate required fields
    missing = [f for f in REQUIRED_TWIN_FIELDS if not body.get(f)]
    if missing:
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"Missing required fields: {', '.join(missing)}",
                "details": {"missing": missing},
            },
        }

    employee_id = body["employeeId"]

    # Check for existing twin
    existing = dynamo_module.get_twin(employee_id)
    if existing is not None:
        return {
            "success": False,
            "status_code": 409,
            "error": {
                "code": "TWIN_ALREADY_EXISTS",
                "message": f"Twin already exists for employee {employee_id}",
                "details": {},
            },
        }

    # Compute retention_expiry
    retention_years = int(os.environ.get("RETENTION_YEARS", DEFAULT_RETENTION_YEARS))
    offboard_date_str = body["offboardDate"]
    try:
        offboard_dt = date.fromisoformat(offboard_date_str)
    except (ValueError, TypeError):
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "offboardDate must be a valid ISO date (YYYY-MM-DD)",
                "details": {},
            },
        }

    retention_expiry = offboard_dt + timedelta(days=retention_years * 365)

    provider = body.get("provider", "upload")

    if provider not in VALID_PROVIDERS:
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"Invalid provider '{provider}'. Valid providers: {', '.join(sorted(VALID_PROVIDERS))}",
                "details": {"validProviders": sorted(VALID_PROVIDERS)},
            },
        }

    item = {
        "employeeId": employee_id,
        "name": body["name"],
        "email": body["email"],
        "role": body["role"],
        "department": body["department"],
        "offboardDate": offboard_date_str,
        "status": "ingesting",
        "chunkCount": 0,
        "topicIndex": [],
        "retentionExpiry": retention_expiry.isoformat(),
        "provider": provider,
    }
    if body.get("tenureStart"):
        item["tenureStart"] = body["tenureStart"]

    try:
        dynamo_module.create_twin(item)
    except Exception:
        logger.exception("Failed to create twin %s", employee_id)
        return {
            "success": False,
            "status_code": 500,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to create twin record",
                "details": {},
            },
        }

    # Optionally invoke email_fetcher async for Google provider
    if provider == "google" and lambda_module is not None:
        fetcher_fn = os.environ.get("EMAIL_FETCHER_FN_NAME", "")
        if fetcher_fn:
            try:
                lambda_module.invoke_async(
                    function_name=fetcher_fn,
                    payload={"employeeId": employee_id, "email": body["email"]},
                )
            except Exception:
                logger.exception("Failed to invoke email_fetcher for %s", employee_id)

    # Invoke M365 email fetcher async for Microsoft provider
    elif provider == "microsoft" and lambda_module is not None:
        m365_fetcher_fn = os.environ.get("M365_EMAIL_FETCHER_FN_NAME", "")
        if m365_fetcher_fn:
            try:
                lambda_module.invoke_async(
                    function_name=m365_fetcher_fn,
                    payload={"employeeId": employee_id, "email": body["email"]},
                )
            except Exception:
                logger.exception("Failed to invoke m365_email_fetcher for %s", employee_id)

    # Audit log
    dynamo_module.write_audit_log(
        request_id=request_id,
        action="create_twin",
        details={"employeeId": employee_id, "provider": provider},
    )

    return {"success": True, "status_code": 201, "data": item}


# ---------------------------------------------------------------------------
# GET /twins — list twins
# ---------------------------------------------------------------------------

def list_twins(
    query_params: dict[str, str] | None,
    *,
    dynamo_module: Any,
) -> dict:
    """List all twins, optionally filtered by status."""
    status_filter = (query_params or {}).get("status")
    items = dynamo_module.list_twins(status_filter=status_filter)
    return {"success": True, "status_code": 200, "data": {"twins": items}}


# ---------------------------------------------------------------------------
# GET /twins/{employeeId} — get twin detail
# ---------------------------------------------------------------------------

def get_twin(
    employee_id: str,
    *,
    dynamo_module: Any,
) -> dict:
    """Get a single twin by employeeId."""
    twin = dynamo_module.get_twin(employee_id)
    if twin is None:
        return {
            "success": False,
            "status_code": 404,
            "error": {
                "code": "TWIN_NOT_FOUND",
                "message": f"No twin found for employee {employee_id}",
                "details": {},
            },
        }
    return {"success": True, "status_code": 200, "data": twin}


# ---------------------------------------------------------------------------
# DELETE /twins/{employeeId} — delete twin (right to erasure)
# ---------------------------------------------------------------------------

def delete_twin(
    employee_id: str,
    request_id: str,
    *,
    dynamo_module: Any,
    s3vectors_module: Any,
    s3_module: Any,
) -> dict:
    """Delete all data associated with a twin."""
    twin = dynamo_module.get_twin(employee_id)
    if twin is None:
        return {
            "success": False,
            "status_code": 404,
            "error": {
                "code": "TWIN_NOT_FOUND",
                "message": f"No twin found for employee {employee_id}",
                "details": {},
            },
        }

    now = datetime.now(timezone.utc)

    # 1. Delete vectors from S3 Vectors
    try:
        s3vectors_module.delete_vectors_for_employee(employee_id)
    except Exception:
        logger.exception("Failed to delete vectors for %s", employee_id)

    # 2. Delete S3 raw archive objects
    try:
        bucket = os.environ.get("RAW_ARCHIVES_BUCKET", "")
        if bucket:
            s3_module.delete_objects_with_prefix(bucket, f"{employee_id}/")
    except Exception:
        logger.exception("Failed to delete S3 objects for %s", employee_id)

    # 3. Delete DynamoDB records
    dynamo_module.delete_twin(employee_id)
    dynamo_module.delete_access_for_employee(employee_id)

    # 4. Audit log
    dynamo_module.write_audit_log(
        request_id=request_id,
        action="delete_twin",
        details={"employeeId": employee_id, "deletedAt": now.isoformat()},
    )

    return {
        "success": True,
        "status_code": 200,
        "data": {"employeeId": employee_id, "deletedAt": now.isoformat()},
    }



# ---------------------------------------------------------------------------
# POST /twins/{employeeId}/access — grant access
# ---------------------------------------------------------------------------

def grant_access(
    employee_id: str,
    body: dict[str, Any],
    request_id: str,
    *,
    dynamo_module: Any,
) -> dict:
    """Grant a user access to a twin."""
    user_id = body.get("userId", "").strip()
    role = body.get("role", "viewer").strip()

    if not user_id:
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "userId is required",
                "details": {},
            },
        }

    if role not in ("admin", "viewer"):
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "role must be 'admin' or 'viewer'",
                "details": {},
            },
        }

    # Verify twin exists
    twin = dynamo_module.get_twin(employee_id)
    if twin is None:
        return {
            "success": False,
            "status_code": 404,
            "error": {
                "code": "TWIN_NOT_FOUND",
                "message": f"No twin found for employee {employee_id}",
                "details": {},
            },
        }

    record = dynamo_module.grant_access(user_id, employee_id, role)

    dynamo_module.write_audit_log(
        request_id=request_id,
        action="grant_access",
        details={"employeeId": employee_id, "userId": user_id, "role": role},
    )

    return {"success": True, "status_code": 200, "data": record}


# ---------------------------------------------------------------------------
# DELETE /twins/{employeeId}/access/{userId} — revoke access
# ---------------------------------------------------------------------------

def revoke_access(
    employee_id: str,
    user_id: str,
    request_id: str,
    *,
    dynamo_module: Any,
) -> dict:
    """Revoke a user's access to a twin."""
    dynamo_module.revoke_access(user_id, employee_id)

    dynamo_module.write_audit_log(
        request_id=request_id,
        action="revoke_access",
        details={"employeeId": employee_id, "userId": user_id},
    )

    return {
        "success": True,
        "status_code": 200,
        "data": {"employeeId": employee_id, "userId": user_id},
    }
