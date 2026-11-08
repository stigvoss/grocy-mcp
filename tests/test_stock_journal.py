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


async def test_stock_journal_keeps_large_and_precise_amounts():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [_entry(1, 12.345678, "purchase"), _entry(2, 1234567, "purchase")],
        [{"id": 1, "name": "Flour"}],
    ]
    result = await stock_journal(client)
    assert "purchase 12.345678 " in result
    assert "purchase 1234567 " in result


def _booking(entry_id, kind="consume", amount=-1, stamp="2026-11-08 08:05:45", **extra):
    return {
        "id": entry_id,
        "product_id": 1,
        "amount": amount,
        "transaction_type": kind,
        "row_created_timestamp": stamp,
        **extra,
    }


def _ids(text):
    return [int(line.split("]")[0].split("[")[1]) for line in text.splitlines()[1:] if "[" in line]


async def test_stock_journal_orders_same_second_bookings_newest_first():
    client = AsyncMock()
    # Grocy returns them oldest first; five bookings share one second
    client.get_objects.side_effect = [
        [
            _booking(3411, "purchase", 5, stamp="2026-11-08 08:05:44"),
            _booking(3412, "product-opened", 1),
            _booking(3413, "transfer_from"),
            _booking(3414, "transfer_to", 1),
            _booking(3415, "consume"),
            _booking(3416, "inventory-correction"),
        ],
        [{"id": 1, "name": "Beef"}],
    ]
    result = await stock_journal(client)
    assert _ids(result) == [3416, 3415, 3414, 3413, 3412, 3411]


async def test_stock_journal_older_second_never_outranks_a_newer_one_with_a_lower_id():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [
            _booking(9, stamp="2026-11-08 08:00:00"),
            _booking(5, stamp="2026-11-08 09:00:00"),  # lower id but later timestamp
        ],
        [{"id": 1, "name": "Beef"}],
    ]
    assert _ids(await stock_journal(client)) == [5, 9]


async def test_stock_journal_keeps_the_newest_fifty_when_many_share_a_second():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [_booking(i) for i in range(1, 61)],  # 60 bookings, all in the same second
        [{"id": 1, "name": "Beef"}],
    ]
    ids = _ids(await stock_journal(client))
    assert len(ids) == 50 and ids[0] == 60 and ids[-1] == 11  # the newest 50, not the oldest


async def test_stock_journal_marks_spoiled_consumes():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [
            _booking(1, "consume", -1, spoiled=1),
            _booking(2, "consume", -1, spoiled=0),
            _booking(3, "consume", -1),  # no flag at all
            _booking(4, "purchase", 2, spoiled="0"),
        ],
        [{"id": 1, "name": "Beef"}],
    ]
    lines = {
        int(l.split("]")[0].split("[")[1]): l
        for l in (await stock_journal(client)).splitlines()[1:]
    }
    assert "consume -1 (spoiled)" in lines[1]
    assert (
        "(spoiled)" not in lines[2] and "(spoiled)" not in lines[3] and "(spoiled)" not in lines[4]
    )
