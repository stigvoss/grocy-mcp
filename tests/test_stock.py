"""Tests for the stock core module."""

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
    with patch("grocy_mcp.core.stock.resolve_product", return_value=7):
        result = await stock_product_info(mock_client, "Minced beef")
    assert "In stock: 4 Pack" in result
    assert "Unopened: 3" in result
    assert "Opened: 1" in result
    assert "Location: Freezer" in result


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
    mock_client.get_stock_product.return_value = {"stock_amount": 2, "stock_amount_opened": 0}
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 2.0, opened_amount=1)
    mock_client.inventory_stock.assert_not_called()
    mock_client.open_stock.assert_called_once_with(1, 1)
    assert "unopened 1, opened 1" in result
