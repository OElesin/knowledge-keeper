"""Property test: credential validation rejects invalid payloads.

Feature: directory-provider-setup
Property 3: Credential validation rejects invalid payloads

For any provider type in {microsoft, google} and for any credential payload
where at least one required field is missing or empty, validate_credential_payload
SHALL return a non-empty list containing the missing field names.

Validates: Requirements 2.2, 2.3, 2.4, 3.5
"""
from __future__ import annotations

import json

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from lambdas.query.admin.logic import validate_credential_payload


MICROSOFT_REQUIRED = ("tenant_id", "client_id", "client_secret")
GOOGLE_REQUIRED = ("service_account_key",)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_empty_or_whitespace = st.sampled_from(["", "  ", "\t", "\n"])


def _microsoft_creds_with_at_least_one_missing():
    """Generate Microsoft credential dicts with at least one required field missing or empty."""
    return st.fixed_dictionaries(
        {
            "tenant_id": st.one_of(st.text(min_size=1), _empty_or_whitespace),
            "client_id": st.one_of(st.text(min_size=1), _empty_or_whitespace),
            "client_secret": st.one_of(st.text(min_size=1), _empty_or_whitespace),
        }
    ).filter(
        lambda d: any(not d.get(f, "").strip() for f in MICROSOFT_REQUIRED)
    )


def _google_creds_missing_key():
    """Generate Google credential dicts where service_account_key is missing, empty, or invalid JSON."""
    return st.one_of(
        # Missing key entirely
        st.just({}),
        # Empty / whitespace key
        st.builds(lambda v: {"service_account_key": v}, _empty_or_whitespace),
        # Non-JSON string
        st.builds(
            lambda v: {"service_account_key": v},
            st.text(min_size=1).filter(lambda s: _is_not_valid_json(s)),
        ),
    )


def _is_not_valid_json(s: str) -> bool:
    try:
        json.loads(s)
        return False
    except (ValueError, TypeError):
        return True


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestCredentialValidationRejectsInvalidPayloads:
    """Property 3: Credential validation rejects invalid payloads."""

    @settings(max_examples=100)
    @given(creds=_microsoft_creds_with_at_least_one_missing())
    def test_microsoft_missing_fields_detected(self, creds: dict):
        """For any Microsoft credential dict with at least one required field
        missing or empty, validate_credential_payload returns those fields."""
        result = validate_credential_payload("microsoft", creds)

        expected_missing = [
            f for f in MICROSOFT_REQUIRED if not creds.get(f, "").strip()
        ]

        assert len(result) > 0, "Should reject payload with missing fields"
        assert set(result) == set(expected_missing)

    @settings(max_examples=100)
    @given(creds=_google_creds_missing_key())
    def test_google_missing_or_invalid_key_detected(self, creds: dict):
        """For any Google credential dict where service_account_key is missing,
        empty, or not valid JSON, validate_credential_payload returns
        ['service_account_key']."""
        result = validate_credential_payload("google", creds)

        assert result == ["service_account_key"]

    @settings(max_examples=100)
    @given(
        provider=st.sampled_from(["microsoft", "google"]),
        extra_keys=st.dictionaries(
            keys=st.text(min_size=1, max_size=20).filter(
                lambda k: k not in (*MICROSOFT_REQUIRED, *GOOGLE_REQUIRED)
            ),
            values=st.text(),
            max_size=5,
        ),
    )
    def test_extra_fields_do_not_satisfy_requirements(self, provider: str, extra_keys: dict):
        """Credential dicts containing only unrecognised keys (no required
        fields) are always rejected."""
        # Ensure none of the required fields are present
        for f in (*MICROSOFT_REQUIRED, *GOOGLE_REQUIRED):
            extra_keys.pop(f, None)

        result = validate_credential_payload(provider, extra_keys)
        assert len(result) > 0, "Should reject payload missing all required fields"
