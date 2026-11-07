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


@pytest.fixture
def userfield_client():
    client = AsyncMock()
    client.get_objects.return_value = [
        {
            "id": 1,
            "name": "Beef",
            "userfields": {
                "bilkatogo_ids": "19753,41377,183283",
                "bilkatogo": "https://x/search?query=hakket%20oksek%C3%B8d",
                "ai_notes": "Freeze on arrival",
            },
        },
        {"id": 2, "name": "Skyr", "userfields": {"bilkatogo_ids": "19856, 84678"}},
        {
            "id": 3,
            "name": "Pork",
            "userfields": {"bilkatogo_ids": "119753", "ai_notes": "svinekød"},
        },
        {"id": 4, "name": "Plain", "userfields": None},
    ]
    return client


async def test_userfields_match_is_a_trimmed_token_not_a_substring(userfield_client):
    ids = lambda r: [p["id"] for p in r]
    assert ids(
        await products_list_data(userfield_client, userfields_match={"bilkatogo_ids": "19753"})
    ) == [1]
    assert ids(
        await products_list_data(userfield_client, userfields_match={"bilkatogo_ids": "84678"})
    ) == [2]
    assert ids(
        await products_list_data(userfield_client, userfields_match={"bilkatogo_ids": " 119753 "})
    ) == [3]
    assert (
        await products_list_data(userfield_client, userfields_match={"bilkatogo_ids": "9753"}) == []
    )


async def test_userfields_contains_matches_substring_and_url_decoded_text(userfield_client):
    ids = lambda r: [p["id"] for p in r]
    assert ids(
        await products_list_data(
            userfield_client, userfields_contains={"bilkatogo": "hakket oksekød"}
        )
    ) == [1]
    assert ids(
        await products_list_data(userfield_client, userfields_contains={"ai_notes": "FREEZE"})
    ) == [1]
    assert ids(
        await products_list_data(userfield_client, userfields_contains={"bilkatogo_ids": "9753"})
    ) == [1, 3]


async def test_userfield_filters_combine_and_validate(userfield_client):
    both = await products_list_data(
        userfield_client,
        userfields_match={"bilkatogo_ids": "19753"},
        userfields_contains={"ai_notes": "freeze"},
        fields=["id"],
    )
    assert both == [{"id": 1}]
    for bad in ({"bilkatogo_ids": ""}, {"": 5}, "x"):
        with pytest.raises(GrocyValidationError):
            await products_list_data(userfield_client, userfields_match=bad)


def test_userfield_contains_lowercases_after_url_decoding():
    from grocy_mcp.core.products import userfield_contains

    assert userfield_contains("https://x/?query=OKSEK%C3%98D", "oksekød")
    assert userfield_contains("https://x/?query=hakket%20OKSEK%C3%98D", "HAKKET oksekØd")
    assert userfield_contains("OKSEK%c3%98d", "oksekød")
    assert not userfield_contains("https://x/?query=mælk", "oksekød")


async def test_encoded_uppercase_is_found_by_both_search_paths(userfield_client):
    userfield_client.get_objects.return_value = [
        {"id": 9, "name": "Beef", "userfields": {"bilkatogo": "https://x/?query=OKSEK%C3%98D"}}
    ]
    found = await products_list_data(userfield_client, userfields_contains={"bilkatogo": "oksekød"})
    assert [p["id"] for p in found] == [9]


async def test_userfield_filters_treat_numeric_zero_as_a_value():
    from grocy_mcp.core.products import userfield_tokens

    client = AsyncMock()
    client.get_objects.return_value = [
        {"id": 1, "name": "Zero", "userfields": {"code": 0}},
        {"id": 2, "name": "One", "userfields": {"code": 1}},
        {"id": 3, "name": "Unset", "userfields": {"code": None}},
        {"id": 4, "name": "Flag off", "userfields": {"code": False}},
    ]
    assert userfield_tokens(0) == ["0"] and userfield_tokens(None) == []
    matched = await products_list_data(client, userfields_match={"code": "0"})
    assert [p["id"] for p in matched] == [1]
    contained = await products_list_data(client, userfields_contains={"code": "0"})
    assert [p["id"] for p in contained] == [1]
