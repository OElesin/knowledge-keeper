"""Business logic for the directory_lookup Lambda.

Looks up employee information from Microsoft Entra ID (Graph API),
Google Workspace (Admin SDK Directory API), or an LDAP directory
and returns a normalized Employee_Record.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import ldap3
from ldap3.core.exceptions import LDAPBindError, LDAPSocketOpenError, LDAPSocketReceiveError
import msal
import requests

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SELECT = "id,displayName,mail,jobTitle,department"
REQUEST_TIMEOUT = 10


class SecretsClient(Protocol):
    """Protocol for Secrets Manager client dependency injection."""

    def get_secret_value(self, **kwargs: Any) -> dict: ...


def _error(status_code: int, code: str, message: str) -> dict:
    return {
        "success": False,
        "status_code": status_code,
        "error": {"code": code, "message": message, "details": {}},
    }


def _success(data: dict) -> dict:
    return {"success": True, "status_code": 200, "data": data}


def _is_email(query: str) -> bool:
    """Heuristic check: query is email-shaped if it contains '@'."""
    return "@" in query


def _normalize_microsoft(graph_user: dict) -> dict:
    """Map Microsoft Graph API user fields to Employee_Record."""
    return {
        "employeeId": graph_user.get("id") or "",
        "name": graph_user.get("displayName") or "",
        "email": graph_user.get("mail") or "",
        "role": graph_user.get("jobTitle") or "",
        "department": graph_user.get("department") or "",
    }


def _normalize_google(directory_user: dict) -> dict:
    """Map Google Directory API user fields to Employee_Record."""
    orgs = directory_user.get("organizations") or []
    first_org = orgs[0] if orgs else {}
    return {
        "employeeId": directory_user.get("id") or "",
        "name": (directory_user.get("name") or {}).get("fullName") or "",
        "email": directory_user.get("primaryEmail") or "",
        "role": first_org.get("title") or "",
        "department": first_org.get("department") or "",
    }

def _normalize_ldap(entry_attributes: dict) -> dict:
    """Map LDAP entry attributes to Employee_Record."""
    return {
        "employeeId": entry_attributes.get("uid") or "",
        "name": entry_attributes.get("cn") or "",
        "email": entry_attributes.get("mail") or "",
        "role": entry_attributes.get("title") or "",
        "department": entry_attributes.get("departmentNumber") or "",
    }



def _handle_http_error(status_code: int) -> dict:
    """Map directory provider HTTP errors to structured error responses."""
    if status_code in (401, 403):
        return _error(
            502,
            "DIRECTORY_AUTH_ERROR",
            "Directory credentials are invalid or insufficient.",
        )
    if status_code == 429:
        return _error(
            429,
            "DIRECTORY_RATE_LIMITED",
            "Directory rate limit reached. Please retry after a short delay.",
        )
    if status_code == 404:
        return _error(
            404,
            "EMPLOYEE_NOT_FOUND",
            "No employee found matching the provided query.",
        )
    if 500 <= status_code < 600:
        return _error(
            502,
            "DIRECTORY_UNAVAILABLE",
            "The directory service is temporarily unavailable.",
        )
    # Unexpected status — treat as unavailable
    return _error(
        502,
        "DIRECTORY_UNAVAILABLE",
        f"Unexpected directory response status {status_code}.",
    )


def _lookup_microsoft(
    query: str,
    secret_name: str,
    secrets_client: SecretsClient,
) -> dict:
    """Look up an employee via Microsoft Graph API."""
    try:
        resp = secrets_client.get_secret_value(SecretId=secret_name)
        creds = json.loads(resp["SecretString"])
    except Exception:
        logger.warning("Failed to retrieve directory credentials from Secrets Manager")
        return _error(
            500,
            "CREDENTIALS_UNAVAILABLE",
            "Unable to retrieve directory credentials.",
        )

    tenant_id = creds["tenant_id"]
    client_id = creds["client_id"]
    client_secret = creds["client_secret"]

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )
    token_result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in token_result:
        return _error(
            502,
            "DIRECTORY_AUTH_ERROR",
            "Failed to acquire Microsoft Graph API token.",
        )

    token = token_result["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    try:
        if _is_email(query):
            url = f"{GRAPH_BASE}/users/{query}"
            resp_api = requests.get(
                url,
                headers=headers,
                params={"$select": GRAPH_SELECT},
                timeout=REQUEST_TIMEOUT,
            )
        else:
            url = f"{GRAPH_BASE}/users"
            resp_api = requests.get(
                url,
                headers=headers,
                params={
                    "$filter": f"employeeId eq '{query}'",
                    "$select": GRAPH_SELECT,
                },
                timeout=REQUEST_TIMEOUT,
            )
    except requests.Timeout:
        return _error(
            504,
            "DIRECTORY_TIMEOUT",
            "The directory provider did not respond within 10 seconds.",
        )

    if resp_api.status_code != 200:
        return _handle_http_error(resp_api.status_code)

    data = resp_api.json()

    # For filter queries, Graph returns {"value": [...]}
    if "value" in data:
        users = data["value"]
        if not users:
            return _error(
                404,
                "EMPLOYEE_NOT_FOUND",
                "No employee found matching the provided query.",
            )
        return _success(_normalize_microsoft(users[0]))

    return _success(_normalize_microsoft(data))


def _lookup_google(
    query: str,
    secret_name: str,
    secrets_client: SecretsClient,
) -> dict:
    """Look up an employee via Google Workspace Admin SDK Directory API."""
    try:
        resp = secrets_client.get_secret_value(SecretId=secret_name)
        creds_json = json.loads(resp["SecretString"])
    except Exception:
        logger.warning("Failed to retrieve directory credentials from Secrets Manager")
        return _error(
            500,
            "CREDENTIALS_UNAVAILABLE",
            "Unable to retrieve directory credentials.",
        )

    try:
        from google.oauth2 import service_account  # noqa: E402
        from googleapiclient.discovery import build  # noqa: E402
        from googleapiclient.errors import HttpError  # noqa: E402

        credentials = service_account.Credentials.from_service_account_info(
            creds_json,
            scopes=["https://www.googleapis.com/auth/admin.directory.user.readonly"],
        )
        if "delegated_admin" in creds_json:
            credentials = credentials.with_subject(creds_json["delegated_admin"])

        service = build(
            "admin",
            "directory_v1",
            credentials=credentials,
            cache_discovery=False,
        )

        user = (
            service.users()
            .get(userKey=query)
            .execute(num_retries=0)
        )
    except HttpError as exc:
        return _handle_http_error(exc.resp.status)
    except Exception as exc:
        # Detect timeout-like errors
        exc_str = str(exc).lower()
        if "timeout" in exc_str or "timed out" in exc_str:
            return _error(
                504,
                "DIRECTORY_TIMEOUT",
                "The directory provider did not respond within 10 seconds.",
            )
        raise

    return _success(_normalize_google(user))


def _lookup_ldap(
    query: str,
    secret_name: str,
    secrets_client: SecretsClient,
) -> dict:
    """Look up an employee via LDAP search.

    Retrieves LDAP connection params from Secrets Manager, connects with
    simple bind, searches using the configured filter template with {query}
    substituted, and normalizes the first matching entry to Employee_Record.
    """
    # 1. Retrieve credentials
    try:
        resp = secrets_client.get_secret_value(SecretId=secret_name)
        creds = json.loads(resp["SecretString"])
    except Exception:
        logger.warning("Failed to retrieve directory credentials from Secrets Manager")
        return _error(
            500,
            "CREDENTIALS_UNAVAILABLE",
            "Unable to retrieve directory credentials.",
        )

    server_url = creds.get("server_url", "")
    port = int(creds.get("port", "389"))
    bind_dn = creds.get("bind_dn", "")
    bind_password = creds.get("bind_password", "")
    search_base_dn = creds.get("search_base_dn", "")
    search_filter_template = creds.get("search_filter_template", "")

    # 2. Validate filter template
    if "{query}" not in search_filter_template:
        return _error(
            500,
            "PROVIDER_NOT_CONFIGURED",
            "The LDAP search filter template is invalid — it must contain {query}.",
        )

    # 3. Substitute query into filter
    search_filter = search_filter_template.replace("{query}", query)

    # 4. Connect, bind, and search
    try:
        server = ldap3.Server(server_url, port=port, get_info=ldap3.NONE)
        conn = ldap3.Connection(
            server,
            user=bind_dn,
            password=bind_password,
            authentication=ldap3.SIMPLE,
            receive_timeout=REQUEST_TIMEOUT,
            auto_bind=True,
        )

        conn.search(
            search_base=search_base_dn,
            search_filter=search_filter,
            attributes=["uid", "cn", "mail", "title", "departmentNumber"],
        )

        entries = conn.entries
        conn.unbind()

        if not entries:
            return _error(
                404,
                "EMPLOYEE_NOT_FOUND",
                "No employee found matching the provided query.",
            )

        first = entries[0].entry_attributes_as_dict
        # ldap3 returns lists for attribute values; take the first element
        flat = {}
        for key, val in first.items():
            if isinstance(val, list):
                flat[key] = val[0] if val else ""
            else:
                flat[key] = val
        return _success(_normalize_ldap(flat))

    except LDAPBindError:
        return _error(
            502,
            "DIRECTORY_AUTH_ERROR",
            "LDAP bind credentials are invalid.",
        )
    except LDAPSocketOpenError:
        return _error(
            502,
            "DIRECTORY_UNAVAILABLE",
            "The LDAP server is unreachable.",
        )
    except LDAPSocketReceiveError:
        return _error(
            504,
            "DIRECTORY_TIMEOUT",
            "The directory provider did not respond within 10 seconds.",
        )


def lookup_employee(
    query: str,
    provider: str,
    secret_name: str,
    secrets_client: SecretsClient,
) -> dict:
    """Look up an employee from the configured directory provider.

    Returns:
        {"success": True, "status_code": 200, "data": Employee_Record}
        or {"success": False, "status_code": int, "error": {...}}
    """
    # Validate query
    if not query or not query.strip():
        return _error(
            400,
            "VALIDATION_ERROR",
            "The query parameter is required and must not be empty.",
        )

    # Validate provider
    if provider not in ("microsoft", "google", "ldap"):
        return _error(
            500,
            "PROVIDER_NOT_CONFIGURED",
            "The directory provider is not configured or unsupported.",
        )

    if provider == "microsoft":
        return _lookup_microsoft(query, secret_name, secrets_client)

    if provider == "ldap":
        return _lookup_ldap(query, secret_name, secrets_client)

    return _lookup_google(query, secret_name, secrets_client)

class ProviderNotConfiguredError(Exception):
    """Raised when no directory provider configuration is available."""

    def __init__(self) -> None:
        super().__init__("No directory provider configured")
        self.code = "PROVIDER_NOT_CONFIGURED"


def resolve_provider_config(
    dynamo_client: Any,
    table_name: str,
    env_provider: str,
    env_secret_name: str,
) -> tuple[str, str]:
    """Return (provider, secret_name) from DynamoDB or env var fallback.

    Resolution order:
    1. Read ``SETTINGS#directory`` item from DynamoDB.  If the record
       exists and contains both ``provider`` and ``secret_name``, use them.
    2. Otherwise fall back to the values supplied via environment variables.
    3. If neither source provides a usable provider, raise
       :class:`ProviderNotConfiguredError`.
    """
    try:
        resp = dynamo_client.get_item(
            TableName=table_name,
            Key={"employeeId": {"S": "SETTINGS#directory"}},
        )
        item = resp.get("Item")
        if item:
            db_provider = item.get("provider", {}).get("S", "")
            db_secret = item.get("secret_name", {}).get("S", "")
            if db_provider and db_secret:
                return db_provider, db_secret
    except Exception:
        logger.warning("Failed to read directory settings from DynamoDB, falling back to env vars")

    # Fallback to environment variables
    if env_provider and env_secret_name:
        return env_provider, env_secret_name

    raise ProviderNotConfiguredError()

