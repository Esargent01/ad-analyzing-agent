"""Unit tests for GAQL input validation in the Google Ads adapter.

Since GAQL doesn't support parameterized queries, we validate inputs
before string interpolation. These tests verify the validation catches
injection attempts.
"""

from __future__ import annotations

import pytest

from src.adapters.google_ads import _validate_date, _validate_resource_name
from src.exceptions import PlatformAPIError


class TestValidateResourceName:
    """Tests for _validate_resource_name."""

    def test_accepts_valid_resource_name(self) -> None:
        result = _validate_resource_name("customers/123/adGroupAds/456~789")
        assert result == "customers/123/adGroupAds/456~789"

    def test_accepts_long_ids(self) -> None:
        result = _validate_resource_name("customers/1234567890/adGroupAds/9876543210~1111111111")
        assert result == "customers/1234567890/adGroupAds/9876543210~1111111111"

    def test_rejects_sql_injection(self) -> None:
        with pytest.raises(PlatformAPIError, match="Invalid resource name"):
            _validate_resource_name("customers/123/adGroupAds/456~789' OR 1=1 --")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(PlatformAPIError, match="Invalid resource name"):
            _validate_resource_name("")

    def test_rejects_arbitrary_string(self) -> None:
        with pytest.raises(PlatformAPIError, match="Invalid resource name"):
            _validate_resource_name("not-a-resource-name")

    def test_rejects_missing_tilde(self) -> None:
        with pytest.raises(PlatformAPIError, match="Invalid resource name"):
            _validate_resource_name("customers/123/adGroupAds/456789")

    def test_rejects_letters_in_ids(self) -> None:
        with pytest.raises(PlatformAPIError, match="Invalid resource name"):
            _validate_resource_name("customers/abc/adGroupAds/456~789")


class TestValidateDate:
    """Tests for _validate_date."""

    def test_accepts_valid_date(self) -> None:
        assert _validate_date("2026-04-12") == "2026-04-12"

    def test_accepts_boundary_date(self) -> None:
        assert _validate_date("2000-01-01") == "2000-01-01"

    def test_rejects_sql_injection(self) -> None:
        with pytest.raises(PlatformAPIError, match="Invalid date"):
            _validate_date("2026-04-12' OR TRUE --")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(PlatformAPIError, match="Invalid date"):
            _validate_date("")

    def test_rejects_wrong_format(self) -> None:
        with pytest.raises(PlatformAPIError, match="Invalid date"):
            _validate_date("04/12/2026")

    def test_rejects_partial_date(self) -> None:
        with pytest.raises(PlatformAPIError, match="Invalid date"):
            _validate_date("2026-04")
