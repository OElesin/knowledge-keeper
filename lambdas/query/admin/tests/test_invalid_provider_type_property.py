"""Property test: invalid provider type rejected.

Feature: directory-provider-setup
Property 4: Invalid provider type rejected

For any string that is not "microsoft" or "google", calling
validate_credential_payload SHALL return ["VALIDATION_ERROR"].

Validates: Requirements 2.5
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from lambdas.query.admin.logic import validate_credential_payload

VALID_PROVIDERS = {"microsoft", "google"}


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_invalid_provider = st.text(min_size=0).filter(lambda s: s not in VALID_PROVIDERS)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestInvalidProviderTypeRejected:
    """Property 4: Invalid provider type rejected."""

    @settings(max_examples=100)
    @given(provider=_invalid_provider, creds=st.dictionaries(keys=st.text(), values=st.text(), max_size=5))
    def test_unknown_provider_returns_validation_error(self, provider: str, creds: dict):
        """For any provider string not in {microsoft, google},
        validate_credential_payload returns ["VALIDATION_ERROR"]."""
        result = validate_credential_payload(provider, creds)

        assert result == ["VALIDATION_ERROR"], (
            f"Expected ['VALIDATION_ERROR'] for provider={provider!r}, got {result}"
        )
