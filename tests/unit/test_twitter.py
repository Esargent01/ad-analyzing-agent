"""Tests for src.reports.twitter — the X API client + dev-mode fallback."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.reports import twitter


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    """Isolate these tests from the process-level settings cache.

    Every test overrides ``get_settings`` via mock.patch, so there's
    nothing to actively reset — but declaring this as a fixture makes
    the intent explicit and keeps ordering guarantees if a future
    test mutates the real Settings.
    """
    yield


def _fake_settings(**overrides) -> SimpleNamespace:
    base = {
        "twitter_api_key": "ck-real",
        "twitter_api_secret": "cs-real",
        "twitter_access_token": "at-real",
        "twitter_access_token_secret": "ats-real",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestCredentialsArePlaceholder:
    def test_all_real_returns_false(self) -> None:
        with patch.object(twitter, "get_settings", return_value=_fake_settings()):
            assert twitter._credentials_are_placeholder() is False

    @pytest.mark.parametrize(
        "missing",
        [
            "twitter_api_key",
            "twitter_api_secret",
            "twitter_access_token",
            "twitter_access_token_secret",
        ],
    )
    def test_any_empty_returns_true(self, missing: str) -> None:
        with patch.object(
            twitter, "get_settings", return_value=_fake_settings(**{missing: ""})
        ):
            assert twitter._credentials_are_placeholder() is True

    def test_placeholder_string_returns_true(self) -> None:
        with patch.object(
            twitter,
            "get_settings",
            return_value=_fake_settings(twitter_api_key="placeholder"),
        ):
            assert twitter._credentials_are_placeholder() is True


class TestPostTweet:
    async def test_dev_mode_returns_sentinel_without_hitting_api(self) -> None:
        """Placeholder credentials must short-circuit — no network call."""
        with patch.object(
            twitter, "get_settings", return_value=_fake_settings(twitter_api_key="")
        ), patch.object(twitter, "AsyncOAuth1Client") as mock_client_cls:
            result = await twitter.post_tweet("hello world")

        assert result == "dev-mode"
        mock_client_cls.assert_not_called()

    async def test_success_returns_tweet_id_and_closes_client(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value=SimpleNamespace(
                status_code=201,
                json=lambda: {"data": {"id": "1789123", "text": "hi"}},
                text="",
            )
        )
        mock_client.aclose = AsyncMock()

        with patch.object(
            twitter, "get_settings", return_value=_fake_settings()
        ), patch.object(twitter, "AsyncOAuth1Client", return_value=mock_client):
            result = await twitter.post_tweet("a real tweet body")

        assert result == "1789123"
        mock_client.post.assert_awaited_once()
        mock_client.aclose.assert_awaited_once()

    async def test_non_201_response_returns_none(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value=SimpleNamespace(
                status_code=403,
                json=lambda: {"detail": "Forbidden"},
                text='{"detail":"Forbidden"}',
            )
        )
        mock_client.aclose = AsyncMock()

        with patch.object(
            twitter, "get_settings", return_value=_fake_settings()
        ), patch.object(twitter, "AsyncOAuth1Client", return_value=mock_client):
            result = await twitter.post_tweet("a real tweet body")

        assert result is None
        mock_client.aclose.assert_awaited_once()

    async def test_exception_returns_none_and_still_closes(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("socket kaboom"))
        mock_client.aclose = AsyncMock()

        with patch.object(
            twitter, "get_settings", return_value=_fake_settings()
        ), patch.object(twitter, "AsyncOAuth1Client", return_value=mock_client):
            result = await twitter.post_tweet("a real tweet body")

        assert result is None
        mock_client.aclose.assert_awaited_once()
