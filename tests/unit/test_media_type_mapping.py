"""Regression guard for the Meta object_type → media_type mapping.

Meta reports creative format via ``AdCreative.object_type`` (an enum:
``PHOTO``, ``VIDEO``, ``SHARE``, ``MULTI_SHARE``, plus less-common
values like ``STATUS`` / ``OFFER`` / ``INVALID``). We translate that
into a small internal taxonomy (``"video"`` / ``"image"`` / ``"mixed"``
/ ``"unknown"``) via :func:`src.adapters.meta._map_media_type`, and
the entire reporting layer keys off those four strings to decide
whether to render video-only metrics.

If Meta ever adds new object_type values, or if we accidentally reshape
the mapping, every image ad in the system could start showing hook /
hold rate rows again — this test pins the contract.
"""

from __future__ import annotations

import pytest

from src.adapters.meta import _map_media_type


class TestMapMediaType:
    @pytest.mark.parametrize(
        ("object_type", "expected"),
        [
            ("VIDEO", "video"),
            ("PHOTO", "image"),
            ("SHARE", "image"),          # link-share creatives are image ads
            ("MULTI_SHARE", "mixed"),    # carousels can mix image + video cards
        ],
    )
    def test_known_values_map_to_taxonomy(
        self, object_type: str, expected: str
    ) -> None:
        assert _map_media_type(object_type) == expected

    @pytest.mark.parametrize(
        "object_type",
        ["STATUS", "OFFER", "APPLICATION", "INVALID", "SOMETHING_NEW", ""],
    )
    def test_unmapped_values_fall_through_to_unknown(
        self, object_type: str
    ) -> None:
        # Unknown is the "render the full funnel" fallback — safer than
        # guessing wrong. Anything Meta adds in the future that we
        # haven't mapped explicitly should land here.
        assert _map_media_type(object_type) == "unknown"

    def test_none_returns_unknown(self) -> None:
        # Meta omits object_type in some edge cases (e.g. very old
        # creatives). ``None`` must round-trip to "unknown", never
        # raise or return an unexpected falsy value.
        assert _map_media_type(None) == "unknown"
