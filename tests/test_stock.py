"""Tests for the stock core module."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from grocy_mcp.core.stock import (
    stock_add,
    stock_barcode_lookup,
    stock_consume,
    stock_expiring,
    stock_inventory,
    stock_open,
    stock_overview,
    stock_product_info,
    stock_search,
    stock_transfer,
)


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get_stock.return_value = [
        {"product_id": 1, "amount": 3, "product": {"id": 1, "name": "Milk", "location_id": 1}}
    ]
    client.get_volatile_stock.return_value = {
        "expiring_products": [{"product_id": 1, "amount": 3, "product": {"id": 1, "name": "Milk"}}],
        "expired_products": [],
        "missing_products": [],
    }
    client.get_objects.return_value = [
        {"id": 1, "name": "Milk"},
        {"id": 2, "name": "Bread"},
    ]
    client.add_stock.return_value = [{"id": 10}]
    client.consume_stock.return_value = [{"id": 10}]
    return client


async def test_stock_overview(mock_client):
    result = await stock_overview(mock_client)
    assert "Milk" in result
    assert "3" in result


async def test_stock_expiring(mock_client):
    result = await stock_expiring(mock_client)
    assert "Milk" in result


async def test_stock_add(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1) as mock_resolve:
        result = await stock_add(mock_client, "Milk", 2.0)
        mock_resolve.assert_called_once_with(mock_client, "Milk")
        mock_client.add_stock.assert_called_once_with(1, 2.0)
        assert "added" in result.lower() or "milk" in result.lower()


async def test_stock_consume(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_consume(mock_client, "Milk", 1.0)
        mock_client.consume_stock.assert_called_once_with(1, 1.0)
        assert result


async def test_stock_search(mock_client):
    result = await stock_search(mock_client, "Milk")
    assert "Milk" in result


async def test_stock_product_info(mock_client):
    mock_client.get_stock_product.return_value = {
        "product": {"id": 1, "name": "Milk"},
        "stock_amount": 3,
        "next_best_before_date": "2026-04-01",
    }
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_product_info(mock_client, "Milk")
        mock_client.get_stock_product.assert_called_once_with(1)
        assert "Milk" in result


async def test_stock_transfer(mock_client):
    mock_client.transfer_stock.return_value = [{"id": 10}]
    mock_client.get_stock_locations.return_value = [
        {"location_id": 5, "location_name": "Pantry", "amount": 3}
    ]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=2),
    ):
        result = await stock_transfer(mock_client, "Milk", 1.0, "Fridge")
        mock_client.transfer_stock.assert_called_once_with(1, 1.0, 2, 5)
        assert result


async def test_stock_inventory(mock_client):
    mock_client.inventory_stock.return_value = [{"id": 10}]
    mock_client.get_stock_product.side_effect = [
        {"stock_amount": 8, "stock_amount_opened": 0},
        {"stock_amount": 5, "stock_amount_opened": 0},
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 5.0)
        mock_client.inventory_stock.assert_called_once_with(1, 5.0)
        assert result


async def test_stock_open(mock_client):
    mock_client.get_stock_product.return_value = {"product": {"name": "Milk"}, "stock_amount": 3}
    mock_client.open_stock.return_value = [{"id": 10}]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_open(mock_client, "Milk", 1.0)
        mock_client.open_stock.assert_called_once_with(1, 1.0)
        assert result


async def test_stock_barcode_lookup(mock_client):
    mock_client.get_stock_by_barcode.return_value = {
        "product": {"id": 1, "name": "Milk"},
        "stock_amount": 3,
    }
    result = await stock_barcode_lookup(mock_client, "1234567890")
    mock_client.get_stock_by_barcode.assert_called_once_with("1234567890")
    assert "Milk" in result


async def test_stock_overview_empty(mock_client):
    mock_client.get_stock.return_value = []
    result = await stock_overview(mock_client)
    assert result == "No stock found."


async def test_stock_overview_format(mock_client):
    result = await stock_overview(mock_client)
    assert "Current stock:" in result
    assert "[1] Milk" in result


async def test_stock_expiring_empty(mock_client):
    mock_client.get_volatile_stock.return_value = {
        "expiring_products": [],
        "expired_products": [],
        "missing_products": [],
    }
    result = await stock_expiring(mock_client)
    assert "No expiring, expired, or missing products found." in result


async def test_stock_add_quotes_name(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_add(mock_client, "Milk", 2.0)
        assert "'Milk'" in result


async def test_stock_consume_quotes_name(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_consume(mock_client, "Milk", 1.0)
        assert "'Milk'" in result


async def test_stock_transfer_quotes_names(mock_client):
    mock_client.transfer_stock.return_value = [{"id": 10}]
    mock_client.get_stock_locations.return_value = [
        {"location_id": 5, "location_name": "Pantry", "amount": 3}
    ]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=2),
    ):
        result = await stock_transfer(mock_client, "Eggs", 3.0, "Fridge")
        assert "'Eggs'" in result
        assert "'Fridge'" in result


async def test_stock_inventory_quotes_name(mock_client):
    mock_client.inventory_stock.return_value = [{"id": 10}]
    mock_client.get_stock_product.side_effect = [
        {"stock_amount": 8, "stock_amount_opened": 0},
        {"stock_amount": 5, "stock_amount_opened": 0},
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 5.0)
        assert "'Milk'" in result


async def test_stock_open_quotes_name(mock_client):
    mock_client.get_stock_product.return_value = {"product": {"name": "Milk"}, "stock_amount": 3}
    mock_client.open_stock.return_value = [{"id": 10}]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_open(mock_client, "Milk", 1.0)
        assert "'Milk'" in result


async def test_stock_search_uses_bracket_ids(mock_client):
    mock_client.get_objects.side_effect = [
        [{"id": 1, "name": "Milk"}, {"id": 2, "name": "Bread"}],
        [],
    ]
    result = await stock_search(mock_client, "Milk")
    assert "[1] Milk" in result


async def test_stock_search_no_results(mock_client):
    mock_client.get_objects.side_effect = [
        [{"id": 1, "name": "Milk"}],
        [],
    ]
    result = await stock_search(mock_client, "Cheese")
    assert "No products found matching 'Cheese'." in result


def _info(stock, opened, name="Minced beef"):
    return {
        "product": {"id": 7, "name": name},
        "stock_amount": stock,
        "stock_amount_opened": opened,
        "quantity_unit_stock": {"name": "Pack"},
        "location": {"name": "Freezer"},
        "next_best_before_date": "2026-12-01",
    }


async def test_stock_product_info_includes_unit_location_and_opened(mock_client):
    mock_client.get_stock_product.return_value = _info(4, 1)
    mock_client.get_stock_locations.return_value = [
        {"location_name": "Freezer", "amount": 3},
        {"location_name": "Fridge", "amount": 1},
        {"location_name": "Pantry", "amount": 4.4408920985006e-16},
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=7):
        result = await stock_product_info(mock_client, "Minced beef")
    assert "In stock: 4 Pack" in result
    assert "Unopened: 3" in result
    assert "Opened: 1" in result
    assert "Stock locations: Freezer 3, Fridge 1" in result
    assert "Pantry" not in result
    assert "Default location (where new stock goes, not necessarily where it is): Freezer" in result


async def test_stock_open_already_open_returns_message_without_calling_api(mock_client):
    mock_client.get_stock_product.return_value = _info(1, 1)
    with patch("grocy_mcp.core.stock.resolve_product", return_value=7):
        result = await stock_open(mock_client, "Minced beef", 1.0)
    mock_client.open_stock.assert_not_called()
    assert "Minced beef" in result
    assert "unopened amount is 0" in result


async def test_stock_open_validation_error_becomes_message(mock_client):
    from grocy_mcp.exceptions import GrocyValidationError

    mock_client.get_stock_product.return_value = _info(2, 0)
    mock_client.open_stock.side_effect = GrocyValidationError("Validation error: SQL boom")
    with patch("grocy_mcp.core.stock.resolve_product", return_value=7):
        result = await stock_open(mock_client, "Minced beef", 1.0)
    assert "SQL" not in result
    assert "Minced beef" in result


async def test_stock_levels_includes_zero_stock_and_filters(mock_client):
    from grocy_mcp.core.stock import stock_levels_data

    mock_client.get_stock.return_value = [{"product_id": 1, "amount": 3, "amount_aggregated": 3}]

    async def get_objects(entity, query=None):
        return {
            "products": [
                {
                    "id": 1,
                    "name": "Milk",
                    "qu_id_stock": 1,
                    "location_id": 1,
                    "product_group_id": 5,
                    "userfields": {"high_churn": "1"},
                },
                {
                    "id": 2,
                    "name": "Cooking cream",
                    "qu_id_stock": 1,
                    "location_id": 2,
                    "product_group_id": 6,
                    "userfields": {"high_churn": "0"},
                },
                {"id": 3, "name": "Old", "active": 0, "qu_id_stock": 1},
            ],
            "quantity_units": [{"id": 1, "name": "Pack"}],
            "locations": [{"id": 1, "name": "Fridge"}, {"id": 2, "name": "Pantry"}],
            "product_groups": [{"id": 5, "name": "Dairy"}, {"id": 6, "name": "Cooking"}],
        }[entity]

    mock_client.get_objects.side_effect = get_objects

    rows = await stock_levels_data(mock_client)
    cream = next(r for r in rows if r["name"] == "Cooking cream")
    assert cream["amount"] == 0
    assert cream["stock_unit"] == "Pack"
    assert cream["default_location"] == "Pantry"
    assert all(r["name"] != "Old" for r in rows)

    assert [r["name"] for r in await stock_levels_data(mock_client, high_churn=True)] == ["Milk"]
    by_group = await stock_levels_data(mock_client, product_group="cooking")
    assert [r["name"] for r in by_group] == ["Cooking cream"]


async def test_stock_levels_reports_aggregated_amount_for_parent(mock_client):
    from grocy_mcp.core.stock import stock_levels_data

    mock_client.get_stock.return_value = [
        {"product_id": 10, "amount": 0, "amount_aggregated": 4},
        {"product_id": 11, "amount": 4, "amount_aggregated": 4},
    ]

    async def get_objects(entity, query=None):
        return {
            "products": [
                {"id": 10, "name": "Pasta", "qu_id_stock": 1},
                {"id": 11, "name": "Penne", "qu_id_stock": 1, "parent_product_id": 10},
                {"id": 12, "name": "Empty", "qu_id_stock": 1},
            ],
            "quantity_units": [{"id": 1, "name": "Pack"}],
            "locations": [],
        }[entity]

    mock_client.get_objects.side_effect = get_objects

    rows = {r["name"]: r for r in await stock_levels_data(mock_client)}
    assert rows["Pasta"]["amount"] == 0
    assert rows["Pasta"]["amount_aggregated"] == 4
    assert rows["Penne"]["amount_aggregated"] == 4
    assert rows["Empty"]["amount_aggregated"] == 0


async def test_stock_add_passes_price_best_before_and_location(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_add(
            mock_client, "Beef", 2.0, price=15.5, best_before_date="2027-01-31", location_id=3
        )
    mock_client.add_stock.assert_called_once_with(
        1, 2.0, price=15.5, best_before_date="2027-01-31", location_id=3
    )
    assert "price 15.5" in result


async def test_stock_add_rejects_bad_price_and_date(mock_client):
    from grocy_mcp.exceptions import GrocyValidationError

    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        with pytest.raises(GrocyValidationError, match="price"):
            await stock_add(mock_client, "Beef", 1.0, price=-1)
        with pytest.raises(GrocyValidationError, match="YYYY-MM-DD"):
            await stock_add(mock_client, "Beef", 1.0, best_before_date="31/01/2027")
    mock_client.add_stock.assert_not_called()


@pytest.mark.parametrize("price", [float("nan"), float("inf"), -0.5])
async def test_stock_add_rejects_non_finite_or_negative_price(mock_client, price):
    from grocy_mcp.exceptions import GrocyValidationError

    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1) as resolve,
        pytest.raises(GrocyValidationError, match="price"),
    ):
        await stock_add(mock_client, "Beef", 1.0, price=price)
    resolve.assert_not_called()
    mock_client.add_stock.assert_not_called()


@pytest.mark.parametrize("value", ["20270131", "2027-W04-7", "2027-1-31"])
async def test_stock_add_rejects_non_strict_dates(mock_client, value):
    from grocy_mcp.exceptions import GrocyValidationError

    with pytest.raises(GrocyValidationError, match="YYYY-MM-DD"):
        await stock_add(mock_client, "Beef", 1.0, best_before_date=value)
    mock_client.add_stock.assert_not_called()


async def test_stock_add_passes_purchased_date_store_and_location_name(mock_client):
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=4) as resolve_loc,
    ):
        await stock_add(
            mock_client,
            "Beef",
            1.0,
            location="Freezer",
            purchased_date="2026-11-07",
            shopping_location_id=2,
        )
    resolve_loc.assert_called_once_with(mock_client, "Freezer")
    mock_client.add_stock.assert_called_once_with(
        1, 1.0, location_id=4, purchased_date="2026-11-07", shopping_location_id=2
    )


async def test_stock_add_rejects_location_and_location_id_together(mock_client):
    from grocy_mcp.exceptions import GrocyValidationError

    with pytest.raises(GrocyValidationError, match="either location or location_id"):
        await stock_add(mock_client, "Beef", 1.0, location="Freezer", location_id=4)
    mock_client.add_stock.assert_not_called()


async def test_stock_add_rejects_bad_purchased_date(mock_client):
    from grocy_mcp.exceptions import GrocyValidationError

    with pytest.raises(GrocyValidationError, match="purchased_date"):
        await stock_add(mock_client, "Beef", 1.0, purchased_date="20261107")
    mock_client.add_stock.assert_not_called()


async def test_stock_transfer_uses_explicit_from_location(mock_client):
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", side_effect=[2, 7]),
    ):
        await stock_transfer(mock_client, "Milk", 1.0, "Fridge", from_location="Pantry")
    mock_client.get_stock_locations.assert_not_called()
    mock_client.transfer_stock.assert_called_once_with(1, 1.0, 2, 7)


async def test_stock_transfer_ambiguous_source_asks_for_from_location(mock_client):
    from grocy_mcp.exceptions import GrocyValidationError

    mock_client.get_stock_locations.return_value = [
        {"location_id": 5, "location_name": "Pantry", "amount": 3},
        {"location_id": 6, "location_name": "Freezer", "amount": 1},
        {"location_id": 7, "location_name": "Empty", "amount": 0},
    ]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=2),
        pytest.raises(GrocyValidationError, match=r"Pantry \(3\), Freezer \(1\).*from_location"),
    ):
        await stock_transfer(mock_client, "Milk", 1.0, "Fridge")
    mock_client.transfer_stock.assert_not_called()


async def test_stock_transfer_without_stock_is_a_clear_error(mock_client):
    from grocy_mcp.exceptions import GrocyValidationError

    mock_client.get_stock_locations.return_value = []
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=2),
        pytest.raises(GrocyValidationError, match="no stock to transfer"),
    ):
        await stock_transfer(mock_client, "Milk", 1.0, "Fridge")


async def test_stock_inventory_reports_split(mock_client):
    mock_client.get_stock_product.side_effect = [
        {"stock_amount": 3, "stock_amount_opened": 1},
        {"stock_amount": 2, "stock_amount_opened": 1},
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 2.0)
    assert "unopened 1, opened 1" in result
    mock_client.open_stock.assert_not_called()


async def test_stock_inventory_opens_missing_units_to_match_opened_amount(mock_client):
    # Grocy dropped the opened unit first: 2 in stock, none opened
    mock_client.get_stock_product.side_effect = [
        {"stock_amount": 3, "stock_amount_opened": 1},
        {"stock_amount": 2, "stock_amount_opened": 0},
        {"stock_amount": 2, "stock_amount_opened": 1},
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 2.0, opened_amount=1)
    mock_client.open_stock.assert_called_once_with(1, 1)
    assert "unopened 1, opened 1" in result


async def test_stock_inventory_cannot_unopen(mock_client):
    mock_client.get_stock_product.side_effect = [
        {"stock_amount": 3, "stock_amount_opened": 2},
        {"stock_amount": 2, "stock_amount_opened": 2},
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 2.0, opened_amount=1)
    mock_client.open_stock.assert_not_called()
    assert "cannot un-open" in result


@pytest.mark.parametrize("opened", [-1, 3, float("nan")])
async def test_stock_inventory_rejects_bad_opened_amount_before_any_request(mock_client, opened):
    from grocy_mcp.exceptions import GrocyValidationError

    with pytest.raises(GrocyValidationError, match="opened_amount"):
        await stock_inventory(mock_client, "Milk", 2.0, opened_amount=opened)
    mock_client.inventory_stock.assert_not_called()


async def test_stock_inventory_skips_inventory_when_amount_unchanged(mock_client):
    mock_client.get_stock_product.side_effect = [
        {"stock_amount": 2, "stock_amount_opened": 0},
        {"stock_amount": 2, "stock_amount_opened": 0},
        {"stock_amount": 2, "stock_amount_opened": 1},
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 2.0, opened_amount=1)
    mock_client.inventory_stock.assert_not_called()
    mock_client.open_stock.assert_called_once_with(1, 1)
    assert "unopened 1, opened 1" in result


class _FakeStockClient:
    """Tiny stateful stand-in for Grocy: one product with a total and an opened count."""

    def __init__(self, total, opened):
        self.total, self.opened = total, opened
        self.open_calls = []

    async def get_stock_product(self, product_id):
        await asyncio.sleep(0)
        return {"stock_amount": self.total, "stock_amount_opened": self.opened}

    async def inventory_stock(self, product_id, new_amount):
        await asyncio.sleep(0)
        removed = self.total - new_amount
        self.opened = max(self.opened - removed, 0)
        self.total = new_amount

    async def open_stock(self, product_id, amount):
        await asyncio.sleep(0)
        self.open_calls.append(amount)
        self.opened += amount


async def test_stock_inventory_overlapping_calls_do_not_double_open():
    client = _FakeStockClient(total=3, opened=0)
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        results = await asyncio.gather(
            stock_inventory(client, "Milk", 2.0, opened_amount=1),
            stock_inventory(client, "Milk", 2.0, opened_amount=1),
        )
    assert client.opened == 1
    assert client.open_calls == [1]
    assert all("unopened 1, opened 1" in r for r in results)


async def test_stock_inventory_reports_actual_split_when_opening_fails(mock_client):
    from grocy_mcp.exceptions import GrocyValidationError

    mock_client.get_stock_product.side_effect = [
        {"stock_amount": 3, "stock_amount_opened": 1},
        {"stock_amount": 2, "stock_amount_opened": 0},
        {"stock_amount": 2, "stock_amount_opened": 0},
    ]
    mock_client.open_stock.side_effect = GrocyValidationError("Validation error: boom")
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 2.0, opened_amount=1)
    assert "unopened 2, opened 0" in result
    assert "inventory was applied" in result
    assert "boom" not in result


async def test_stock_inventory_rereads_split_after_opening(mock_client):
    mock_client.get_stock_product.side_effect = [
        {"stock_amount": 3, "stock_amount_opened": 0},
        {"stock_amount": 2, "stock_amount_opened": 0},
        {"stock_amount": 2, "stock_amount_opened": 2},
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 2.0, opened_amount=1)
    assert "unopened 0, opened 2" in result
    assert "cannot un-open" in result


def test_stock_inventory_locks_work_across_successive_event_loops():
    def run_once():
        client = _FakeStockClient(total=3, opened=0)

        async def both():
            with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
                return await asyncio.gather(
                    stock_inventory(client, "Milk", 2.0, opened_amount=1),
                    stock_inventory(client, "Milk", 2.0, opened_amount=1),
                )

        asyncio.run(both())
        return client

    assert run_once().opened == 1
    assert run_once().opened == 1


def test_stock_inventory_locks_are_not_retained_after_use():
    import gc

    from grocy_mcp.core import stock as stock_module

    client = _FakeStockClient(total=3, opened=0)

    async def both():
        with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
            await asyncio.gather(
                stock_inventory(client, "Milk", 2.0, opened_amount=1),
                stock_inventory(client, "Milk", 2.0, opened_amount=1),
            )

    asyncio.run(both())
    gc.collect()
    assert all(len(locks) == 0 for locks in stock_module._product_locks.values())


async def test_stock_overview_rounds_and_hides_float_noise_rows(mock_client):
    mock_client.get_stock.return_value = [
        {"product_id": 1, "amount": 1.0000000000000007, "product": {"name": "Paper towel"}},
        {"product_id": 2, "amount": 4.4408920985006e-16, "product": {"name": "Phantom"}},
        {"product_id": 3, "amount": 12.345678, "product": {"name": "Flour"}},
    ]
    result = await stock_overview(mock_client)
    assert "Paper towel — 1" in result
    assert "1.0000000" not in result
    assert "Phantom" not in result
    assert "Flour — 12.345678" in result
    assert "(1 zero-amount row hidden)" in result


async def test_stock_levels_rounds_amounts(mock_client):
    from grocy_mcp.core.stock import stock_levels_data

    mock_client.get_stock.return_value = [
        {"product_id": 1, "amount": 1.0000000000000007, "amount_aggregated": 1.0000000000000007}
    ]

    async def get_objects(entity, query=None):
        return {
            "products": [{"id": 1, "name": "Paper towel", "qu_id_stock": 1}],
            "quantity_units": [{"id": 1, "name": "Roll"}],
            "locations": [],
        }[entity]

    mock_client.get_objects.side_effect = get_objects
    rows = await stock_levels_data(mock_client)
    assert rows[0]["amount"] == 1.0
    assert rows[0]["amount_aggregated"] == 1.0


async def test_stock_product_info_does_not_cut_significant_digits(mock_client):
    mock_client.get_stock_product.return_value = {
        "product": {"name": "Flour"},
        "stock_amount": 1234567.0,
        "stock_amount_opened": 0,
    }
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_product_info(mock_client, "Flour")
    assert "In stock: 1234567 " in result
    assert "e+" not in result


def _location_client(mock_client):
    async def get_objects(entity, query=None):
        return {
            "stock_current_locations": [
                {
                    "product_id": 1,
                    "amount": 3,
                    "location_id": 4,
                    "location_name": "Freezer",
                    "location_is_freezer": 1,
                },
                {
                    "product_id": 1,
                    "amount": 1.0000000000000002,
                    "location_id": 2,
                    "location_name": "Fridge",
                    "location_is_freezer": 0,
                },
                {
                    "product_id": 2,
                    "amount": 2,
                    "location_id": 2,
                    "location_name": "Fridge",
                    "location_is_freezer": 0,
                },
                {
                    "product_id": 2,
                    "amount": 4.4408920985006e-16,
                    "location_id": 3,
                    "location_name": "Pantry",
                    "location_is_freezer": 0,
                },
            ],
            "products": [
                {"id": 1, "name": "Minced beef", "qu_id_stock": 7},
                {"id": 2, "name": "Milk", "qu_id_stock": 7},
            ],
            "quantity_units": [{"id": 7, "name": "Pack"}],
            "locations": [
                {"id": 2, "name": "Fridge"},
                {"id": 3, "name": "Pantry"},
                {"id": 4, "name": "Freezer"},
            ],
        }[entity]

    mock_client.get_objects.side_effect = get_objects
    return mock_client


async def test_stock_by_location_lists_names_amounts_and_skips_noise(mock_client):
    from grocy_mcp.core.stock import stock_by_location_data

    rows = await stock_by_location_data(_location_client(mock_client))
    assert [(r["location"], r["name"], r["amount"]) for r in rows] == [
        ("Freezer", "Minced beef", 3.0),
        ("Fridge", "Milk", 2.0),
        ("Fridge", "Minced beef", 1.0),
    ]
    assert rows[0]["stock_unit"] == "Pack"
    assert rows[0]["is_freezer"] is True


async def test_stock_by_location_filters_by_name_and_freezer(mock_client):
    from grocy_mcp.core.stock import stock_by_location_data

    client = _location_client(mock_client)
    fridge = await stock_by_location_data(client, location="Fridge")
    assert {r["location"] for r in fridge} == {"Fridge"}
    freezer = await stock_by_location_data(client, freezer_only=True)
    assert [r["name"] for r in freezer] == ["Minced beef"]


async def test_stock_levels_location_filter_adds_amount_in_location(mock_client):
    from grocy_mcp.core.stock import stock_levels_data

    client = _location_client(mock_client)
    mock_client.get_stock.return_value = [
        {"product_id": 1, "amount": 4, "amount_aggregated": 4},
        {"product_id": 2, "amount": 2, "amount_aggregated": 2},
    ]
    rows = await stock_levels_data(client, location="Freezer")
    assert [(r["name"], r["amount"], r["amount_in_location"]) for r in rows] == [
        ("Minced beef", 4.0, 3.0)
    ]


async def test_stock_consume_from_location_passes_location_id(mock_client):
    mock_client.get_stock_locations.return_value = [
        {"location_id": 4, "location_name": "Freezer", "amount": 2},
        {"location_id": 2, "location_name": "Fridge", "amount": 1},
    ]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=4),
    ):
        result = await stock_consume(mock_client, "Beef", 2.0, from_location="Freezer")
    mock_client.consume_stock.assert_called_once_with(1, 2.0, location_id=4)
    assert "from 'Freezer'" in result


async def test_stock_consume_from_location_with_too_little_lists_where_stock_is(mock_client):
    from grocy_mcp.exceptions import GrocyValidationError

    mock_client.get_stock_locations.return_value = [
        {"location_id": 4, "location_name": "Freezer", "amount": 1},
        {"location_id": 2, "location_name": "Fridge", "amount": 3},
    ]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=4),
        pytest.raises(GrocyValidationError, match=r"holds 1\. Stock is at: Freezer 1, Fridge 3"),
    ):
        await stock_consume(mock_client, "Beef", 2.0, from_location="Freezer")
    mock_client.consume_stock.assert_not_called()


async def test_stock_consume_from_location_without_stock_there(mock_client):
    from grocy_mcp.exceptions import GrocyValidationError

    mock_client.get_stock_locations.return_value = [
        {"location_id": 2, "location_name": "Fridge", "amount": 3}
    ]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=4),
        pytest.raises(GrocyValidationError, match=r"holds 0\. Stock is at: Fridge 3"),
    ):
        await stock_consume(mock_client, "Beef", 1.0, from_location="Freezer")


async def test_stock_consume_spoiled_flag(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_consume(mock_client, "Milk", 1.0, spoiled=True)
    mock_client.consume_stock.assert_called_once_with(1, 1.0, spoiled=True)
    assert "spoiled" in result


async def test_stock_consume_default_behaviour_unchanged(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        await stock_consume(mock_client, "Milk", 1.0)
    mock_client.consume_stock.assert_called_once_with(1, 1.0)
    mock_client.get_stock_locations.assert_not_called()


def _entry(**over):
    entry = {
        "id": 24,
        "product_id": 1,
        "amount": 2,
        "best_before_date": "2026-11-07",
        "purchased_date": "2026-11-07",
        "price": None,
        "open": 0,
        "location_id": 2,
        "shopping_location_id": None,
    }
    entry.update(over)
    return entry


async def test_stock_entry_edit_sends_full_entry_with_changes(mock_client):
    from grocy_mcp.core.stock import stock_entry_edit

    mock_client.get_stock_entry.return_value = _entry(shopping_location_id=2, note="from market")
    mock_client.get_objects.return_value = [{"id": 4, "name": "Freezer"}]
    with patch("grocy_mcp.core.stock.resolve_location", return_value=4):
        result = await stock_entry_edit(
            mock_client, 24, price=15.5, best_before_date="2027-01-31", location="Freezer"
        )
    mock_client.update_stock_entry.assert_called_once_with(
        24,
        {
            "amount": 2,
            "best_before_date": "2027-01-31",
            "purchased_date": "2026-11-07",
            "location_id": 4,
            "open": 0,
            "shopping_location_id": 2,
            "note": "from market",
            "price": 15.5,
        },
    )
    assert "price None -> 15.5" in result
    assert "best_before_date 2026-11-07 -> 2027-01-31" in result


async def test_stock_entry_edit_open_flag(mock_client):
    from grocy_mcp.core.stock import stock_entry_edit

    mock_client.get_stock_entry.return_value = _entry()
    await stock_entry_edit(mock_client, 24, open=True)
    assert mock_client.update_stock_entry.call_args.args[1]["open"] == 1


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "at least one field"),
        ({"amount": 0}, "greater than 0"),
        ({"amount": float("nan")}, "greater than 0"),
        ({"price": -1}, "price"),
        ({"price": float("inf")}, "price"),
        ({"best_before_date": "20270131"}, "best_before_date"),
        ({"purchased_date": "tomorrow"}, "purchased_date"),
    ],
)
async def test_stock_entry_edit_validates_before_any_request(mock_client, kwargs, message):
    from grocy_mcp.core.stock import stock_entry_edit
    from grocy_mcp.exceptions import GrocyValidationError

    with pytest.raises(GrocyValidationError, match=message):
        await stock_entry_edit(mock_client, 24, **kwargs)
    mock_client.get_stock_entry.assert_not_called()
    mock_client.update_stock_entry.assert_not_called()


async def test_stock_undo_calls_client_and_explains_failure(mock_client):
    from grocy_mcp.core.stock import stock_undo
    from grocy_mcp.exceptions import GrocyValidationError

    mock_client.get_object.return_value = {"id": 17, "product_id": 1}
    assert "Undid booking 17" in await stock_undo(mock_client, 17)
    mock_client.get_object.assert_called_once_with("stock_log", 17)
    mock_client.undo_booking.assert_called_once_with(17)

    mock_client.undo_booking.side_effect = GrocyValidationError("Validation error: gone")
    with pytest.raises(GrocyValidationError, match="may already be undone"):
        await stock_undo(mock_client, 17)


async def test_stock_undo_of_an_unknown_booking_is_a_clear_error(mock_client):
    from grocy_mcp.core.stock import stock_undo
    from grocy_mcp.exceptions import GrocyNotFoundError, GrocyValidationError

    mock_client.get_object.side_effect = GrocyNotFoundError("Not found: x")
    with pytest.raises(GrocyValidationError, match="does not exist"):
        await stock_undo(mock_client, 999)
    mock_client.undo_booking.assert_not_called()


async def test_stock_entries_lists_ids_and_location_names(mock_client):
    from grocy_mcp.core.stock import stock_entries_data

    mock_client.get_stock_entries.return_value = [
        _entry(id=24, location_id=2),
        _entry(id=25, location_id=4, open=1, price=4.5),
    ]

    async def get_objects(entity, query=None):
        return {"locations": [{"id": 2, "name": "Fridge"}, {"id": 4, "name": "Freezer"}]}[entity]

    mock_client.get_objects.side_effect = get_objects
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        rows = await stock_entries_data(mock_client, "Beef")
        freezer = None
        with patch("grocy_mcp.core.stock.resolve_location", return_value=4):
            freezer = await stock_entries_data(mock_client, "Beef", location="Freezer")
    assert [(r["entry_id"], r["location"], r["opened"]) for r in rows] == [
        (24, "Fridge", False),
        (25, "Freezer", True),
    ]
    assert [r["entry_id"] for r in freezer] == [25]


async def test_stock_search_matches_userfields_when_asked(mock_client):
    async def get_objects(entity, query=None):
        return {
            "products": [
                {
                    "id": 1,
                    "name": "Minced beef",
                    "userfields": {
                        "bilkatogo": "https://x/search?query=hakket%20oksek%C3%B8d",
                        "ai_notes": "",
                    },
                },
                {"id": 2, "name": "Milk", "userfields": {"ai_notes": "mælk"}},
            ],
            "product_barcodes": [],
        }[entity]

    mock_client.get_objects.side_effect = get_objects
    assert "No products found" in await stock_search(mock_client, "hakket")
    result = await stock_search(mock_client, "hakket", include_userfields=True)
    assert "[1] Minced beef (userfield: bilkatogo)" in result
    assert "Milk" not in result
    assert "[1] Minced beef" in await stock_search(mock_client, "oksekød", include_userfields=True)
    # name matches are not tagged and are not duplicated
    both = await stock_search(mock_client, "minced", include_userfields=True)
    assert both.count("Minced beef") == 1 and "userfield" not in both


async def test_unknown_numeric_location_is_an_error_not_an_empty_result(mock_client):
    from grocy_mcp.core.stock import stock_by_location_data, stock_levels_data
    from grocy_mcp.exceptions import GrocyValidationError

    client = _location_client(mock_client)
    for call in (
        lambda: stock_by_location_data(client, location="999"),
        lambda: stock_levels_data(client, location="999"),
    ):
        with pytest.raises(GrocyValidationError, match=r"Unknown location '999'.*Fridge \(2\)"):
            await call()


@pytest.mark.parametrize(
    "held, requested, allowed",
    [
        (0.1234564, 0.1234564, True),  # exactly what is held is never refused
        (1.9999996, 2.0, False),  # a shortfall is not rounded away
        (0.9999999999999999, 1.0, True),  # float residue below the request is tolerated
        (1.0, 1.0000001, False),
        (0.0000004, 0.0000004, True),  # a tiny but real balance is not discarded as noise
        (0.0000004, 0.0000005, False),
    ],
)
async def test_stock_consume_from_location_compares_the_real_balance(
    mock_client, held, requested, allowed
):
    from grocy_mcp.exceptions import GrocyValidationError

    mock_client.get_stock_locations.return_value = [
        {"location_id": 4, "location_name": "Freezer", "amount": held}
    ]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=4),
    ):
        if allowed:
            await stock_consume(mock_client, "Beef", requested, from_location="Freezer")
            mock_client.consume_stock.assert_called_once()
        else:
            with pytest.raises(GrocyValidationError, match="holds"):
                await stock_consume(mock_client, "Beef", requested, from_location="Freezer")
            mock_client.consume_stock.assert_not_called()


async def test_stock_entry_edit_keeps_the_note_on_a_price_only_edit(mock_client):
    from grocy_mcp.core.stock import stock_entry_edit

    mock_client.get_stock_entry.return_value = _entry(note="freeze on arrival")
    await stock_entry_edit(mock_client, 24, price=2.5)
    assert mock_client.update_stock_entry.call_args.args[1]["note"] == "freeze on arrival"


class _FakeEntryClient:
    """Stateful stand-in: a PUT replaces the entry with exactly what it was sent."""

    def __init__(self):
        self.entry = _entry(amount=1, price=None)

    async def get_stock_entry(self, entry_id):
        await asyncio.sleep(0)
        return dict(self.entry)

    async def update_stock_entry(self, entry_id, payload):
        await asyncio.sleep(0)
        self.entry = {**self.entry, **payload}


async def test_stock_entry_edit_overlapping_edits_do_not_overwrite_each_other():
    from grocy_mcp.core.stock import stock_entry_edit

    client = _FakeEntryClient()
    await asyncio.gather(
        stock_entry_edit(client, 24, amount=5),
        stock_entry_edit(client, 24, price=9.5),
    )
    assert client.entry["amount"] == 5 and client.entry["price"] == 9.5


async def test_stock_search_finds_encoded_uppercase_in_userfields(mock_client):
    async def get_objects(entity, query=None):
        return {
            "products": [
                {
                    "id": 1,
                    "name": "Beef",
                    "userfields": {"bilkatogo": "https://x/?query=OKSEK%C3%98D"},
                }
            ],
            "product_barcodes": [],
        }[entity]

    mock_client.get_objects.side_effect = get_objects
    assert "[1] Beef (userfield: bilkatogo)" in await stock_search(
        mock_client, "oksekød", include_userfields=True
    )


async def test_stock_consume_error_hides_noise_rows_but_lists_real_ones(mock_client):
    from grocy_mcp.exceptions import GrocyValidationError

    mock_client.get_stock_locations.return_value = [
        {"location_id": 4, "location_name": "Freezer", "amount": 1},
        {"location_id": 3, "location_name": "Pantry", "amount": 4.4408920985006e-16},
        {"location_id": 2, "location_name": "Fridge", "amount": 3},
    ]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=4),
        pytest.raises(GrocyValidationError) as exc,
    ):
        await stock_consume(mock_client, "Beef", 2.0, from_location="Freezer")
    assert "Freezer 1, Fridge 3" in str(exc.value) and "Pantry" not in str(exc.value)


async def test_entries_and_edit_reject_unknown_numeric_locations(mock_client):
    from grocy_mcp.core.stock import stock_entries_data, stock_entry_edit
    from grocy_mcp.exceptions import GrocyValidationError

    async def get_objects(entity, query=None):
        return {"locations": [{"id": 2, "name": "Fridge"}, {"id": 4, "name": "Freezer"}]}[entity]

    mock_client.get_objects.side_effect = get_objects
    mock_client.get_stock_entry.return_value = _entry()
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        pytest.raises(GrocyValidationError, match=r"Unknown location '999'.*Fridge \(2\)"),
    ):
        await stock_entries_data(mock_client, "Beef", location="999")
    with pytest.raises(GrocyValidationError, match=r"Unknown location '999'"):
        await stock_entry_edit(mock_client, 24, location="999")
    mock_client.update_stock_entry.assert_not_called()


class _FakeProductClient:
    """Stateful stand-in with one entry; a consume lowers it, an edit PUT replaces fields."""

    def __init__(self, amount=2):
        self.entry = _entry(amount=amount, price=None)

    async def get_stock_entry(self, entry_id):
        await asyncio.sleep(0)
        return dict(self.entry)

    async def update_stock_entry(self, entry_id, payload):
        await asyncio.sleep(0)
        self.entry = {**self.entry, **payload}

    async def get_stock_locations(self, product_id):
        await asyncio.sleep(0)
        return [{"location_id": 2, "location_name": "Fridge", "amount": self.entry["amount"]}]

    async def consume_stock(self, product_id, amount, **kwargs):
        await asyncio.sleep(0)
        self.entry["amount"] -= amount


async def test_consume_overlapping_a_price_only_edit_is_not_undone():
    from grocy_mcp.core.stock import stock_entry_edit

    client = _FakeProductClient(amount=2)
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=2),
    ):
        await asyncio.gather(
            stock_entry_edit(client, 24, price=9.5),
            stock_consume(client, "Beef", 1.0, from_location="Fridge"),
        )
    assert client.entry["amount"] == 1  # the consumed unit stays consumed
    assert client.entry["price"] == 9.5


async def test_edit_started_first_still_sees_the_consume_that_ran_before_its_write():
    from grocy_mcp.core.stock import stock_entry_edit

    client = _FakeProductClient(amount=2)
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=2),
    ):
        await asyncio.gather(
            stock_consume(client, "Beef", 1.0, from_location="Fridge"),
            stock_entry_edit(client, 24, price=9.5),
        )
    assert client.entry["amount"] == 1 and client.entry["price"] == 9.5


class _FakeUndoClient(_FakeProductClient):
    """A consume booking that an overlapping undo and price-only edit both touch."""

    async def get_object(self, entity, obj_id):
        await asyncio.sleep(0)
        return {"id": obj_id, "product_id": 1}

    async def undo_booking(self, booking_id):
        await asyncio.sleep(0)
        self.entry["amount"] += 1  # reverses a consume of one unit


async def test_undo_overlapping_an_edit_is_not_overwritten():
    from grocy_mcp.core.stock import stock_entry_edit, stock_undo

    client = _FakeUndoClient(amount=1)
    await asyncio.gather(
        stock_entry_edit(client, 24, price=9.5),
        stock_undo(client, 17),
    )
    assert client.entry["amount"] == 2 and client.entry["price"] == 9.5


class _FakeOpenClient(_FakeProductClient):
    """One unopened pack; opening flips the entry to opened, like Grocy does."""

    async def get_stock_product(self, product_id):
        await asyncio.sleep(0)
        return {
            "product": {"name": "Beef"},
            "stock_amount": self.entry["amount"],
            "stock_amount_opened": self.entry["amount"] if self.entry["open"] else 0,
        }

    async def open_stock(self, product_id, amount):
        await asyncio.sleep(0)
        self.entry["open"] = 1


async def test_opening_overlapping_a_price_only_edit_is_not_silently_undone():
    from grocy_mcp.core.stock import stock_entry_edit, stock_open

    for first in ("edit", "open"):
        client = _FakeOpenClient(amount=1)
        with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
            calls = {
                "edit": stock_entry_edit(client, 24, price=9.5),
                "open": stock_open(client, "Beef", 1.0),
            }
            order = ["edit", "open"] if first == "edit" else ["open", "edit"]
            await asyncio.gather(*(calls[name] for name in order))
        assert client.entry["open"] == 1, f"open was undone (started with {first})"
        assert client.entry["price"] == 9.5
