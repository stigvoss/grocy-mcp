"""Tests for bulk product reads."""

from unittest.mock import AsyncMock

import pytest

from grocy_mcp.core.products import products_list_data
from grocy_mcp.exceptions import GrocyValidationError


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get_objects.return_value = [
        {"id": 1, "name": "Milk", "userfields": {"bilkatogo_ids": "111,222", "mealieId": "m1"}},
        {"id": 2, "name": "Salt", "userfields": {"bilkatogo_ids": "", "ai_notes": "x"}},
        {"id": 3, "name": "Rice", "userfields": None},
    ]
    return client


async def test_returns_all_products_with_userfields_in_one_request(mock_client):
    result = await products_list_data(mock_client)
    assert len(result) == 3
    assert result[0]["userfields"]["bilkatogo_ids"] == "111,222"
    assert result[2]["userfields"] == {}
    mock_client.get_objects.assert_called_once_with("products")


async def test_where_userfield_set_keeps_only_non_empty(mock_client):
    result = await products_list_data(mock_client, userfields_set=["bilkatogo_ids"])
    assert [p["id"] for p in result] == [1]


async def test_fields_filter_returns_only_requested_keys(mock_client):
    result = await products_list_data(
        mock_client, fields=["id", "name", "userfields.bilkatogo_ids"]
    )
    assert result[0] == {"id": 1, "name": "Milk", "userfields": {"bilkatogo_ids": "111,222"}}
    assert set(result[1]) == {"id", "name", "userfields"}


async def test_invalid_fields_rejected(mock_client):
    with pytest.raises(GrocyValidationError):
        await products_list_data(mock_client, fields=[""])
