"""Property test: config resolution — DynamoDB overrides env vars.

Feature: directory-provider-setup
Property 9: Config resolution — DynamoDB overrides env vars

For any DynamoDB settings record with provider P_db and secret name S_db,
and for any environment variable values P_env and S_env, calling
resolve_provider_config SHALL return (P_db, S_db).  When no DynamoDB record
exists, it SHALL return (P_env, S_env).

Validates: Requirements 4.1, 4.2, 4.3
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from lambdas.query.directory_lookup.logic import (
    ProviderNotConfiguredError,
    resolve_provider_config,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_non_empty_text = st.text(min_size=1).filter(lambda s: s.strip() != "")
_table_name = st.text(min_size=1, max_size=50)


def _dynamo_client_with_record(provider: str, secret_name: str) -> MagicMock:
    """Return a mock DynamoDB client that returns a SETTINGS#directory item."""
    client = MagicMock()
    client.get_item.return_value = {
        "Item": {
            "employeeId": {"S": "SETTINGS#directory"},
            "provider": {"S": provider},
            "secret_name": {"S": secret_name},
        }
    }
    return client


def _dynamo_client_no_record() -> MagicMock:
    """Return a mock DynamoDB client that returns no item."""
    client = MagicMock()
    client.get_item.return_value = {}
    return client


def _dynamo_client_error() -> MagicMock:
    """Return a mock DynamoDB client that raises on get_item."""
    client = MagicMock()
    client.get_item.side_effect = Exception("DynamoDB unavailable")
    return client


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestConfigResolutionDynamoDBOverridesEnvVars:
    """Property 9: Config resolution — DynamoDB overrides env vars."""

    @settings(max_examples=100)
    @given(
        db_provider=_non_empty_text,
        db_secret=_non_empty_text,
        env_provider=_non_empty_text,
        env_secret=_non_empty_text,
        table=_table_name,
    )
    def test_dynamodb_record_overrides_env_vars(
        self,
        db_provider: str,
        db_secret: str,
        env_provider: str,
        env_secret: str,
        table: str,
    ):
        """When a DynamoDB record exists with both provider and secret_name,
        resolve_provider_config returns the DynamoDB values regardless of
        what the env vars contain."""
        client = _dynamo_client_with_record(db_provider, db_secret)

        result = resolve_provider_config(client, table, env_provider, env_secret)

        assert result == (db_provider, db_secret), (
            f"Expected DDB values ({db_provider!r}, {db_secret!r}), got {result}"
        )

    @settings(max_examples=100)
    @given(
        env_provider=_non_empty_text,
        env_secret=_non_empty_text,
        table=_table_name,
    )
    def test_no_record_falls_back_to_env_vars(
        self,
        env_provider: str,
        env_secret: str,
        table: str,
    ):
        """When no DynamoDB record exists, resolve_provider_config returns
        the environment variable values."""
        client = _dynamo_client_no_record()

        result = resolve_provider_config(client, table, env_provider, env_secret)

        assert result == (env_provider, env_secret), (
            f"Expected env values ({env_provider!r}, {env_secret!r}), got {result}"
        )

    @settings(max_examples=100)
    @given(
        env_provider=_non_empty_text,
        env_secret=_non_empty_text,
        table=_table_name,
    )
    def test_dynamodb_error_falls_back_to_env_vars(
        self,
        env_provider: str,
        env_secret: str,
        table: str,
    ):
        """When DynamoDB raises an exception, resolve_provider_config
        gracefully falls back to env vars."""
        client = _dynamo_client_error()

        result = resolve_provider_config(client, table, env_provider, env_secret)

        assert result == (env_provider, env_secret), (
            f"Expected env fallback ({env_provider!r}, {env_secret!r}), got {result}"
        )

    @settings(max_examples=100)
    @given(table=_table_name)
    def test_no_record_and_no_env_vars_raises(self, table: str):
        """When neither DynamoDB record nor env vars are available,
        resolve_provider_config raises ProviderNotConfiguredError."""
        client = _dynamo_client_no_record()

        with pytest.raises(ProviderNotConfiguredError):
            resolve_provider_config(client, table, "", "")
