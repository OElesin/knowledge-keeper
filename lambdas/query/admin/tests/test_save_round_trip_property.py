"""Property test: save round-trip.

Feature: directory-provider-setup
Property 5: Save round-trip

For any valid provider type and valid credential payload, after calling
save_directory_config, calling get_directory_config SHALL return the saved
provider type and credentials_configured set to true.

Validates: Requirements 2.1, 2.6
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from lambdas.query.admin.logic import (
    get_directory_config,
    save_directory_config,
    SETTINGS_KEY,
)


# ---------------------------------------------------------------------------
# Strategies — generate valid provider + credential combos
# ---------------------------------------------------------------------------

_non_empty_stripped = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())

_valid_microsoft_creds = st.fixed_dictionaries({
    "tenant_id": _non_empty_stripped,
    "client_id": _non_empty_stripped,
    "client_secret": _non_empty_stripped,
})

_valid_google_service_account = st.fixed_dictionaries({
    "type": st.just("service_account"),
    "project_id": _non_empty_stripped,
    "private_key": _non_empty_stripped,
}).map(lambda d: json.dumps(d))

_valid_google_creds = _valid_google_service_account.flatmap(
    lambda key_json: st.fixed_dictionaries({
        "service_account_key": st.just(key_json),
    })
)

_valid_provider_and_creds = st.one_of(
    st.tuples(st.just("microsoft"), _valid_microsoft_creds),
    st.tuples(st.just("google"), _valid_google_creds),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stateful_mocks():
    """Build dynamo and secrets mocks that share state so save → get works."""
    store = {}  # simulates DynamoDB settings record
    secret_exists = {"value": False}  # tracks whether secret has been written

    dynamo = MagicMock()

    def fake_get_twin(key):
        return store.get(key)

    def fake_update_twin(key, attrs):
        if key not in store:
            store[key] = {}
        store[key].update(attrs)

    dynamo.get_twin.side_effect = fake_get_twin
    dynamo.update_twin.side_effect = fake_update_twin
    dynamo.write_audit_log.return_value = {}

    secrets = MagicMock()

    def fake_put_secret(secret_id, secret_string):
        secret_exists["value"] = True
        return {}

    def fake_describe_secret(secret_id):
        if not secret_exists["value"]:
            raise Exception("Secret not found")
        return {"Name": secret_id}

    secrets.put_secret_value.side_effect = fake_put_secret
    secrets.describe_secret.side_effect = fake_describe_secret

    return dynamo, secrets


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


class TestSaveRoundTrip:
    """Property 5: Save round-trip."""

    @settings(max_examples=100)
    @given(provider_and_creds=_valid_provider_and_creds)
    def test_get_after_save_returns_provider_and_configured(
        self, provider_and_creds: tuple[str, dict]
    ):
        """For any valid provider + credentials, saving then reading back
        returns the same provider with credentials_configured=True."""
        provider, creds = provider_and_creds
        dynamo, secrets = _make_stateful_mocks()

        body = {"provider": provider, "credentials": creds}

        with patch.dict(os.environ, {"ENVIRONMENT": "test"}):
            save_result = save_directory_config(
                body, "req_roundtrip",
                dynamo_module=dynamo,
                secrets_module=secrets,
            )

        assert save_result["success"] is True, (
            f"save_directory_config failed: {save_result}"
        )

        get_result = get_directory_config(
            dynamo_module=dynamo,
            secrets_module=secrets,
        )

        assert get_result["success"] is True
        assert get_result["data"]["provider"] == provider
        assert get_result["data"]["credentials_configured"] is True
