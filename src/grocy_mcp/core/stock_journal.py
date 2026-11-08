"""Core stock journal/history functions for Grocy."""

from __future__ import annotations

from grocy_mcp.client import GrocyClient
from grocy_mcp.core.resolve import resolve_product
from grocy_mcp.core.utils import format_amount, tidy_amount


async def stock_journal(client: GrocyClient, product: str | None = None) -> str:
    """Return recent stock journal entries, optionally filtered by product."""
    entries = await client.get_objects("stock_log")
    if not entries:
        return "No stock journal entries found."

    # Build product name map
    products = await client.get_objects("products")
    product_map = {p["id"]: p.get("name", f"Product {p['id']}") for p in products}

    # Filter by product if specified
    if product is not None:
        product_id = await resolve_product(client, product)
        entries = [e for e in entries if e.get("product_id") == product_id]
        if not entries:
            return f"No stock journal entries found for '{product}'."

    # Float residue (e.g. 2.2e-16 from opening or transferring) is not a real movement
    visible = [e for e in entries if tidy_amount(e.get("amount")) != 0.0]
    hidden = len(entries) - len(visible)
    entries = visible

    # Newest first. Bookings made within the same second share a timestamp, and a reverse sort
    # keeps equal items in their original (oldest-first) order, so break ties by booking ID.
    entries.sort(
        key=lambda e: (e.get("row_created_timestamp") or "", int(e.get("id") or 0)), reverse=True
    )
    entries = entries[:50]

    lines = ["Stock journal (most recent first):"]
    for entry in entries:
        prod_name = product_map.get(entry.get("product_id"), f"Product {entry.get('product_id')}")
        tidy = tidy_amount(entry.get("amount"))
        amount = format_amount(tidy) if tidy is not None else entry.get("amount", "?")
        txn_type = entry.get("transaction_type", "?")
        spoiled = " (spoiled)" if int(entry.get("spoiled") or 0) else ""
        timestamp = entry.get("row_created_timestamp", "?")
        lines.append(
            f"  [{entry.get('id', '?')}] {prod_name} — {txn_type} {amount}{spoiled} — {timestamp}"
        )

    if hidden:
        lines.append(f"  ({hidden} zero-amount entr{'y' if hidden == 1 else 'ies'} hidden)")

    return "\n".join(lines)
