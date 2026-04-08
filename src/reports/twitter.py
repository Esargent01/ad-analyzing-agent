"""Post ad performance snapshots to Twitter / X."""

from __future__ import annotations

import logging
from pathlib import Path

import tweepy

logger = logging.getLogger(__name__)


def post_snapshot(
    image_path: Path,
    caption: str,
    *,
    api_key: str,
    api_secret: str,
    access_token: str,
    access_token_secret: str,
) -> str | None:
    """Upload an image and post a tweet with the given caption.

    Returns the tweet URL on success, or None on failure.
    """
    try:
        # V1.1 auth for media upload (v2 doesn't support media upload directly)
        auth = tweepy.OAuth1UserHandler(
            api_key, api_secret, access_token, access_token_secret,
        )
        api_v1 = tweepy.API(auth)

        # Upload media via v1.1
        media = api_v1.media_upload(filename=str(image_path))
        logger.info("Media uploaded: media_id=%s", media.media_id)

        # Post tweet via v1.1 (avoids v2 Project requirement)
        status = api_v1.update_status(status=caption, media_ids=[media.media_id])

        tweet_url = f"https://x.com/i/status/{status.id}"
        logger.info("Tweet posted: %s", tweet_url)
        return tweet_url

    except tweepy.TweepyException:
        logger.exception("Failed to post tweet")
        return None


def build_daily_caption(
    campaign_name: str,
    report_date: str,
    spend: str,
    hook_rate: str,
    ctr: str,
    report_url: str,
) -> str:
    """Build a tweet caption for a daily report snapshot."""
    return (
        f"{campaign_name} — {report_date}\n"
        f"\n"
        f"Spend: {spend}\n"
        f"Hook Rate: {hook_rate}\n"
        f"CTR: {ctr}\n"
        f"\n"
        f"Full report: {report_url}"
    )


def build_weekly_caption(
    campaign_name: str,
    week_label: str,
    spend: str,
    purchases: int,
    roas: str,
    report_url: str,
) -> str:
    """Build a tweet caption for a weekly report snapshot."""
    return (
        f"{campaign_name} — Week {week_label}\n"
        f"\n"
        f"Spend: {spend}\n"
        f"Purchases: {purchases}\n"
        f"ROAS: {roas}\n"
        f"\n"
        f"Full report: {report_url}"
    )
