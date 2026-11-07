"""Core system information and generic entity management for Grocy."""

from __future__ import annotations

import re

from grocy_mcp.client import GrocyClient
from grocy_mcp.exceptions import GrocyValidationError

_NOT_NULL = re.compile(r"NOT NULL constraint failed: (\w+)\.(\w+)")
_UNIQUE = re.compile(r"UNIQUE constraint failed: (\w+)\.(\w+)")
_FOREIGN_KEY = "FOREIGN KEY constraint failed"


def _friendly_constraint_error(entity: str, action: str, error: GrocyValidationError) -> Exception:
    """Turn a raw Grocy/SQLite constraint failure into a message that says what to do next."""
    text = str(error)
    if match := _NOT_NULL.search(text):
        column = match.group(2)
        hint = (
            " Use locations_list_tool or catalog_list_tool to find a valid ID."
            if column.endswith("_id")
            else ""
        )
        return GrocyValidationError(
            f"Cannot {action} {entity}: required field '{column}' is missing. Add it to data "
            f"and retry; Grocy reports one missing field at a time.{hint}"
        )
    if match := _UNIQUE.search(text):
        return GrocyValidationError(
            f"Cannot {action} {entity}: a record with the same '{match.group(2)}' already "
            "exists. Use a different value, or update the existing record."
        )
    if _FOREIGN_KEY in text:
        return GrocyValidationError(
            f"Cannot {action} {entity}: an ID in data refers to a record that does not exist. "
            "Check the *_id values with the matching list tool."
        )
    return error


async def system_info(client: GrocyClient) -> str:
    """Return Grocy system information."""
    info = await client.get_system_info()
    grocy_version = info.get("grocy_version", {})
    version = (
        grocy_version.get("Version", "unknown")
        if isinstance(grocy_version, dict)
        else str(grocy_version)
    )
    php_version = info.get("php_version", "unknown")
    sqlite_version = info.get("sqlite_version", "unknown")

    return (
        f"Grocy System Info:\n"
        f"  Grocy version: {version}\n"
        f"  PHP version: {php_version}\n"
        f"  SQLite version: {sqlite_version}"
    )


async def entity_list(client: GrocyClient, entity: str) -> str:
    """List all objects of a given entity type."""
    items = await client.get_objects(entity)
    if not items:
        return f"No {entity} found."

    lines = [f"{entity} ({len(items)} item(s)):"]
    for item in items:
        item_id = item.get("id", "?")
        name = item.get("name", str(item))
        lines.append(f"  [{item_id}] {name}")

    return "\n".join(lines)


async def entity_manage(
    client: GrocyClient,
    entity: str,
    action: str,
    obj_id: int | None = None,
    data: dict | None = None,
) -> str:
    """Perform create, update, or delete on any Grocy entity."""
    match action:
        case "create":
            payload = data or {}
            try:
                created_id = await client.create_object(entity, payload)
            except GrocyValidationError as e:
                raise _friendly_constraint_error(entity, "create", e) from e
            return f"Created {entity} object with ID {created_id}."

        case "update":
            if obj_id is None:
                raise GrocyValidationError("Update requires an obj_id.")
            payload = data or {}
            if "userfields" in payload:
                raise GrocyValidationError(
                    "Use userfields_set_tool for userfields; entity updates cannot change them."
                )
            try:
                await client.update_object(entity, obj_id, payload)
            except GrocyValidationError as e:
                raise _friendly_constraint_error(entity, "update", e) from e
            return f"Updated {entity} object ID {obj_id}."

        case "delete":
            if obj_id is None:
                raise GrocyValidationError("Delete requires an obj_id.")
            await client.delete_object(entity, obj_id)
            return f"Deleted {entity} object ID {obj_id}."

        case _:
            raise GrocyValidationError(
                f"Unknown action '{action}'. Valid actions: create, update, delete."
            )


async def userfields_set(client: GrocyClient, entity: str, obj_id: int, data: dict) -> str:
    """Set userfield values on an existing Grocy entity object."""
    if not isinstance(data, dict) or not data:
        raise GrocyValidationError("userfields_set requires a non-empty object of field values.")
    await client.update_userfields(entity, obj_id, data)
    return f"Updated userfields for {entity} object ID {obj_id}."
