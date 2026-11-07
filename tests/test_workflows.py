"""Tests for workflow-oriented preview/apply helpers."""

from unittest.mock import AsyncMock, patch

import pytest

from grocy_mcp.core.stock import StockOutcome
from grocy_mcp.core.workflows import (
    workflow_match_products_preview_data,
    workflow_shopping_reconcile_apply_data,
    workflow_shopping_reconcile_preview_data,
    workflow_stock_apply_data,
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


async def test_workflow_stock_apply_runs_every_action_and_reports_each():
    client = AsyncMock()
    with (
        patch("grocy_mcp.core.stock.stock_consume", AsyncMock(return_value="Consumed")) as consume,
        patch(
            "grocy_mcp.core.stock.stock_open_outcome",
            AsyncMock(return_value=StockOutcome(True, "Opened")),
        ) as open_,
        patch(
            "grocy_mcp.core.stock.stock_inventory_outcome",
            AsyncMock(return_value=StockOutcome(True, "Inv")),
        ) as inv,
        patch("grocy_mcp.core.stock.stock_transfer", AsyncMock(return_value="Moved")) as transfer,
    ):
        result = await workflow_stock_apply_data(
            client,
            [
                {"action": "consume", "product": "Milk", "amount": 1, "from_location": "Freezer"},
                {"action": "open", "product": 7},
                {"action": "inventory", "product": "Eggs", "new_amount": 2, "opened_amount": 1},
                {"action": "transfer", "product": "Beef", "amount": 1, "to_location": "Freezer"},
            ],
        )
    consume.assert_awaited_once_with(client, "Milk", 1.0, "Freezer", False)
    open_.assert_awaited_once_with(client, "7", 1.0)
    inv.assert_awaited_once_with(client, "Eggs", 2.0, 1.0)
    transfer.assert_awaited_once_with(client, "Beef", 1.0, "Freezer", None)
    assert result["applied_count"] == 4 and result["failed_count"] == 0
    assert [r["ok"] for r in result["results"]] == [True] * 4


async def test_workflow_stock_apply_failing_action_does_not_abort_the_rest():
    from grocy_mcp.exceptions import GrocyValidationError

    client = AsyncMock()
    with (
        patch(
            "grocy_mcp.core.stock.stock_consume",
            AsyncMock(side_effect=[GrocyValidationError("holds 0"), "Consumed"]),
        ),
        patch(
            "grocy_mcp.core.stock.stock_open_outcome",
            AsyncMock(return_value=StockOutcome(True, "Opened")),
        ),
    ):
        result = await workflow_stock_apply_data(
            client,
            [
                {"action": "consume", "product": "A", "amount": 1},
                {"action": "open", "product": "B"},
                {"action": "consume", "product": "C", "amount": 1},
            ],
        )
    assert result["applied_count"] == 2 and result["failed_count"] == 1
    assert [r["ok"] for r in result["results"]] == [False, True, True]
    assert result["results"][0]["error"] == "holds 0"


async def test_workflow_stock_apply_invalid_items_are_reported_by_index():
    client = AsyncMock()
    with patch(
        "grocy_mcp.core.stock.stock_open_outcome",
        AsyncMock(return_value=StockOutcome(True, "Opened")),
    ) as open_:
        result = await workflow_stock_apply_data(
            client,
            [
                {"action": "consume", "product": "Milk", "amount": -1},
                {"action": "fly", "product": "Milk"},
                {"action": "open", "product": "Milk", "color": "red"},
                "not an object",
                {"action": "open", "product": "Milk"},
            ],
        )
    open_.assert_awaited_once()
    assert [r["ok"] for r in result["results"]] == [False, False, False, False, True]
    assert "actions[0]" in result["results"][0]["error"]
    assert result["applied_count"] == 1 and result["failed_count"] == 4


async def test_workflow_stock_apply_rejects_non_array_and_too_many_actions():
    client = AsyncMock()
    with pytest.raises(GrocyValidationError, match="expected a JSON array"):
        await workflow_stock_apply_data(client, {"action": "open"})
    with pytest.raises(GrocyValidationError, match="at most 100"):
        await workflow_stock_apply_data(client, [{"action": "open", "product": "x"}] * 101)


async def test_workflow_stock_apply_text_summary():
    from grocy_mcp.core.workflows import workflow_stock_apply

    client = AsyncMock()
    with patch(
        "grocy_mcp.core.stock.stock_open_outcome",
        AsyncMock(return_value=StockOutcome(True, "Opened 1 of 'Milk'.")),
    ):
        text = await workflow_stock_apply(client, [{"action": "open", "product": "Milk"}])
    assert "1 applied, 0 failed" in text and "[0] open Milk: ok" in text


async def test_workflow_stock_apply_strips_grocy_json_wrapper_and_names_unknown_actions():
    from grocy_mcp.exceptions import GrocyValidationError

    client = AsyncMock()
    wrapped = GrocyValidationError(
        'Validation error: {"error_message":"Amount to be consumed cannot be > current stock"}'
    )
    with patch("grocy_mcp.core.stock.stock_consume", AsyncMock(side_effect=wrapped)):
        result = await workflow_stock_apply_data(
            client,
            [
                {"action": "consume", "product": "A", "amount": 9},
                {"action": "explode", "product": "A"},
                {"product": "A"},
            ],
        )
    assert result["results"][0]["error"] == "Amount to be consumed cannot be > current stock"
    assert "unknown action 'explode'" in result["results"][1]["error"]
    assert "consume, open, inventory, transfer" in result["results"][1]["error"]
    assert "unknown action None" in result["results"][2]["error"]


async def test_workflow_stock_apply_refused_open_is_not_reported_as_applied():
    client = AsyncMock()
    client.get_stock_product.return_value = {
        "product": {"name": "Milk"},
        "stock_amount": 1,
        "stock_amount_opened": 1,
    }
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(client, [{"action": "open", "product": "Milk"}])
    client.open_stock.assert_not_called()
    assert result["applied_count"] == 0 and result["failed_count"] == 1
    assert result["results"][0]["ok"] is False
    assert "Cannot open 1 of 'Milk'" in result["results"][0]["error"]


async def test_workflow_stock_apply_grocy_rejected_open_is_a_failure():
    client = AsyncMock()
    client.get_stock_product.return_value = {
        "product": {"name": "Milk"},
        "stock_amount": 2,
        "stock_amount_opened": 0,
    }
    client.open_stock.side_effect = GrocyValidationError("Validation error: no")
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(client, [{"action": "open", "product": "Milk"}])
    assert result["results"][0]["ok"] is False and result["failed_count"] == 1


async def test_workflow_stock_apply_incomplete_inventory_is_partial_not_applied():
    client = AsyncMock()
    # total adjusted 3 -> 2, but opening the missing unit fails: the total change is kept
    client.get_stock_product.side_effect = [
        {"stock_amount": 3, "stock_amount_opened": 1},
        {"stock_amount": 2, "stock_amount_opened": 0},
        {"stock_amount": 2, "stock_amount_opened": 0},
    ]
    client.open_stock.side_effect = GrocyValidationError("Validation error: no")
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(
            client,
            [{"action": "inventory", "product": "Milk", "new_amount": 2, "opened_amount": 1}],
        )
    client.inventory_stock.assert_awaited_once()
    entry = result["results"][0]
    assert entry["ok"] is False and entry["partial"] is True
    assert "inventory was applied" in entry["error"] and "unopened 2, opened 0" in entry["error"]
    assert result["applied_count"] == 0 and result["failed_count"] == 1


async def test_workflow_stock_apply_inventory_that_cannot_unopen_is_partial():
    client = AsyncMock()
    client.get_stock_product.side_effect = [
        {"stock_amount": 3, "stock_amount_opened": 2},
        {"stock_amount": 2, "stock_amount_opened": 2},
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(
            client,
            [{"action": "inventory", "product": "Milk", "new_amount": 2, "opened_amount": 1}],
        )
    assert result["results"][0]["ok"] is False and result["results"][0]["partial"] is True
    assert "cannot un-open" in result["results"][0]["error"]


async def test_workflow_stock_apply_complete_inventory_is_ok():
    client = AsyncMock()
    client.get_stock_product.side_effect = [
        {"stock_amount": 3, "stock_amount_opened": 0},
        {"stock_amount": 2, "stock_amount_opened": 0},
        {"stock_amount": 2, "stock_amount_opened": 1},
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(
            client,
            [{"action": "inventory", "product": "Milk", "new_amount": 2, "opened_amount": 1}],
        )
    assert result["results"][0]["ok"] is True and "partial" not in result["results"][0]
    assert result["applied_count"] == 1


async def test_workflow_stock_apply_unreachable_opened_amount_without_a_write_is_not_partial():
    client = AsyncMock()
    # the total already matches, so nothing is written; two units are already open
    client.get_stock_product.return_value = {"stock_amount": 2, "stock_amount_opened": 2}
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(
            client,
            [{"action": "inventory", "product": "Milk", "new_amount": 2, "opened_amount": 1}],
        )
    client.inventory_stock.assert_not_called()
    entry = result["results"][0]
    assert entry["ok"] is False and "partial" not in entry
    assert "cannot un-open" in entry["error"]


async def test_workflow_stock_apply_error_after_a_write_keeps_the_confirmed_change():
    from grocy_mcp.exceptions import GrocyServerError

    client = AsyncMock()
    client.get_stock_product.side_effect = [
        {"stock_amount": 3, "stock_amount_opened": 0},
        GrocyServerError("Server error (500): down"),  # the read after the inventory fails
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(
            client, [{"action": "inventory", "product": "Milk", "new_amount": 2}]
        )
    client.inventory_stock.assert_awaited_once()
    entry = result["results"][0]
    assert entry["ok"] is False and entry["partial"] is True
    assert "stock set to 2" in entry["error"] and "partly applied" in entry["error"]
    assert result["applied_count"] == 0 and result["failed_count"] == 1


async def test_workflow_stock_apply_error_before_any_write_is_an_ordinary_failure():
    from grocy_mcp.exceptions import GrocyServerError

    client = AsyncMock()
    client.get_stock_product.side_effect = GrocyServerError("Server error (500): down")
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(
            client, [{"action": "inventory", "product": "Milk", "new_amount": 2}]
        )
    client.inventory_stock.assert_not_called()
    entry = result["results"][0]
    assert entry["ok"] is False and "partial" not in entry
    assert "down" in entry["error"]


async def test_workflow_stock_apply_error_after_opening_reports_what_was_opened():
    from grocy_mcp.exceptions import GrocyServerError

    client = AsyncMock()
    client.get_stock_product.side_effect = [
        {"stock_amount": 2, "stock_amount_opened": 0},
        {"stock_amount": 2, "stock_amount_opened": 0},
        GrocyServerError("Server error (500): down"),  # re-read after opening fails
    ]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(
            client,
            [{"action": "inventory", "product": "Milk", "new_amount": 2, "opened_amount": 1}],
        )
    entry = result["results"][0]
    assert entry["partial"] is True and "1 opened" in entry["error"]


async def test_inventory_float_residue_in_the_opened_count_is_not_a_failure():
    client = AsyncMock()
    # 1.0000000000000007 opened is, to Grocy, exactly the requested 1: nothing to open or refuse
    client.get_stock_product.return_value = {
        "stock_amount": 2,
        "stock_amount_opened": 1.0000000000000007,
    }
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(
            client,
            [{"action": "inventory", "product": "Milk", "new_amount": 2, "opened_amount": 1}],
        )
    client.inventory_stock.assert_not_called()
    client.open_stock.assert_not_called()
    assert result["results"][0]["ok"] is True and result["applied_count"] == 1


async def test_inventory_residue_below_the_requested_opened_count_does_not_trigger_an_open():
    client = AsyncMock()
    client.get_stock_product.return_value = {
        "stock_amount": 2,
        "stock_amount_opened": 0.9999999999999999,
    }
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(
            client,
            [{"action": "inventory", "product": "Milk", "new_amount": 2, "opened_amount": 1}],
        )
    client.open_stock.assert_not_called()
    assert result["results"][0]["ok"] is True


async def test_inventory_residue_in_the_total_does_not_cause_a_needless_inventory():
    client = AsyncMock()
    client.get_stock_product.return_value = {
        "stock_amount": 2.0000000000000004,
        "stock_amount_opened": 0,
    }
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        await workflow_stock_apply_data(
            client, [{"action": "inventory", "product": "Milk", "new_amount": 2}]
        )
    client.inventory_stock.assert_not_called()  # Grocy would reject an inventory equal to stock


async def test_open_with_residue_in_the_unopened_amount_is_allowed():
    client = AsyncMock()
    client.get_stock_product.return_value = {
        "product": {"name": "Milk"},
        "stock_amount": 1,
        "stock_amount_opened": 1.1102230246251565e-16,
    }
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await workflow_stock_apply_data(client, [{"action": "open", "product": "Milk"}])
    client.open_stock.assert_awaited_once()
    assert result["results"][0]["ok"] is True
