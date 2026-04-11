"""
Channel-coverage guardrail for the sales_velocity aggregator.

Asserts that every value in `products.SKU.channel` that exists on the
live DB is explicitly classified into one of three buckets:

  1. `SKU_CHANNEL_MAP`     — mapped to a sales_velocity channel code
  2. `CHANNELS_OUT_OF_SCOPE` — intentionally ignored (SHOPIFY, STOCK)
  3. `CHANNELS_DATA_CLEANUP` — known garbage, cleanup pending

A new `SKU.channel` value that isn't in any of the three buckets will
fail this test, forcing a conscious decision before the aggregator
silently drops rows for it. This replaces the `SKU_CHANNEL_MAP`
coverage test originally specified in review correction #12 — the
2026-04-11 planning session re-specified it as a duplicate-detection
safety check rather than a one-way coverage assertion, but the
guardrail here is still the first line of defence against silent
drops when new channel values appear in SKU data.
"""
from __future__ import annotations

import pytest
from django.db import connection

from sales_velocity.models import (
    SKU_CHANNEL_MAP,
    CHANNELS_OUT_OF_SCOPE,
    CHANNELS_DATA_CLEANUP,
)


def _all_mapped_values() -> set[str]:
    """Flatten SKU_CHANNEL_MAP value sets into one set."""
    mapped: set[str] = set()
    for values in SKU_CHANNEL_MAP.values():
        mapped |= values
    return mapped


@pytest.mark.django_db
class TestChannelCoverage:
    def test_no_overlap_between_buckets(self):
        """Buckets must be disjoint so a channel's treatment is unambiguous."""
        mapped = _all_mapped_values()
        assert mapped.isdisjoint(CHANNELS_OUT_OF_SCOPE), (
            f'SKU_CHANNEL_MAP and CHANNELS_OUT_OF_SCOPE overlap: '
            f'{mapped & CHANNELS_OUT_OF_SCOPE}'
        )
        assert mapped.isdisjoint(CHANNELS_DATA_CLEANUP), (
            f'SKU_CHANNEL_MAP and CHANNELS_DATA_CLEANUP overlap: '
            f'{mapped & CHANNELS_DATA_CLEANUP}'
        )
        assert CHANNELS_OUT_OF_SCOPE.isdisjoint(CHANNELS_DATA_CLEANUP), (
            f'CHANNELS_OUT_OF_SCOPE and CHANNELS_DATA_CLEANUP overlap: '
            f'{CHANNELS_OUT_OF_SCOPE & CHANNELS_DATA_CLEANUP}'
        )

    def test_every_live_channel_value_is_classified(self):
        """
        Hits the actual DB — every DISTINCT SKU.channel on prod must be
        covered by one of the three buckets. A new channel value that
        isn't in any bucket fails this test with the unknown value(s)
        listed explicitly so the next engineer knows what to add.
        """
        with connection.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT channel FROM products_sku "
                "WHERE channel IS NOT NULL "
                "ORDER BY channel"
            )
            live_channels = {row[0] for row in cur.fetchall()}

        classified = (
            _all_mapped_values()
            | CHANNELS_OUT_OF_SCOPE
            | CHANNELS_DATA_CLEANUP
        )

        unknown = live_channels - classified
        assert not unknown, (
            f'Unexpected SKU.channel values on live DB: {sorted(unknown)}. '
            f'Classify each one in sales_velocity.models by adding it to '
            f'SKU_CHANNEL_MAP (if it should flow into velocity), '
            f'CHANNELS_OUT_OF_SCOPE (if it should be ignored), or '
            f'CHANNELS_DATA_CLEANUP (if it is garbage pending cleanup).'
        )

    def test_no_channel_code_collision(self):
        """
        Each sales_velocity channel code must appear exactly once in
        CHANNEL_CHOICES. A duplicate would silently override the label
        or choice for the later entry.
        """
        from sales_velocity.models import CHANNEL_CHOICES
        codes = [code for code, _label in CHANNEL_CHOICES]
        assert len(codes) == len(set(codes)), (
            f'Duplicate channel codes in CHANNEL_CHOICES: '
            f'{[c for c in codes if codes.count(c) > 1]}'
        )

    def test_map_keys_match_channel_choices(self):
        """
        SKU_CHANNEL_MAP keys must be a subset of CHANNEL_CHOICES codes.
        A key that isn't in CHANNEL_CHOICES would never match any
        velocity row (the aggregator uses CHANNEL_CHOICES codes as its
        authoritative namespace).
        """
        from sales_velocity.models import CHANNEL_CHOICES
        valid_codes = {code for code, _label in CHANNEL_CHOICES}
        extra = set(SKU_CHANNEL_MAP.keys()) - valid_codes
        assert not extra, (
            f'SKU_CHANNEL_MAP keys not in CHANNEL_CHOICES: {sorted(extra)}'
        )
