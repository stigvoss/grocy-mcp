"""Tests for the stock journal core module."""

from unittest.mock import AsyncMock, patch

from grocy_mcp.core.stock_journal import stock_journal


async def test_stock_journal():
    client = AsyncMock()
    client.get_objects.side_effect = [
        # stock_log
        [
            {
                "id": 1,
                "product_id": 1,
                "amount": 2,
                "transaction_type": "purchase",
                "row_created_timestamp": "2026-03-30 10:00:00",
            },
            {
                "id": 2,
                "product_id": 2,
                "amount": 1,
                "transaction_type": "consume",
                "row_created_timestamp": "2026-03-31 12:00:00",
            },
        ],
        # products
        [{"id": 1, "name": "Milk"}, {"id": 2, "name": "Bread"}],
    ]
    result = await stock_journal(client)
    assert "Milk" in result
    assert "Bread" in result
    assert "purchase" in result
    assert "consume" in result


async def test_stock_journal_empty():
    client = AsyncMock()
    client.get_objects.side_effect = [[], []]
    result = await stock_journal(client)
    assert result == "No stock journal entries found."


async def test_stock_journal_filtered_by_product():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [
            {
                "id": 1,
                "product_id": 1,
                "amount": 2,
                "transaction_type": "purchase",
                "row_created_timestamp": "2026-03-30 10:00:00",
            },
            {
                "id": 2,
                "product_id": 2,
                "amount": 1,
                "transaction_type": "consume",
                "row_created_timestamp": "2026-03-31 12:00:00",
            },
        ],
        [{"id": 1, "name": "Milk"}, {"id": 2, "name": "Bread"}],
    ]
    with patch("grocy_mcp.core.stock_journal.resolve_product", return_value=1):
        result = await stock_journal(client, product="Milk")
    assert "Milk" in result
    assert "Bread" not in result


async def test_stock_journal_filtered_no_results():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [
            {
                "id": 1,
                "product_id": 2,
                "amount": 1,
                "transaction_type": "consume",
                "row_created_timestamp": "2026-03-31 12:00:00",
            },
        ],
        [{"id": 1, "name": "Milk"}, {"id": 2, "name": "Bread"}],
    ]
    with patch("grocy_mcp.core.stock_journal.resolve_product", return_value=1):
        result = await stock_journal(client, product="Milk")
    assert "No stock journal entries found for 'Milk'." in result


def _entry(entry_id, amount, txn="consume"):
    return {
        "id": entry_id,
        "product_id": 1,
        "amount": amount,
        "transaction_type": txn,
        "row_created_timestamp": f"2026-11-07 08:16:{entry_id:02d}",
    }


async def test_stock_journal_hides_float_noise_entries():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [
            _entry(1, 2, "purchase"),
            _entry(2, 2.2204460492503e-16, "product-opened"),
            _entry(3, -2.2204460492503e-16, "transfer_from"),
        ],
        [{"id": 1, "name": "Kitchen paper towel"}],
    ]
    result = await stock_journal(client)
    assert "purchase 2" in result
    assert "e-16" not in result
    assert "product-opened" not in result
    assert "2 zero-amount entries hidden" in result


async def test_stock_journal_rounds_amounts():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [_entry(1, 0.30000000000000004, "purchase"), _entry(2, -4, "consume")],
        [{"id": 1, "name": "Milk"}],
    ]
    result = await stock_journal(client)
    assert "purchase 0.3 " in result
    assert "consume -4 " in result
    assert "hidden" not in result
