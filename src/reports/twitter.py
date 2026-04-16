"""Post tweets to the Kleiber X (Twitter) account.

Single responsibility: take a 20–280 char text body and POST it to
``https://api.x.com/2/tweets`` using OAuth 1.0a User Context. Mirrors
the pattern in ``src/reports/auth_email.py`` — no shared base class,
direct async HTTP call, dev-mode fallback when credentials are
placeholders so local development doesn't need a real X app.

OAuth 1.0a was chosen over OAuth 2.0 PKCE because the four tokens
(consumer key/secret + access token/secret) never expire — no refresh
dance needed for a server-to-server cron job. ``authlib`` handles the
signature; we just wrap its httpx client and POST JSON.
"""

from __future__ import annotations

import logging

from authlib.integrations.httpx_client import AsyncOAuth1Client

from src.config import get_settings

logger = logging.getLogger(__name__)

_TWEETS_ENDPOINT = "https://api.x.com/2/tweets"
_DEV_PLACEHOLDER_KEYS = {"", "placeholder", "dev-placeholder"}


def _credentials_are_placeholder() -> bool:
    """Return True if any of the four OAuth values is empty/placeholder.

    Any one missing puts the whole client into dev-mode — partial
    credentials can't sign a real request and we'd rather fail loudly
    during setup than half-send.
    """
    settings = get_settings()
    return any(
        v in _DEV_PLACEHOLDER_KEYS
        for v in (
            settings.twitter_consumer_key,
            settings.twitter_consumer_secret,
            settings.twitter_access_token,
            settings.twitter_access_token_secret,
        )
    )


async def post_tweet(text: str) -> str | None:
    """POST ``text`` as a new tweet on the configured X account.

    Args:
        text: The tweet body. Caller is responsible for keeping this
            within X's 280-char limit — ``src.agents.tweet_writer``
            enforces this via Pydantic before calling.

    Returns:
        The X tweet ID on success, ``None`` on HTTP failure. In
        dev-mode (placeholder credentials) the draft is logged and
        the sentinel string ``"dev-mode"`` is returned so callers
        can treat dev-mode as a non-null success.
    """
    if _credentials_are_placeholder():
        logger.info("=" * 72)
        logger.info("DEV MODE: tweet would be posted")
        logger.info("Body: %s", text)
        logger.info("=" * 72)
        return "dev-mode"

    settings = get_settings()
    client = AsyncOAuth1Client(
        client_id=settings.twitter_consumer_key,
        client_secret=settings.twitter_consumer_secret,
        token=settings.twitter_access_token,
        token_secret=settings.twitter_access_token_secret,
        timeout=30.0,
    )

    try:
        response = await client.post(
            _TWEETS_ENDPOINT,
            json={"text": text},
        )
        if response.status_code == 201:
            data = response.json().get("data", {})
            tweet_id = data.get("id")
            if tweet_id:
                logger.info("Posted tweet %s", tweet_id)
                return str(tweet_id)
            logger.error(
                "X accepted the tweet but returned no id: %s",
                response.text[:500],
            )
            return None

        logger.error(
            "X API returned HTTP %d: %s",
            response.status_code,
            response.text[:500],
        )
        return None
    except Exception as exc:  # noqa: BLE001 — caller cannot fail the cron
        logger.error("X request failed: %s", exc)
        return None
    finally:
        await client.aclose()
