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


@pytest.fixture
def create_client():
    from grocy_mcp.core import products as products_module  # noqa: F401

    client = AsyncMock()

    async def get_objects(entity, query=None):
        return {
            "quantity_units": [{"id": 2, "name": "Piece"}, {"id": 3, "name": "Pack"}],
            "locations": [{"id": 2, "name": "Fridge"}, {"id": 4, "name": "Freezer"}],
            "product_groups": [{"id": 9, "name": "Dairy"}],
            "products": [
                {"id": 1, "name": "Minced beef, frozen 200g"},
                {"id": 2, "name": "Whole milk"},
            ],
        }[entity]

    client.get_objects.side_effect = get_objects
    client.create_object.return_value = 77
    return client


async def test_product_create_validates_and_creates_with_all_fields(create_client):
    from grocy_mcp.core.products import product_create_data

    result = await product_create_data(
        create_client,
        "  Skyr,   natural ",
        "pack",
        "Freezer",
        product_group="Dairy",
        default_best_before_days=14,
        min_stock_amount=2,
        userfields={"bilkatogo_ids": "19753", "high_churn": 1},
    )
    create_client.create_object.assert_called_once_with(
        "products",
        {
            "name": "Skyr, natural",
            "location_id": 4,
            "qu_id_stock": 3,
            "qu_id_purchase": 3,
            "qu_id_consume": 3,
            "qu_id_price": 3,
            "product_group_id": 9,
            "default_best_before_days": 14,
            "min_stock_amount": 2,
        },
    )
    create_client.update_userfields.assert_called_once_with(
        "products", 77, {"bilkatogo_ids": "19753", "high_churn": 1}
    )
    assert result == {
        "created": True,
        "product_id": 77,
        "name": "Skyr, natural",
        "stock_unit": "Pack",
        "location": "Freezer",
        "product_group": "Dairy",
        "userfields_set": ["bilkatogo_ids", "high_churn"],
    }


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        (
            {"stock_unit": "Litre", "location": "Fridge"},
            r"Unknown stock unit 'Litre'.*Piece \(2\), Pack \(3\)",
        ),
        (
            {"stock_unit": "Pack", "location": "Cellar"},
            r"Unknown location 'Cellar'.*Fridge \(2\), Freezer \(4\)",
        ),
        (
            {"stock_unit": "Pack", "location": "2", "product_group": "Meat"},
            r"Unknown product group 'Meat'.*Dairy \(9\)",
        ),
    ],
)
async def test_product_create_unknown_references_list_valid_values(create_client, kwargs, expected):
    from grocy_mcp.core.products import product_create_data

    with pytest.raises(GrocyValidationError, match=expected):
        await product_create_data(create_client, "New thing", **kwargs)
    create_client.create_object.assert_not_called()


@pytest.mark.parametrize(
    "name, reason",
    [
        ("frozen 200g Minced beef", "same name"),
        ("MINCED BEEF frozen 200G", "same name"),
        ("Milk whole", "same name"),
        ("Whole milks", "very similar"),
        ("Minced beaf frozen 200g", "very similar"),
    ],
)
async def test_product_create_flags_near_duplicates_and_force_overrides(
    create_client, name, reason
):
    from grocy_mcp.core.products import product_create_data

    result = await product_create_data(create_client, name, "Pack", "Fridge")
    assert result["created"] is False
    assert reason in result["duplicates"][0]["reason"]
    create_client.create_object.assert_not_called()

    forced = await product_create_data(create_client, name, "Pack", "Fridge", force=True)
    assert forced["created"] is True


async def test_product_create_does_not_flag_different_products(create_client):
    from grocy_mcp.core.products import product_create_data

    result = await product_create_data(create_client, "Milk chocolate", "Pack", "Fridge")
    assert result["created"] is True


async def test_product_create_userfield_failure_keeps_the_product_and_warns(create_client):
    from grocy_mcp.core.products import product_create_data

    create_client.update_userfields.side_effect = GrocyValidationError("no such field")
    result = await product_create_data(
        create_client, "Butter", "Pack", "Fridge", userfields={"nope": "x"}
    )
    assert result["created"] is True and "userfields_set_tool" in result["warning"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "  "},
        {"name": "X", "min_stock_amount": -1},
        {"name": "X", "min_stock_amount": float("nan")},
        {"name": "X", "default_best_before_days": -5},
        {"name": "X", "userfields": ["a"]},
    ],
)
async def test_product_create_validates_inputs_before_any_request(create_client, kwargs):
    from grocy_mcp.core.products import product_create_data

    with pytest.raises(GrocyValidationError):
        await product_create_data(create_client, stock_unit="Pack", location="Fridge", **kwargs)
    create_client.get_objects.assert_not_called()
    create_client.create_object.assert_not_called()


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


@pytest.mark.parametrize(
    "name",
    ["Minced veef", "veef Minced", "MINCED BEEFF", "Mincd beef"],
)
async def test_product_create_flags_a_typo_wherever_it_sorts(name):
    from grocy_mcp.core.products import find_near_duplicates

    found = find_near_duplicates(name, [{"id": 1, "name": "Minced beef"}])
    assert [f["product_id"] for f in found] == [1]


@pytest.mark.parametrize("name", ["Minced chicken", "Beef", "Milk", "Minced beef stew"])
async def test_product_create_does_not_flag_clearly_different_names(name):
    from grocy_mcp.core.products import find_near_duplicates

    assert find_near_duplicates(name, [{"id": 1, "name": "Minced beef"}]) == []


@pytest.mark.parametrize("failure", ["GrocyNotFoundError", "GrocyServerError", "GrocyAuthError"])
async def test_product_create_keeps_the_new_id_when_the_userfield_request_fails(
    create_client, failure
):
    from grocy_mcp import exceptions
    from grocy_mcp.core.products import product_create_data

    create_client.update_userfields.side_effect = getattr(exceptions, failure)("boom")
    result = await product_create_data(
        create_client, "Butter", "Pack", "Fridge", userfields={"ai_notes": "x"}
    )
    assert result["created"] is True and result["product_id"] == 77
    assert "77" in result["warning"] and "userfields_set_tool" in result["warning"]
    assert "userfields_set" not in result


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


@pytest.mark.parametrize(
    "name", ["Pepper, whole while", "Pepper, while whole", "while Pepper whole"]
)
async def test_duplicate_matching_does_not_depend_on_word_order(name):
    from grocy_mcp.core.products import find_near_duplicates

    found = find_near_duplicates(name, [{"id": 1, "name": "Pepper, whole white"}])
    assert [f["product_id"] for f in found] == [1]


async def test_duplicate_matching_long_names_still_work():
    from grocy_mcp.core.products import find_near_duplicates

    existing = "alpha bravo charlie delta echo foxtrot golf hotel india"
    typo = "alpha bravo charlie delta echo foxtrot golf hotel indla"
    assert find_near_duplicates(typo, [{"id": 1, "name": existing}])
    assert not find_near_duplicates(
        "one two three four five six seven eight nine", [{"id": 1, "name": existing}]
    )


async def test_an_id_wins_over_a_name_that_looks_like_it(create_client):
    from grocy_mcp.core.products import product_create_data

    async def get_objects(entity, query=None):
        return {
            "quantity_units": [{"id": 2, "name": "4"}, {"id": 4, "name": "Pack"}],
            "locations": [{"id": 2, "name": "4"}, {"id": 4, "name": "Freezer"}],
            "product_groups": [{"id": 3, "name": "7"}, {"id": 7, "name": "Dairy"}],
            "products": [],
        }[entity]

    create_client.get_objects.side_effect = get_objects
    result = await product_create_data(
        create_client, "New thing", stock_unit="4", location="4", product_group="7"
    )
    data = create_client.create_object.call_args.args[1]
    assert data["qu_id_stock"] == 4 and data["location_id"] == 4 and data["product_group_id"] == 7
    assert result["stock_unit"] == "Pack" and result["location"] == "Freezer"
    # a name still resolves when it is not also an ID
    await product_create_data(
        create_client, "Other", stock_unit="pack", location="freezer", force=True
    )
    assert create_client.create_object.call_args.args[1]["qu_id_stock"] == 4
