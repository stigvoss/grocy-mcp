"""Bulk product reads, including userfields, for Grocy."""

from __future__ import annotations

import difflib
import math
import re
from typing import Any
from urllib.parse import unquote_plus

from grocy_mcp.client import GrocyClient
from grocy_mcp.exceptions import GrocyError, GrocyValidationError

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
    # Only None is "no value": a numeric 0 (or False) is a real userfield value
    return [
        t.strip().lower() for t in ("" if value is None else str(value)).split(",") if t.strip()
    ]


def userfield_contains(value: Any, needle: str) -> bool:
    """Case-insensitive substring match, also against the URL-decoded value (query=hakket%20...)."""
    if value is None:
        return False
    # Decode before lowercasing: %C3%98 decodes to "Ø", which only lowercases once it is decoded.
    raw = str(value)
    needle = needle.strip().lower()
    return bool(needle) and (needle in raw.lower() or needle in unquote_plus(raw).lower())


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
                isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
                for k, v in mapping.items()
            )
        ):
            raise GrocyValidationError(
                f"{label} must map non-blank userfield names to non-empty text."
            )

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


_WORD_MIN_RATIO = 0.75  # every word must resemble its counterpart at least this much
_WORDS_MEAN_RATIO = 0.87  # and the words must resemble their counterparts this much on average


def _words(name: str) -> list[str]:
    return re.findall(r"\w+", name.casefold())


def _name_key(name: str) -> str:
    """Case-insensitive name with the words sorted, so word order and punctuation do not matter."""
    return " ".join(sorted(_words(name)))


_MAX_MATCHED_WORDS = 16  # bitmask states grow as 2**words; longer names use greedy pairing


def _word_ratio(x: str, y: str) -> float:
    """Symmetric word similarity: ``SequenceMatcher`` scores a transposition differently
    depending on argument order (``ppeper``/``pepper`` is 0.67 one way and 0.83 the other)."""
    return max(
        difflib.SequenceMatcher(None, x, y).ratio(),
        difflib.SequenceMatcher(None, y, x).ratio(),
    )


def _words_similar(a: list[str], b: list[str]) -> bool:
    """True when both names have the same number of words and each word has a close match.

    The words are paired one-to-one so that every pair meets the per-word minimum and the
    pairs meet the mean, whatever the word order: a typo is found wherever it sorts ("Minced
    veef" vs "Minced beef") and a reordered typo too ("Pepper, while whole" vs "Pepper, whole
    white"). The best pairing is found with a dynamic programme over the set of already used
    words of ``b`` (no factorial enumeration), and a word without any plausible counterpart
    ends the comparison at once, so unrelated names are cheap.
    """
    if len(a) != len(b) or not a:
        return False
    n = len(a)
    allowed: list[list[tuple[int, float]]] = []
    for word in a:
        row = []
        for j, other in enumerate(b):
            ratio = _word_ratio(word, other)
            if ratio >= _WORD_MIN_RATIO:
                row.append((j, ratio))
        if not row:
            return False
        allowed.append(row)

    if n > _MAX_MATCHED_WORDS:
        unused = set(range(n))
        total = 0.0
        for row in allowed:
            candidates = [(j, r) for j, r in row if j in unused]
            if not candidates:
                return False
            j, r = max(candidates, key=lambda pair: pair[1])
            unused.remove(j)
            total += r
        return total / n >= _WORDS_MEAN_RATIO

    best = {0: 0.0}  # used-word mask of b -> best score sum so far
    for row in allowed:
        following: dict[int, float] = {}
        for mask, total in best.items():
            for j, ratio in row:
                bit = 1 << j
                if not mask & bit and total + ratio > following.get(mask | bit, -1.0):
                    following[mask | bit] = total + ratio
        if not following:
            return False
        best = following
    return max(best.values()) / n >= _WORDS_MEAN_RATIO


def _plain_name(name: str) -> str:
    """Case-folded name with whitespace collapsed; unlike the word key it keeps every character,
    so names made only of symbols or emoji can still be compared."""
    return " ".join(name.casefold().split())


def find_near_duplicates(name: str, products: list[dict]) -> list[dict]:
    """Return existing products whose name is the same, or nearly the same, as ``name``."""
    plain = _plain_name(name)
    key = _name_key(name)
    words = _words(name)
    found = []
    for product in products:
        other_name = product.get("name") or ""
        if not other_name.strip():
            continue
        if _plain_name(other_name) == plain or (key and _name_key(other_name) == key):
            reason = "same name (ignoring case and word order)"
        elif key and _words_similar(words, _words(other_name)):
            reason = "very similar name"
        else:
            continue
        found.append({"product_id": product["id"], "name": product.get("name"), "reason": reason})
    return found


def _resolve_known(items: list[dict], value: str | int, label: str) -> dict:
    """Find an item by ID or exact (case-insensitive) name; the error lists the valid values.

    IDs are searched first, like ``core/resolve.py``: an item that happens to be *named* "4"
    must not shadow the item whose ID is 4 (a stock unit cannot be changed once stock exists).
    """
    text = str(value).strip()
    for item in items:
        if str(item["id"]) == text:
            return item
    for item in items:
        if (item.get("name") or "").casefold() == text.casefold():
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
        except GrocyError as error:
            result["warning"] = (
                f"Product {product_id} was created, but the userfields could not be saved or "
                f"confirmed ({error}). Check them with products_list_tool and set them with "
                "userfields_set_tool."
            )
    return result
