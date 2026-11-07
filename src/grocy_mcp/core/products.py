"""Bulk product reads, including userfields, for Grocy."""

from __future__ import annotations

import difflib
import math
import re
from typing import Any
from urllib.parse import unquote_plus

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


def userfield_tokens(value: Any) -> list[str]:
    """Split a comma-separated userfield value into trimmed, lower-cased tokens."""
    return [t.strip().lower() for t in str(value or "").split(",") if t.strip()]


def userfield_contains(value: Any, needle: str) -> bool:
    """Case-insensitive substring match, also against the URL-decoded value (query=hakket%20...)."""
    if value is None:
        return False
    text = str(value).lower()
    needle = needle.strip().lower()
    return bool(needle) and (needle in text or needle in unquote_plus(text))


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
    userfields_match: dict[str, str] | None = None,
    userfields_contains: dict[str, str] | None = None,
) -> list[dict]:
    """Return every product as full JSON with its ``userfields`` object.

    Uses a single bulk request: Grocy attaches the userfield values to each object returned
    by ``GET /objects/products``.

    Args:
        client: Grocy client.
        fields: Keys to keep, e.g. ``["id", "name", "userfields.bilkatogo_ids"]``. All keys when
            omitted.
        userfields_set: Userfield names that must be non-empty for a product to be included.
        userfields_match: ``{"bilkatogo_ids": "19753"}``; the value must equal one of the
            comma-separated tokens of the userfield (whitespace trimmed, case-insensitive), so
            ``19753`` does not match ``119753``.
        userfields_contains: ``{"ai_notes": "hakket"}``; case-insensitive substring match, also
            against the URL-decoded value.
    """
    if fields is not None and not all(isinstance(f, str) and f for f in fields):
        raise GrocyValidationError("fields must be a list of non-empty strings.")
    if userfields_set is not None and not all(isinstance(f, str) and f for f in userfields_set):
        raise GrocyValidationError("userfields_set must be a list of userfield names.")

    for label, mapping in (
        ("userfields_match", userfields_match),
        ("userfields_contains", userfields_contains),
    ):
        if mapping is not None and not (
            isinstance(mapping, dict)
            and all(
                isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in mapping.items()
            )
        ):
            raise GrocyValidationError(f"{label} must map userfield names to non-empty text.")

    products = await client.get_objects("products")
    result = []
    for product in products:
        product = {**product, "userfields": product.get("userfields") or {}}
        if userfields_set and any(
            is_empty_value(product["userfields"].get(name)) for name in userfields_set
        ):
            continue
        userfields = product["userfields"]
        if userfields_match and not all(
            needle.strip().lower() in userfield_tokens(userfields.get(name))
            for name, needle in userfields_match.items()
        ):
            continue
        if userfields_contains and not all(
            userfield_contains(userfields.get(name), needle)
            for name, needle in userfields_contains.items()
        ):
            continue
        result.append(_select_fields(product, fields) if fields else product)
    return result


_NEAR_DUPLICATE_RATIO = 0.88


def _name_key(name: str) -> str:
    """Case-insensitive name with the words sorted, so word order and punctuation do not matter."""
    return " ".join(sorted(re.findall(r"\w+", name.casefold())))


def find_near_duplicates(name: str, products: list[dict]) -> list[dict]:
    """Return existing products whose name is the same, or nearly the same, as ``name``."""
    key = _name_key(name)
    found = []
    for product in products:
        other = _name_key(product.get("name") or "")
        if not other:
            continue
        if other == key:
            reason = "same name (ignoring case and word order)"
        elif difflib.SequenceMatcher(None, key, other).ratio() >= _NEAR_DUPLICATE_RATIO:
            reason = "very similar name"
        else:
            continue
        found.append({"product_id": product["id"], "name": product.get("name"), "reason": reason})
    return found


def _resolve_known(items: list[dict], value: str | int, label: str) -> dict:
    """Find an item by exact (case-insensitive) name or ID; the error lists the valid values."""
    text = str(value).strip()
    for item in items:
        if str(item["id"]) == text or (item.get("name") or "").casefold() == text.casefold():
            return item
    valid = ", ".join(f"{i.get('name')} ({i['id']})" for i in items) or "none defined"
    raise GrocyValidationError(f"Unknown {label} '{text}'. Valid values: {valid}.")


async def product_create_data(
    client: GrocyClient,
    name: str,
    stock_unit: str | int,
    location: str | int,
    product_group: str | int | None = None,
    default_best_before_days: int | None = None,
    min_stock_amount: float | None = None,
    userfields: dict[str, Any] | None = None,
    force: bool = False,
) -> dict:
    """Create a complete product in one call, after validating and checking for duplicates.

    The stock unit cannot be changed once a product has had stock, so unit and location are
    required and must exist. Unless ``force`` is set, nothing is created when the same or a
    near-duplicate name already exists; the candidates are returned instead.
    """
    name = " ".join((name or "").split())
    if not name:
        raise GrocyValidationError("name must not be blank.")
    if default_best_before_days is not None and (
        not isinstance(default_best_before_days, int) or default_best_before_days < -1
    ):
        raise GrocyValidationError("default_best_before_days must be a whole number, or -1.")
    if min_stock_amount is not None and not (
        math.isfinite(min_stock_amount) and min_stock_amount >= 0
    ):
        raise GrocyValidationError("min_stock_amount must be a finite number, not negative.")
    if userfields is not None and not (
        isinstance(userfields, dict) and all(isinstance(k, str) and k for k in userfields)
    ):
        raise GrocyValidationError("userfields must map userfield names to values.")

    unit = _resolve_known(await client.get_objects("quantity_units"), stock_unit, "stock unit")
    place = _resolve_known(await client.get_objects("locations"), location, "location")
    group = None
    if product_group is not None:
        group = _resolve_known(
            await client.get_objects("product_groups"), product_group, "product group"
        )

    if not force:
        duplicates = find_near_duplicates(name, await client.get_objects("products"))
        if duplicates:
            return {
                "created": False,
                "reason": "A product with the same or a very similar name already exists. "
                "Use it, or pass force=true to create anyway.",
                "duplicates": duplicates,
            }

    data: dict[str, Any] = {
        "name": name,
        "location_id": place["id"],
        "qu_id_stock": unit["id"],
        "qu_id_purchase": unit["id"],
        "qu_id_consume": unit["id"],
        "qu_id_price": unit["id"],
    }
    if group is not None:
        data["product_group_id"] = group["id"]
    if default_best_before_days is not None:
        data["default_best_before_days"] = default_best_before_days
    if min_stock_amount is not None:
        data["min_stock_amount"] = min_stock_amount
    product_id = int(await client.create_object("products", data))

    result: dict[str, Any] = {
        "created": True,
        "product_id": product_id,
        "name": name,
        "stock_unit": unit["name"],
        "location": place["name"],
        "product_group": group["name"] if group else None,
    }
    if userfields:
        try:
            await client.update_userfields("products", product_id, userfields)
            result["userfields_set"] = sorted(userfields)
        except GrocyValidationError as error:
            result["warning"] = (
                f"Product created, but the userfields were not saved ({error}). "
                "Set them with userfields_set_tool."
            )
    return result
