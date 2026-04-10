"""Unit tests for the Phase G asset-enumeration helpers.

``fetch_meta_ad_accounts`` and ``fetch_meta_pages`` call the Graph
API via ``httpx`` and coerce the response into Pydantic models. We
stub ``httpx.AsyncClient`` at the module boundary rather than
monkey-patching ``fetch_meta_user_id`` so the happy/sad paths of the
actual fetchers are exercised — parsing, truncation, and error
handling.

No real network, no Graph API creds required. The test suite stays
green without Meta app access.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from src.dashboard.meta_oauth import (
    MetaOAuthError,
    fetch_meta_ad_accounts,
    fetch_meta_pages,
)

# ---------------------------------------------------------------------------
# httpx stubs
# ---------------------------------------------------------------------------
#
# ``httpx.AsyncClient`` is used as ``async with httpx.AsyncClient(...) as
# client`` in production. We replace the class with a factory that
# returns an async-context-manager wrapping a fake client object whose
# ``get`` method returns a predetermined ``httpx.Response``.


def _fake_response(status_code: int, json_body: object | None = None) -> httpx.Response:
    """Build a real ``httpx.Response`` without touching the network."""
    request = httpx.Request("GET", "https://graph.facebook.com/test")
    if json_body is None:
        content = b""
    else:
        import json as _json

        content = _json.dumps(json_body).encode("utf-8")
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": "application/json"},
        request=request,
    )


def _client_factory(response: httpx.Response | Exception):
    """Return a fake ``httpx.AsyncClient`` class.

    The fake's ``.get()`` coroutine returns ``response``, or raises if
    ``response`` is an ``Exception`` instance (used to exercise the
    ``httpx.RequestError`` path).
    """

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, *args: object, **kwargs: object) -> httpx.Response:
            if isinstance(response, Exception):
                raise response
            return response

    return _FakeClient


# ---------------------------------------------------------------------------
# fetch_meta_ad_accounts
# ---------------------------------------------------------------------------


class TestFetchMetaAdAccounts:
    @pytest.mark.asyncio
    async def test_zero_accounts_is_valid(self) -> None:
        response = _fake_response(200, {"data": []})
        with patch(
            "src.dashboard.meta_oauth.httpx.AsyncClient",
            _client_factory(response),
        ):
            result = await fetch_meta_ad_accounts("token-xyz")
        assert result == []

    @pytest.mark.asyncio
    async def test_single_account_parses(self) -> None:
        response = _fake_response(
            200,
            {
                "data": [
                    {
                        "id": "act_1111",
                        "name": "Operator Main",
                        "account_status": 1,
                        "currency": "USD",
                    }
                ]
            },
        )
        with patch(
            "src.dashboard.meta_oauth.httpx.AsyncClient",
            _client_factory(response),
        ):
            result = await fetch_meta_ad_accounts("token-xyz")
        assert len(result) == 1
        assert result[0].id == "act_1111"
        assert result[0].name == "Operator Main"
        assert result[0].account_status == 1
        assert result[0].currency == "USD"

    @pytest.mark.asyncio
    async def test_many_accounts_are_all_returned(self) -> None:
        response = _fake_response(
            200,
            {
                "data": [
                    {
                        "id": f"act_{i}",
                        "name": f"Account {i}",
                        "account_status": 1,
                        "currency": "USD",
                    }
                    for i in range(5)
                ]
            },
        )
        with patch(
            "src.dashboard.meta_oauth.httpx.AsyncClient",
            _client_factory(response),
        ):
            result = await fetch_meta_ad_accounts("token-xyz")
        assert len(result) == 5
        assert {a.id for a in result} == {f"act_{i}" for i in range(5)}

    @pytest.mark.asyncio
    async def test_truncates_at_100_items(self) -> None:
        response = _fake_response(
            200,
            {
                "data": [
                    {
                        "id": f"act_{i}",
                        "name": f"Agency Account {i}",
                        "account_status": 1,
                        "currency": "USD",
                    }
                    for i in range(250)
                ]
            },
        )
        with patch(
            "src.dashboard.meta_oauth.httpx.AsyncClient",
            _client_factory(response),
        ):
            result = await fetch_meta_ad_accounts("token-xyz")
        assert len(result) == 100

    @pytest.mark.asyncio
    async def test_400_response_raises(self) -> None:
        response = _fake_response(400, {"error": {"message": "bad token"}})
        with (
            patch(
                "src.dashboard.meta_oauth.httpx.AsyncClient",
                _client_factory(response),
            ),
            pytest.raises(MetaOAuthError, match="HTTP 400"),
        ):
            await fetch_meta_ad_accounts("bad-token")

    @pytest.mark.asyncio
    async def test_malformed_payload_raises(self) -> None:
        response = _fake_response(200, {"something": "else"})
        with (
            patch(
                "src.dashboard.meta_oauth.httpx.AsyncClient",
                _client_factory(response),
            ),
            pytest.raises(MetaOAuthError, match="missing data array"),
        ):
            await fetch_meta_ad_accounts("token-xyz")

    @pytest.mark.asyncio
    async def test_missing_required_field_raises(self) -> None:
        response = _fake_response(
            200,
            {"data": [{"name": "Orphan", "account_status": 1, "currency": "USD"}]},
        )
        with (
            patch(
                "src.dashboard.meta_oauth.httpx.AsyncClient",
                _client_factory(response),
            ),
            pytest.raises(MetaOAuthError, match="malformed entry"),
        ):
            await fetch_meta_ad_accounts("token-xyz")

    @pytest.mark.asyncio
    async def test_network_error_raises(self) -> None:
        err = httpx.ConnectError("dns failure")
        with (
            patch(
                "src.dashboard.meta_oauth.httpx.AsyncClient",
                _client_factory(err),
            ),
            pytest.raises(MetaOAuthError, match="request failed"),
        ):
            await fetch_meta_ad_accounts("token-xyz")


# ---------------------------------------------------------------------------
# fetch_meta_pages
# ---------------------------------------------------------------------------


class TestFetchMetaPages:
    @pytest.mark.asyncio
    async def test_zero_pages_is_valid(self) -> None:
        response = _fake_response(200, {"data": []})
        with patch(
            "src.dashboard.meta_oauth.httpx.AsyncClient",
            _client_factory(response),
        ):
            result = await fetch_meta_pages("token-xyz")
        assert result == []

    @pytest.mark.asyncio
    async def test_single_page_parses(self) -> None:
        response = _fake_response(
            200,
            {
                "data": [
                    {
                        "id": "2222",
                        "name": "Slice Society",
                        "category": "Restaurant",
                    }
                ]
            },
        )
        with patch(
            "src.dashboard.meta_oauth.httpx.AsyncClient",
            _client_factory(response),
        ):
            result = await fetch_meta_pages("token-xyz")
        assert len(result) == 1
        assert result[0].id == "2222"
        assert result[0].name == "Slice Society"
        assert result[0].category == "Restaurant"

    @pytest.mark.asyncio
    async def test_400_response_raises(self) -> None:
        response = _fake_response(403, {"error": {"message": "no permission"}})
        with (
            patch(
                "src.dashboard.meta_oauth.httpx.AsyncClient",
                _client_factory(response),
            ),
            pytest.raises(MetaOAuthError, match="HTTP 403"),
        ):
            await fetch_meta_pages("bad-token")

    @pytest.mark.asyncio
    async def test_missing_data_array_raises(self) -> None:
        response = _fake_response(200, {"paging": {}})
        with (
            patch(
                "src.dashboard.meta_oauth.httpx.AsyncClient",
                _client_factory(response),
            ),
            pytest.raises(MetaOAuthError, match="missing data array"),
        ):
            await fetch_meta_pages("token-xyz")

    @pytest.mark.asyncio
    async def test_page_access_token_never_leaks_into_model(self) -> None:
        """The per-Page access_token field is deliberately dropped."""
        response = _fake_response(
            200,
            {
                "data": [
                    {
                        "id": "3333",
                        "name": "Test Page",
                        "category": "Local Business",
                        "access_token": "PAGE_TOKEN_SECRET",
                    }
                ]
            },
        )
        with patch(
            "src.dashboard.meta_oauth.httpx.AsyncClient",
            _client_factory(response),
        ):
            result = await fetch_meta_pages("token-xyz")
        assert len(result) == 1
        # The model doesn't even define an access_token field.
        assert not hasattr(result[0], "access_token")
        # Belt-and-braces: make sure the secret didn't sneak into the dict.
        dumped = result[0].model_dump()
        assert "access_token" not in dumped
        assert "PAGE_TOKEN_SECRET" not in str(dumped)
