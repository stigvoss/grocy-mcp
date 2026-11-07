"""Tests for workflow-oriented preview/apply helpers."""

from unittest.mock import AsyncMock

import pytest

from grocy_mcp.core.workflows import (
    workflow_match_products_preview_data,
    workflow_shopping_reconcile_apply_data,
    workflow_shopping_reconcile_preview_data,
    workflow_stock_intake_apply_data,
)
from grocy_mcp.exceptions import GrocyValidationError


async def test_workflow_match_products_preview_exact_barcode():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [{"id": 1, "name": "Whole Milk"}],
        [{"id": 10, "product_id": 1, "barcode": "5000112637922"}],
    ]

    result = await workflow_match_products_preview_data(
        client,
        [{"label": "milk", "quantity": 2, "barcode": "5000112637922", "unit_text": "cartons"}],
    )

    assert result[0]["status"] == "matched"
    assert result[0]["matched_product_id"] == 1
    assert result[0]["matched_product_name"] == "Whole Milk"
    assert result[0]["suggested_amount"] == 2


async def test_workflow_match_products_preview_exact_name():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [{"id": 1, "name": "Whole Milk"}],
        [],
    ]

    result = await workflow_match_products_preview_data(
        client,
        [{"label": "whole milk", "quantity": 1}],
    )

    assert result[0]["status"] == "matched"
    assert result[0]["matched_product_id"] == 1


async def test_workflow_match_products_preview_ambiguous_substring():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [{"id": 1, "name": "Whole Milk"}, {"id": 2, "name": "Oat Milk"}],
        [],
    ]

    result = await workflow_match_products_preview_data(
        client,
        [{"label": "milk", "quantity": 1}],
    )

    assert result[0]["status"] == "ambiguous"
    assert len(result[0]["candidates"]) == 2


async def test_workflow_match_products_preview_unmatched():
    client = AsyncMock()
    client.get_objects.side_effect = [
        [{"id": 1, "name": "Whole Milk"}],
        [],
    ]

    result = await workflow_match_products_preview_data(
        client,
        [{"label": "bananas", "quantity": 1}],
    )

    assert result[0]["status"] == "unmatched"
    assert result[0]["candidates"] == []


async def test_workflow_match_products_preview_rejects_invalid_payload():
    client = AsyncMock()

    with pytest.raises(GrocyValidationError, match="Invalid items\\[0\\]"):
        await workflow_match_products_preview_data(client, [{"label": "", "quantity": 0}])


async def test_workflow_stock_intake_apply_data():
    client = AsyncMock()

    result = await workflow_stock_intake_apply_data(
        client,
        [{"product_id": 12, "amount": 2, "note": "organic"}],
    )

    client.add_stock.assert_awaited_once_with(12, 2)
    assert result["applied_count"] == 1
    assert result["applied_items"][0]["note"] == "organic"


async def test_workflow_shopping_reconcile_preview_data():
    client = AsyncMock()
    client.get_shopping_list.return_value = [
        {"id": 3, "product_id": 12, "amount": 1},
        {"id": 4, "product_id": 12, "amount": 3},
    ]

    result = await workflow_shopping_reconcile_preview_data(
        client,
        [{"product_id": 12, "amount": 2}],
        list_id=1,
    )

    assert result[0]["status"] == "matched"
    assert result[0]["actions"] == [
        {"shopping_item_id": 3, "action": "remove", "previous_amount": 1.0},
        {
            "shopping_item_id": 4,
            "action": "set_amount",
            "previous_amount": 3.0,
            "new_amount": 2.0,
        },
    ]


async def test_workflow_shopping_reconcile_preview_data_partial():
    client = AsyncMock()
    client.get_shopping_list.return_value = [{"id": 5, "product_id": 12, "amount": 1}]

    result = await workflow_shopping_reconcile_preview_data(
        client,
        [{"product_id": 12, "amount": 2}],
        list_id=1,
    )

    assert result[0]["status"] == "partial"
    assert result[0]["unapplied_amount"] == 1


async def test_workflow_shopping_reconcile_apply_data():
    client = AsyncMock()

    result = await workflow_shopping_reconcile_apply_data(
        client,
        [
            {"shopping_item_id": 3, "action": "remove"},
            {"shopping_item_id": 4, "action": "set_amount", "new_amount": 2},
        ],
    )

    client.remove_shopping_list_item.assert_awaited_once_with(3)
    client.update_shopping_list_item.assert_awaited_once_with(4, {"amount": 2.0})
    assert result["applied_count"] == 2


async def test_workflow_shopping_reconcile_preview_actions_pass_straight_to_apply():
    client = AsyncMock()
    client.get_shopping_list.return_value = [
        {"id": 3, "product_id": 12, "amount": 1},
        {"id": 4, "product_id": 12, "amount": 3},
    ]

    preview = await workflow_shopping_reconcile_preview_data(
        client, [{"product_id": 12, "amount": 2}], list_id=1
    )
    result = await workflow_shopping_reconcile_apply_data(client, preview[0]["actions"])

    client.remove_shopping_list_item.assert_awaited_once_with(3)
    client.update_shopping_list_item.assert_awaited_once_with(4, {"amount": 2.0})
    assert result["applied_count"] == 2
    assert all("previous_amount" not in action for action in result["applied_actions"])


async def test_workflow_stock_intake_apply_passes_price_and_options():
    client = AsyncMock()

    result = await workflow_stock_intake_apply_data(
        client,
        [
            {"product_id": 39, "amount": 1, "price": 15.5},
            {
                "product_id": 40,
                "amount": 2,
                "price": 0,
                "best_before_date": "2027-01-31",
                "location_id": 3,
            },
            {"product_id": 41, "amount": 1},
        ],
    )

    assert client.add_stock.await_args_list[0].args == (39, 1.0)
    assert client.add_stock.await_args_list[0].kwargs == {"price": 15.5}
    assert client.add_stock.await_args_list[1].kwargs == {
        "price": 0.0,
        "best_before_date": "2027-01-31",
        "location_id": 3,
    }
    assert client.add_stock.await_args_list[2].kwargs == {}
    assert result["applied_items"][0]["price"] == 15.5


async def test_workflow_stock_intake_apply_rejects_negative_price_and_bad_date():
    client = AsyncMock()
    with pytest.raises(Exception, match="price must not be negative"):
        await workflow_stock_intake_apply_data(
            client, [{"product_id": 1, "amount": 1, "price": -2}]
        )
    with pytest.raises(Exception, match="YYYY-MM-DD"):
        await workflow_stock_intake_apply_data(
            client, [{"product_id": 1, "amount": 1, "best_before_date": "tomorrow"}]
        )
    client.add_stock.assert_not_called()


@pytest.mark.parametrize("value", ["20270131", "2027-W04-7"])
async def test_workflow_stock_intake_apply_rejects_non_strict_dates(value):
    client = AsyncMock()
    with pytest.raises(Exception, match="YYYY-MM-DD"):
        await workflow_stock_intake_apply_data(
            client,
            [
                {"product_id": 1, "amount": 1},
                {"product_id": 2, "amount": 1, "best_before_date": value},
            ],
        )
    client.add_stock.assert_not_called()


async def test_workflow_stock_intake_apply_rejects_non_finite_price_before_any_write():
    client = AsyncMock()
    for bad in ('[{"product_id":1,"amount":1},{"product_id":2,"amount":1,"price":1e400}]',):
        import json

        items = json.loads(bad)
        with pytest.raises(Exception, match="price"):
            await workflow_stock_intake_apply_data(client, items)
    with pytest.raises(Exception, match="price"):
        await workflow_stock_intake_apply_data(
            client,
            [{"product_id": 1, "amount": 1}, {"product_id": 2, "amount": 1, "price": float("nan")}],
        )
    client.add_stock.assert_not_called()


async def test_workflow_stock_intake_apply_passes_purchased_date_and_store():
    client = AsyncMock()
    await workflow_stock_intake_apply_data(
        client,
        [{"product_id": 5, "amount": 1, "purchased_date": "2026-11-07", "shopping_location_id": 2}],
    )
    assert client.add_stock.await_args.kwargs == {
        "purchased_date": "2026-11-07",
        "shopping_location_id": 2,
    }
    with pytest.raises(Exception, match="purchased_date must be formatted"):
        await workflow_stock_intake_apply_data(
            client, [{"product_id": 5, "amount": 1, "purchased_date": "7/11/2026"}]
        )
