"""Tests for GrocyClient."""

import json

import httpx
import pytest

from grocy_mcp.client import GrocyClient
from grocy_mcp.exceptions import (
    GrocyAuthError,
    GrocyNotFoundError,
    GrocyServerError,
    GrocyValidationError,
)


@pytest.fixture
async def client(base_url, api_key, mock_api):
    async with GrocyClient(base_url, api_key) as c:
        yield c


async def test_get_objects(client, mock_api):
    mock_api.get("/objects/products").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "Milk"}])
    )
    result = await client.get_objects("products")
    assert result == [{"id": 1, "name": "Milk"}]


async def test_get_object(client, mock_api):
    mock_api.get("/objects/products/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Milk"})
    )
    result = await client.get_object("products", 1)
    assert result == {"id": 1, "name": "Milk"}


async def test_create_object(client, mock_api):
    mock_api.post("/objects/products").mock(
        return_value=httpx.Response(200, json={"created_object_id": 5})
    )
    result = await client.create_object("products", {"name": "Bread"})
    assert result == 5


async def test_delete_object(client, mock_api):
    mock_api.delete("/objects/products/1").mock(return_value=httpx.Response(204))
    await client.delete_object("products", 1)


async def test_update_userfields(client, mock_api):
    route = mock_api.put("/userfields/products/87").mock(return_value=httpx.Response(204))
    await client.update_userfields("products", 87, {"ai_notes": "Prefer paprika"})
    assert route.calls.last.request.read() == b'{"ai_notes":"Prefer paprika"}'


async def test_update_userfields_not_found(client, mock_api):
    mock_api.put("/userfields/products/87").mock(return_value=httpx.Response(404))
    with pytest.raises(GrocyNotFoundError):
        await client.update_userfields("products", 87, {"ai_notes": "x"})


async def test_get_stock(client, mock_api):
    mock_api.get("/stock").mock(
        return_value=httpx.Response(200, json=[{"product_id": 1, "amount": 3}])
    )
    result = await client.get_stock()
    assert len(result) == 1


async def test_add_stock(client, mock_api):
    mock_api.post("/stock/products/1/add").mock(return_value=httpx.Response(200, json=[{"id": 10}]))
    result = await client.add_stock(1, 2.0)
    assert result is not None


async def test_consume_stock(client, mock_api):
    mock_api.post("/stock/products/1/consume").mock(
        return_value=httpx.Response(200, json=[{"id": 10}])
    )
    await client.consume_stock(1, 1.0)


async def test_get_volatile_stock(client, mock_api):
    mock_api.get("/stock/volatile").mock(
        return_value=httpx.Response(
            200,
            json={
                "expiring_products": [],
                "expired_products": [],
                "missing_products": [],
                "overdue_products": [],
            },
        )
    )
    result = await client.get_volatile_stock()
    assert "expiring_products" in result


async def test_auth_error(client, mock_api):
    mock_api.get("/objects/products").mock(return_value=httpx.Response(401))
    with pytest.raises(GrocyAuthError):
        await client.get_objects("products")


async def test_validation_error(client, mock_api):
    mock_api.post("/objects/products").mock(
        return_value=httpx.Response(400, json={"error_message": "bad"})
    )
    with pytest.raises(GrocyValidationError):
        await client.create_object("products", {})


async def test_not_found_error(client, mock_api):
    mock_api.get("/objects/products/999").mock(return_value=httpx.Response(404))
    with pytest.raises(GrocyNotFoundError):
        await client.get_object("products", 999)


async def test_server_error(client, mock_api):
    mock_api.get("/stock").mock(return_value=httpx.Response(500))
    with pytest.raises(GrocyServerError):
        await client.get_stock()


async def test_retry_on_502(client, mock_api):
    route = mock_api.get("/stock")
    route.side_effect = [
        httpx.Response(502),
        httpx.Response(200, json=[]),
    ]
    result = await client.get_stock()
    assert result == []
    assert route.call_count == 2


async def test_auth_header(client, mock_api, api_key):
    mock_api.get("/objects/products").mock(return_value=httpx.Response(200, json=[]))
    await client.get_objects("products")
    request = mock_api.calls[0].request
    assert request.headers["GROCY-API-KEY"] == api_key


# --------------------------------------------------------- Retry and transport


async def test_retry_on_503(client, mock_api):
    """503 should also trigger retry."""
    route = mock_api.get("/stock")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json=[{"product_id": 1}]),
    ]
    result = await client.get_stock()
    assert result == [{"product_id": 1}]
    assert route.call_count == 2


async def test_retry_on_504(client, mock_api):
    """504 should also trigger retry."""
    route = mock_api.get("/stock")
    route.side_effect = [
        httpx.Response(504),
        httpx.Response(200, json=[]),
    ]
    result = await client.get_stock()
    assert result == []


async def test_retry_exhaustion_raises(client, mock_api):
    """All retries returning 502 should raise GrocyServerError."""
    route = mock_api.get("/stock")
    route.side_effect = [
        httpx.Response(502),
        httpx.Response(502),
        httpx.Response(502),
    ]
    with pytest.raises(GrocyServerError):
        await client.get_stock()
    assert route.call_count == 3  # initial + 2 retries


async def test_transport_error_retries(client, mock_api):
    """Transport errors should be retried."""
    route = mock_api.get("/stock")
    route.side_effect = [
        httpx.ConnectError("connection refused"),
        httpx.Response(200, json=[]),
    ]
    result = await client.get_stock()
    assert result == []


async def test_transport_error_exhaustion(client, mock_api):
    """Persistent transport errors should raise GrocyServerError."""
    route = mock_api.get("/stock")
    route.side_effect = [
        httpx.ConnectError("refused"),
        httpx.ConnectError("refused"),
        httpx.ConnectError("refused"),
    ]
    with pytest.raises(GrocyServerError, match="Connection failed"):
        await client.get_stock()


async def test_403_raises_auth_error(client, mock_api):
    """403 should map to GrocyAuthError like 401."""
    mock_api.get("/stock").mock(return_value=httpx.Response(403))
    with pytest.raises(GrocyAuthError):
        await client.get_stock()


async def test_non_transient_error_no_retry(client, mock_api):
    """400/404 errors should not be retried."""
    route = mock_api.post("/objects/products")
    route.mock(return_value=httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(GrocyValidationError):
        await client.create_object("products", {})
    assert route.call_count == 1  # no retry


async def test_url_trailing_slash_normalization(base_url, api_key):
    """URL with trailing slash should be normalized."""
    client = GrocyClient(base_url + "/", api_key)
    assert client._base == base_url + "/api"
    await client._client.aclose()


async def test_transfer_stock_sends_from_and_to_location(client, mock_api):
    route = mock_api.post("/stock/products/6/transfer").mock(
        return_value=httpx.Response(200, json=[{"id": 28}])
    )
    await client.transfer_stock(6, 2.0, to_location_id=2, from_location_id=3)
    assert json.loads(route.calls.last.request.content) == {
        "amount": 2.0,
        "location_id_to": 2,
        "location_id_from": 3,
    }


async def test_transfer_stock_without_from_location_omits_it(client, mock_api):
    route = mock_api.post("/stock/products/6/transfer").mock(
        return_value=httpx.Response(200, json=[])
    )
    await client.transfer_stock(6, 1.0, to_location_id=2)
    assert "location_id_from" not in json.loads(route.calls.last.request.content)


async def test_get_stock_locations(client, mock_api):
    mock_api.get("/stock/products/6/locations").mock(
        return_value=httpx.Response(
            200, json=[{"location_id": 3, "location_name": "Pantry", "amount": 3}]
        )
    )
    assert (await client.get_stock_locations(6))[0]["location_name"] == "Pantry"


async def test_update_stock_entry_and_undo_booking(client, mock_api):
    put = mock_api.put("/stock/entry/24").mock(return_value=httpx.Response(200, json=[{"id": 5}]))
    undo = mock_api.post("/stock/bookings/17/undo").mock(return_value=httpx.Response(204))
    await client.update_stock_entry(24, {"amount": 2, "price": 1.5})
    await client.undo_booking(17)
    assert json.loads(put.calls.last.request.content) == {"amount": 2, "price": 1.5}
    assert undo.called


async def test_add_shopping_list_item_without_product_sends_no_product_id(client, mock_api):
    route = mock_api.post("/objects/shopping_list").mock(
        return_value=httpx.Response(200, json={"created_object_id": "9"})
    )
    assert await client.add_shopping_list_item(None, 1, 1, "Spinat") == "9"
    assert json.loads(route.calls.last.request.content) == {
        "amount": 1,
        "shopping_list_id": 1,
        "note": "Spinat",
    }


async def test_get_stock_entry_null_response_is_not_found(client, mock_api):
    mock_api.get("/stock/entry/999").mock(return_value=httpx.Response(200, content=b"null"))
    with pytest.raises(GrocyNotFoundError, match="may have been consumed"):
        await client.get_stock_entry(999)


async def test_unreadable_json_becomes_a_grocy_server_error(client, mock_api):
    mock_api.get("/stock").mock(return_value=httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(GrocyServerError, match="unreadable response to GET /api/stock"):
        await client.get_stock()


async def test_inventory_then_unreadable_details_reports_a_partial_not_a_crash(client, mock_api):
    from grocy_mcp.core.stock import stock_inventory_outcome

    mock_api.get("/stock/products/1").mock(
        side_effect=[
            httpx.Response(200, json={"stock_amount": 3, "stock_amount_opened": 0}),
            httpx.Response(200, text="<html>gateway hiccup</html>"),
        ]
    )
    write = mock_api.post("/stock/products/1/inventory").mock(
        return_value=httpx.Response(200, json=[{"id": 1}])
    )
    outcome = await stock_inventory_outcome(client, "1", 2.0)
    assert write.called
    assert outcome.ok is False and outcome.partial is True
    assert "stock set to 2" in outcome.message and "unreadable response" in outcome.message


async def test_unreadable_json_before_any_write_is_an_ordinary_grocy_error(client, mock_api):
    from grocy_mcp.core.stock import stock_inventory_outcome

    mock_api.get("/stock/products/1").mock(return_value=httpx.Response(200, text="oops"))
    # no inventory route is registered: respx would fail the test if a write were attempted
    with pytest.raises(GrocyServerError):
        await stock_inventory_outcome(client, "1", 2.0)


@pytest.mark.parametrize(
    "call, route",
    [
        (lambda c: c.add_stock(1, 2.0), ("post", "/stock/products/1/add")),
        (lambda c: c.consume_stock(1, 1.0), ("post", "/stock/products/1/consume")),
        (lambda c: c.transfer_stock(1, 1.0, 2, 3), ("post", "/stock/products/1/transfer")),
        (lambda c: c.inventory_stock(1, 2.0), ("post", "/stock/products/1/inventory")),
        (lambda c: c.open_stock(1, 1.0), ("post", "/stock/products/1/open")),
        (lambda c: c.update_stock_entry(24, {"amount": 1}), ("put", "/stock/entry/24")),
    ],
)
async def test_acknowledged_stock_writes_survive_an_unreadable_body(client, mock_api, call, route):
    method, path = route
    sent = getattr(mock_api, method)(path).mock(
        return_value=httpx.Response(200, text="<html>gateway</html>")
    )
    assert await call(client) is None  # applied; nothing to report, nothing to retry
    assert sent.called


async def test_reads_and_create_still_require_a_readable_body(client, mock_api):
    mock_api.get("/stock/products/1/locations").mock(return_value=httpx.Response(200, text="x"))
    mock_api.post("/objects/products").mock(return_value=httpx.Response(200, text="x"))
    with pytest.raises(GrocyServerError):
        await client.get_stock_locations(1)
    with pytest.raises(GrocyServerError):  # the new id is needed, so this one stays strict
        await client.create_object("products", {"name": "x"})


async def test_acknowledged_inventory_with_unreadable_body_is_recorded_as_applied(client, mock_api):
    from grocy_mcp.core.stock import stock_inventory_outcome

    mock_api.get("/stock/products/1").mock(
        side_effect=[
            httpx.Response(200, json={"stock_amount": 3, "stock_amount_opened": 0}),
            httpx.Response(200, json={"stock_amount": 2, "stock_amount_opened": 0}),
        ]
    )
    mock_api.post("/stock/products/1/inventory").mock(
        return_value=httpx.Response(200, text="<html>no json</html>")
    )
    outcome = await stock_inventory_outcome(client, "1", 2.0)
    assert outcome.ok is True and "Inventory updated" in outcome.message


async def test_batch_does_not_report_an_applied_consume_as_failed(client, mock_api):
    from grocy_mcp.core.workflows import workflow_stock_apply_data

    consume = mock_api.post("/stock/products/1/consume").mock(
        return_value=httpx.Response(200, text="<html>no json</html>")
    )
    result = await workflow_stock_apply_data(
        client, [{"action": "consume", "product": "1", "amount": 1}]
    )
    assert consume.call_count == 1
    assert result["results"][0]["ok"] is True and result["applied_count"] == 1
