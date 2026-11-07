"""Core shopping list management functions for Grocy."""

from __future__ import annotations

from grocy_mcp.client import GrocyClient
from grocy_mcp.core.resolve import resolve_product
from grocy_mcp.exceptions import GrocyValidationError


async def _product_name_map(client: GrocyClient) -> dict[int, str]:
    """Return a mapping of product_id -> product name."""
    products = await client.get_objects("products")
    return {p["id"]: p.get("name", f"Product {p['id']}") for p in products}


async def shopping_list_view(client: GrocyClient, list_id: int = 1) -> str:
    """Return a formatted view of the shopping list."""
    items = await client.get_shopping_list(list_id)
    if not items:
        return "No shopping list items found."

    name_map = await _product_name_map(client)

    lines = [f"Shopping list #{list_id}:"]
    for item in items:
        product_id = item.get("product_id")
        amount = item.get("amount", 1)
        note = item.get("note")
        if product_id is None:
            line = f"  [{item['id']}] {note or '(empty note)'} — note"
        else:
            name = name_map.get(product_id, f"Product {product_id}")
            line = f"  [{item['id']}] {name} — {amount}"
            if note:
                line += f" ({note})"
        lines.append(line)

    return "\n".join(lines)


def _normalize_note(note: str | None) -> str:
    return " ".join((note or "").casefold().split())


async def shopping_list_add(
    client: GrocyClient,
    product: str | None = None,
    amount: float = 1.0,
    list_id: int = 1,
    note: str | None = None,
    skip_if_present: bool = False,
) -> str:
    """Add a product, or a note-only line, to the shopping list.

    A note-only line (no ``product``) is for things that have no Grocy product, e.g.
    "Spinat 300 g (Tue)". With ``skip_if_present`` nothing is added when the product (or an
    identical note) is already on the list, and the reply says which item matched.
    """
    if not product and not (note or "").strip():
        raise GrocyValidationError("Give a product, or a note for a note-only line.")
    if not product:
        wanted = _normalize_note(note)
        match = None
        if skip_if_present:
            match = next(
                (
                    i
                    for i in await client.get_shopping_list(list_id)
                    if i.get("product_id") is None and _normalize_note(i.get("note")) == wanted
                ),
                None,
            )
        if match:
            return f"Skipped: note '{note}' is already on the list (item ID {match['id']})."
        item_id = await client.add_shopping_list_item(None, amount, list_id, note.strip())
        return f"Added note '{note.strip()}' to shopping list (item ID {item_id})."

    product_id = await resolve_product(client, product)
    if skip_if_present:
        match = next(
            (
                i
                for i in await client.get_shopping_list(list_id)
                if i.get("product_id") == product_id
            ),
            None,
        )
        if match:
            return (
                f"Skipped: '{product}' is already on the list "
                f"(item ID {match['id']}, amount {match.get('amount')})."
            )
    item_id = await client.add_shopping_list_item(product_id, amount, list_id, note)
    return f"Added {amount} of '{product}' to shopping list (item ID {item_id})."


async def shopping_list_update(client: GrocyClient, item_id: int, data: dict) -> str:
    """Update a shopping list item by its ID."""
    await client.update_shopping_list_item(item_id, data)
    return f"Shopping list item {item_id} updated."


async def shopping_list_set_amount(client: GrocyClient, item_id: int, amount: float) -> str:
    """Set the amount for a shopping list item."""
    await client.update_shopping_list_item(item_id, {"amount": amount})
    return f"Shopping list item {item_id} amount set to {amount}."


async def shopping_list_set_note(client: GrocyClient, item_id: int, note: str) -> str:
    """Set or update the note for a shopping list item."""
    await client.update_shopping_list_item(item_id, {"note": note})
    return f"Shopping list item {item_id} note set to '{note}'."


async def shopping_list_remove(client: GrocyClient, item_id: int) -> str:
    """Remove a shopping list item by its ID."""
    await client.remove_shopping_list_item(item_id)
    return f"Shopping list item {item_id} removed."


async def shopping_list_clear(client: GrocyClient, list_id: int = 1) -> str:
    """Clear all items from a shopping list."""
    await client.clear_shopping_list(list_id)
    return f"Shopping list #{list_id} cleared."


async def shopping_list_add_missing(client: GrocyClient, list_id: int = 1) -> str:
    """Add missing products (below min stock) to the shopping list."""
    await client.add_missing_products_to_shopping_list(list_id)
    return f"Missing products added to shopping list #{list_id}."
