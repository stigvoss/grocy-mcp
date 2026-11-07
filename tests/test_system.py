"""Tests for the system core module."""

from unittest.mock import AsyncMock

import pytest

from grocy_mcp.core.system import entity_list, entity_manage, system_info, userfields_set
from grocy_mcp.exceptions import GrocyValidationError


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get_system_info.return_value = {
        "grocy_version": {"Version": "3.3.2"},
        "php_version": "8.1.0",
        "sqlite_version": "3.39.0",
    }
    client.get_objects.return_value = [
        {"id": 1, "name": "Item A"},
        {"id": 2, "name": "Item B"},
    ]
    client.create_object.return_value = 42
    client.update_object.return_value = None
    client.delete_object.return_value = None
    client.update_userfields.return_value = None
    return client


async def test_system_info(mock_client):
    result = await system_info(mock_client)
    assert "3.3.2" in result


async def test_entity_list(mock_client):
    result = await entity_list(mock_client, "products")
    assert "Item A" in result
    assert "Item B" in result
    mock_client.get_objects.assert_called_once_with("products")


async def test_entity_list_empty(mock_client):
    mock_client.get_objects.return_value = []
    result = await entity_list(mock_client, "products")
    assert "no" in result.lower() or "empty" in result.lower() or "0" in result


async def test_entity_manage_create(mock_client):
    result = await entity_manage(mock_client, "products", "create", data={"name": "Cheese"})
    mock_client.create_object.assert_called_once_with("products", {"name": "Cheese"})
    assert "42" in result or "created" in result.lower()


async def test_entity_manage_update(mock_client):
    result = await entity_manage(mock_client, "products", "update", obj_id=1, data={"name": "New"})
    mock_client.update_object.assert_called_once_with("products", 1, {"name": "New"})
    assert result


async def test_entity_manage_delete(mock_client):
    result = await entity_manage(mock_client, "products", "delete", obj_id=1)
    mock_client.delete_object.assert_called_once_with("products", 1)
    assert result


async def test_entity_manage_unknown_action(mock_client):
    with pytest.raises(GrocyValidationError, match="Unknown action"):
        await entity_manage(mock_client, "products", "explode")


async def test_entity_manage_update_missing_obj_id(mock_client):
    with pytest.raises(GrocyValidationError, match="requires an obj_id"):
        await entity_manage(mock_client, "products", "update", data={"name": "X"})
    mock_client.update_object.assert_not_called()


async def test_entity_manage_delete_missing_obj_id(mock_client):
    with pytest.raises(GrocyValidationError, match="requires an obj_id"):
        await entity_manage(mock_client, "products", "delete")
    mock_client.delete_object.assert_not_called()


async def test_entity_manage_create_empty_data(mock_client):
    result = await entity_manage(mock_client, "products", "create")
    mock_client.create_object.assert_called_once_with("products", {})
    assert "42" in result


async def test_userfields_set(mock_client):
    result = await userfields_set(mock_client, "products", 87, {"ai_notes": "Prefer paprika"})
    mock_client.update_userfields.assert_called_once_with(
        "products", 87, {"ai_notes": "Prefer paprika"}
    )
    assert "87" in result


async def test_userfields_set_empty_data(mock_client):
    with pytest.raises(GrocyValidationError, match="non-empty object"):
        await userfields_set(mock_client, "products", 87, {})
    mock_client.update_userfields.assert_not_called()


async def test_userfields_set_non_dict_data(mock_client):
    with pytest.raises(GrocyValidationError, match="non-empty object"):
        await userfields_set(mock_client, "products", 87, ["not", "a", "dict"])
    mock_client.update_userfields.assert_not_called()


async def test_entity_update_rejects_userfields_without_request(mock_client):
    with pytest.raises(GrocyValidationError, match="userfields_set_tool"):
        await entity_manage(
            mock_client, "products", "update", obj_id=1, data={"userfields": {"ai_notes": "x"}}
        )
    mock_client.update_object.assert_not_called()


async def test_entity_update_plain_rename_still_works(mock_client):
    result = await entity_manage(mock_client, "products", "update", obj_id=1, data={"name": "New"})
    mock_client.update_object.assert_called_once_with("products", 1, {"name": "New"})
    assert "Updated" in result


async def test_entity_create_not_null_error_is_translated(mock_client):
    mock_client.create_object.side_effect = GrocyValidationError(
        'Validation error: {"error_message":"SQLSTATE[23000]: Integrity constraint violation: '
        '19 NOT NULL constraint failed: products.location_id"}'
    )
    with pytest.raises(GrocyValidationError) as exc:
        await entity_manage(mock_client, "products", "create", data={"name": "X"})
    message = str(exc.value)
    assert "required field 'location_id'" in message
    assert "SQLSTATE" not in message


async def test_entity_create_unique_error_is_translated(mock_client):
    mock_client.create_object.side_effect = GrocyValidationError(
        "Validation error: UNIQUE constraint failed: products.name"
    )
    with pytest.raises(GrocyValidationError, match="already exists"):
        await entity_manage(mock_client, "products", "create", data={"name": "X"})


async def test_entity_update_foreign_key_error_is_translated(mock_client):
    mock_client.update_object.side_effect = GrocyValidationError(
        "Validation error: FOREIGN KEY constraint failed"
    )
    with pytest.raises(GrocyValidationError, match="does not exist"):
        await entity_manage(mock_client, "products", "update", obj_id=1, data={"location_id": 99})


async def test_entity_create_other_validation_errors_pass_through(mock_client):
    mock_client.create_object.side_effect = GrocyValidationError("Validation error: other")
    with pytest.raises(GrocyValidationError, match="other"):
        await entity_manage(mock_client, "products", "create", data={"name": "X"})


async def test_entity_create_qu_id_field_gets_lookup_hint(mock_client):
    mock_client.create_object.side_effect = GrocyValidationError(
        "NOT NULL constraint failed: products.qu_id_stock"
    )
    with pytest.raises(GrocyValidationError, match="qu_id_stock.*find a valid ID"):
        await entity_manage(mock_client, "products", "create", data={"name": "X"})


async def test_entity_create_composite_unique_error_names_all_columns(mock_client):
    mock_client.create_object.side_effect = GrocyValidationError(
        "UNIQUE constraint failed: product_barcodes.barcode, product_barcodes.shopping_location_id"
    )
    with pytest.raises(GrocyValidationError) as exc:
        await entity_manage(mock_client, "product_barcodes", "create", data={})
    assert "combination of 'barcode', 'shopping_location_id'" in str(exc.value)
