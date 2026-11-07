"""Tests for the per-product usage statistics."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from grocy_mcp.core.stock_usage import stock_usage_stats_data
from grocy_mcp.exceptions import GrocyValidationError

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _row(day, kind, amount, **extra):
    return {
        "transaction_type": kind,
        "amount": amount,
        "row_created_timestamp": f"{day} 09:00:00",
        "undone": 0,
        "spoiled": 0,
        "price": None,
        **extra,
    }


@pytest.fixture
def client():
    c = AsyncMock()
    c.get_stock_product.return_value = {"product": {"name": "Milk"}, "stock_amount": 3}
    c.get_objects.return_value = [
        _row("2026-08-01", "purchase", 6, price=10),  # outside the 90-day window
        _row("2026-09-20", "purchase", 4, price=12),
        _row("2026-10-20", "purchase", 6, price=14),
        _row("2026-09-25", "consume", -1),
        _row("2026-10-05", "consume", -2),
        _row("2026-10-09", "consume", -1),
        _row("2026-10-09", "consume", -1, spoiled=1),
        _row("2026-10-01", "product-opened", 1),
        _row("2026-10-11", "product-opened", 1),
        _row("2026-10-15", "consume", -1, undone=1),  # undone: ignored
        _row("2026-10-16", "consume", 4.4408920985006e-16),  # float noise: ignored
        _row("2026-11-07", "transfer_to", 1),
    ]
    return c


async def test_usage_stats_summarises_the_window(client):
    with patch("grocy_mcp.core.stock_usage.resolve_product", return_value=7):
        stats = await stock_usage_stats_data(client, "Milk", days=90, now=NOW)

    client.get_objects.assert_called_once_with("stock_log", "product_id=7")
    assert stats["product"] == "Milk" and stats["current_stock"] == 3
    assert stats["purchases"]["count"] == 2  # the August purchase is outside the window
    assert stats["purchases"]["total_amount"] == 10
    assert stats["purchases"]["dates"] == ["2026-09-20", "2026-10-20"]
    assert stats["purchases"]["total_spent"] == 4 * 12 + 6 * 14
    assert stats["purchases"]["average_unit_price"] == pytest.approx(
        (4 * 12 + 6 * 14) / 10, abs=1e-4
    )
    assert stats["purchases"]["median_gap_days"] == 30
    assert stats["consumes"]["count"] == 3 and stats["consumes"]["total_amount"] == 4
    assert stats["consumes"]["spoiled_count"] == 1 and stats["consumes"]["spoiled_amount"] == 1
    assert stats["consumes"]["last_gap_days"] == 4  # Oct 5 -> Oct 9
    assert stats["consumes"]["median_gap_days"] == 7.0  # gaps of 10 and 4 days
    assert stats["opens"]["count"] == 2 and stats["opens"]["last_gap_days"] == 10
    assert stats["average_daily_use"] == pytest.approx(4 / 90, abs=1e-6)
    assert stats["days_since_last_movement"] == 3  # the transfer on Nov 7
    assert stats["window_days"] == 90


async def test_usage_stats_window_narrows_the_counts(client):
    with patch("grocy_mcp.core.stock_usage.resolve_product", return_value=7):
        stats = await stock_usage_stats_data(client, "Milk", days=30, now=NOW)
    assert stats["purchases"]["count"] == 1
    assert stats["consumes"]["count"] == 0  # the window starts Oct 11; all consumes are earlier
    assert stats["opens"]["count"] == 0  # Oct 11 09:00 is before the window start at 12:00
    assert stats["purchases"]["median_gap_days"] is None  # one event has no gap


async def test_usage_stats_with_no_history(client):
    client.get_objects.return_value = []
    with patch("grocy_mcp.core.stock_usage.resolve_product", return_value=7):
        stats = await stock_usage_stats_data(client, "Milk", now=NOW)
    assert stats["purchases"]["count"] == 0 and stats["purchases"]["total_spent"] is None
    assert stats["average_daily_use"] == 0
    assert stats["days_since_last_movement"] is None and stats["last_movement"] is None


@pytest.mark.parametrize("days", [0, -5, 4000, 1.5, True, "90"])
async def test_usage_stats_rejects_bad_window_before_any_request(client, days):
    with pytest.raises(GrocyValidationError, match="days"):
        await stock_usage_stats_data(client, "Milk", days=days, now=NOW)
    client.get_objects.assert_not_called()


async def test_usage_stats_same_day_events_count_as_zero_day_gaps(client):
    client.get_objects.return_value = [
        _row("2026-10-01", "purchase", 1),
        {**_row("2026-10-11", "purchase", 1), "row_created_timestamp": "2026-10-11 09:00:00"},
        {**_row("2026-10-11", "purchase", 1), "row_created_timestamp": "2026-10-11 18:00:00"},
    ]
    with patch("grocy_mcp.core.stock_usage.resolve_product", return_value=7):
        stats = await stock_usage_stats_data(client, "Milk", days=90, now=NOW)
    assert stats["purchases"]["count"] == 3
    assert stats["purchases"]["median_gap_days"] == 5.0  # gaps of 10 and 0 days
    assert stats["purchases"]["last_gap_days"] == 0


async def test_usage_stats_booking_newer_than_now_is_today_not_minus_one(client):
    client.get_objects.return_value = [
        {**_row("2026-11-10", "purchase", 1), "row_created_timestamp": "2026-11-10 12:00:01"}
    ]
    with patch("grocy_mcp.core.stock_usage.resolve_product", return_value=7):
        stats = await stock_usage_stats_data(client, "Milk", days=90, now=NOW)
    assert stats["days_since_last_movement"] == 0
    assert stats["purchases"]["count"] == 1  # still counted: it is a real booking


async def test_usage_stats_keeps_recent_bookings_from_a_server_ahead_of_utc(client):
    # Grocy in UTC+1 writes local time: a booking 30 minutes ago looks like 30 minutes ahead
    client.get_objects.return_value = [
        {**_row("2026-11-10", "consume", -2), "row_created_timestamp": "2026-11-10 12:30:00"}
    ]
    with patch("grocy_mcp.core.stock_usage.resolve_product", return_value=7):
        stats = await stock_usage_stats_data(client, "Milk", days=7, now=NOW)
    assert stats["consumes"]["total_amount"] == 2
    assert stats["days_since_last_movement"] == 0


async def test_usage_stats_mixed_priced_and_unpriced_purchases_are_labelled(client):
    client.get_objects.return_value = [
        _row("2026-10-01", "purchase", 2, price=10),
        _row("2026-10-08", "purchase", 3),  # no price recorded
        _row("2026-10-15", "purchase", 1, price=20),
    ]
    with patch("grocy_mcp.core.stock_usage.resolve_product", return_value=7):
        stats = await stock_usage_stats_data(client, "Milk", days=90, now=NOW)
    purchases = stats["purchases"]
    assert purchases["count"] == 3 and purchases["total_amount"] == 6
    assert purchases["total_spent"] == 40  # 2 x 10 + 1 x 20: the priced purchases only
    assert purchases["average_unit_price"] == pytest.approx(40 / 3, abs=1e-4)
    assert purchases["unpriced_purchases"] == 1
    assert purchases["total_spent_is_complete"] is False


async def test_usage_stats_fully_priced_purchases_are_complete(client):
    client.get_objects.return_value = [_row("2026-10-01", "purchase", 2, price=10)]
    with patch("grocy_mcp.core.stock_usage.resolve_product", return_value=7):
        stats = await stock_usage_stats_data(client, "Milk", days=90, now=NOW)
    assert stats["purchases"]["unpriced_purchases"] == 0
    assert stats["purchases"]["total_spent_is_complete"] is True
