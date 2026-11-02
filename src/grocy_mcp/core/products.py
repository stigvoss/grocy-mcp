"""Bulk product reads, including userfields, for Grocy."""

from __future__ import annotations

from typing import Any

from grocy_mcp.client import GrocyClient
from grocy_mcp.exceptions import GrocyValidationError

_USERFIELDS_PREFIX = "userfields."


def is_empty_value(value: Any) -> bool:
    """Return True for values Grocy treats as an unset userfield."""
    return value is None or (isinstance(value, str) and not value.strip())


def is_truthy_value(value: Any) -> bool:
    """Return True for checkbox-style userfield values such as 1, "1" or "true"."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _select_fields(product: dict, fields: list[str]) -> dict:
    selected: dict[str, Any] = {}
    userfields = product.get("userfields") or {}
    for field in fields:
        if field == "userfields":
            selected["userfields"] = userfields
        elif field.startswith(_USERFIELDS_PREFIX):
            key = field[len(_USERFIELDS_PREFIX) :]
            selected.setdefault("userfields", {})[key] = userfields.get(key)
        elif field in product:
            selected[field] = product[field]
    return selected


async def products_list_data(
    client: GrocyClient,
    fields: list[str] | None = None,
    userfields_set: list[str] | None = None,
) -> list[dict]:
    """Return every product as full JSON with its ``userfields`` object.

    Uses a single bulk request: Grocy attaches the userfield values to each object returned
    by ``GET /objects/products``.

    Args:
        client: Grocy client.
        fields: Keys to keep, e.g. ``["id", "name", "userfields.bilkatogo_ids"]``. All keys when
            omitted.
        userfields_set: Userfield names that must be non-empty for a product to be included.
    """
    if fields is not None and not all(isinstance(f, str) and f for f in fields):
        raise GrocyValidationError("fields must be a list of non-empty strings.")
    if userfields_set is not None and not all(isinstance(f, str) and f for f in userfields_set):
        raise GrocyValidationError("userfields_set must be a list of userfield names.")

    products = await client.get_objects("products")
    result = []
    for product in products:
        product = {**product, "userfields": product.get("userfields") or {}}
        if userfields_set and any(
            is_empty_value(product["userfields"].get(name)) for name in userfields_set
        ):
            continue
        result.append(_select_fields(product, fields) if fields else product)
    return result
