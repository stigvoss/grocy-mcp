"""Bulk product reads, including userfields, for Grocy."""

from __future__ import annotations

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
