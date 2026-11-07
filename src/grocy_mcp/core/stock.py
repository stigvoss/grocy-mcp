"""Core stock management functions for Grocy."""

from __future__ import annotations

import asyncio
import math
import weakref

from grocy_mcp.client import GrocyClient
from grocy_mcp.core.products import is_truthy_value
from grocy_mcp.core.resolve import resolve_location, resolve_product
from grocy_mcp.core.utils import is_iso_date
from grocy_mcp.exceptions import GrocyValidationError


async def stock_overview(client: GrocyClient) -> str:
    """Return a formatted overview of current stock."""
    items = await client.get_stock()
    if not items:
        return "No stock found."
    lines = ["Current stock:"]
    for item in items:
        product = item.get("product") or {}
        name = product.get("name", f"Product {item.get('product_id')}")
        amount = item.get("amount", 0)
        lines.append(f"  [{item.get('product_id', '?')}] {name} — {amount}")
    return "\n".join(lines)


async def stock_expiring(client: GrocyClient) -> str:
    """Return products that are expiring soon or already expired."""
    volatile = await client.get_volatile_stock()
    expiring = volatile.get("expiring_products", [])
    expired = volatile.get("expired_products", [])
    missing = volatile.get("missing_products", [])

    lines = []

    if expiring:
        lines.append("Expiring soon:")
        for item in expiring:
            product = item.get("product") or {}
            name = product.get("name", f"Product {item.get('product_id')}")
            lines.append(f"  {name}")

    if expired:
        lines.append("Expired:")
        for item in expired:
            product = item.get("product") or {}
            name = product.get("name", f"Product {item.get('product_id')}")
            lines.append(f"  {name}")

    if missing:
        lines.append("Missing (below min stock):")
        for item in missing:
            product = item.get("product") or {}
            name = product.get("name", f"Product {item.get('product_id')}")
            lines.append(f"  {name}")

    if not lines:
        return "No expiring, expired, or missing products found."

    return "\n".join(lines)


# asyncio.Lock objects belong to one event loop, so the registry is keyed by the running loop.
# Both levels are weak: a closed loop and idle locks are dropped, while a caller that is
# waiting for or holding a lock keeps it alive for the duration of its ``async with``.
_inventory_locks: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, weakref.WeakValueDictionary[int, asyncio.Lock]
] = weakref.WeakKeyDictionary()


def _inventory_lock(product_id: int) -> asyncio.Lock:
    locks = _inventory_locks.setdefault(asyncio.get_running_loop(), weakref.WeakValueDictionary())
    lock = locks.get(product_id)
    if lock is None:
        lock = locks[product_id] = asyncio.Lock()
    return lock


def _split_amounts(info: dict) -> tuple[float, float, float]:
    """Return (total, opened, unopened) amounts from a stock product details response."""
    total = float(info.get("stock_amount") or 0)
    opened = float(info.get("stock_amount_opened") or 0)
    return total, opened, max(total - opened, 0.0)


def _fmt(value: float) -> str:
    return f"{value:g}"


async def stock_product_info(client: GrocyClient, product: str) -> str:
    """Return detailed stock information for a specific product."""
    product_id = await resolve_product(client, product)
    info = await client.get_stock_product(product_id)

    product_data = info.get("product") or {}
    name = product_data.get("name", f"Product {product_id}")
    total, opened, unopened = _split_amounts(info)
    best_before = info.get("next_best_before_date", "unknown")
    unit = (info.get("quantity_unit_stock") or {}).get("name", "unknown")
    location = (info.get("location") or {}).get("name", "unknown")

    return (
        f"Product: {name}\n"
        f"  In stock: {_fmt(total)} {unit}\n"
        f"  Unopened: {_fmt(unopened)}\n"
        f"  Opened: {_fmt(opened)}\n"
        f"  Location: {location}\n"
        f"  Next best before: {best_before}"
    )


async def stock_add(
    client: GrocyClient,
    product: str,
    amount: float,
    price: float | None = None,
    best_before_date: str | None = None,
    location_id: int | None = None,
    location: str | None = None,
    purchased_date: str | None = None,
    shopping_location_id: int | None = None,
    **kwargs,
) -> str:
    """Add stock for a product, optionally with price, dates, location and store.

    Args:
        client: Grocy client.
        product: Product name or numeric ID.
        amount: Quantity to add.
        price: Price per stock unit.
        best_before_date: Best-before date as YYYY-MM-DD.
        location_id: Location ID to add the stock to, when not the product's default.
        location: Location name or numeric ID, as an alternative to ``location_id``.
        purchased_date: Purchase date as YYYY-MM-DD.
        shopping_location_id: Store (shopping location) ID.
    """
    if price is not None and not (math.isfinite(price) and price >= 0):
        raise GrocyValidationError("price must be a finite number that is not negative.")
    for field, value in (
        ("best_before_date", best_before_date),
        ("purchased_date", purchased_date),
    ):
        if value is not None and not is_iso_date(value):
            raise GrocyValidationError(f"{field} must be formatted as YYYY-MM-DD.")
    if location is not None and location_id is not None:
        raise GrocyValidationError("Pass either location or location_id, not both.")
    product_id = await resolve_product(client, product)
    if location is not None:
        location_id = await resolve_location(client, location)
    options = {
        "price": price,
        "best_before_date": best_before_date,
        "location_id": location_id,
        "purchased_date": purchased_date,
        "shopping_location_id": shopping_location_id,
        **kwargs,
    }
    await client.add_stock(
        product_id, amount, **{k: v for k, v in options.items() if v is not None}
    )
    suffix = f" at price {price:g}" if price is not None else ""
    return f"Added {amount} of '{product}' to stock{suffix}."


async def stock_consume(client: GrocyClient, product: str, amount: float, **kwargs) -> str:
    """Consume stock for a product."""
    product_id = await resolve_product(client, product)
    await client.consume_stock(product_id, amount, **kwargs)
    return f"Consumed {amount} of '{product}' from stock."


async def stock_transfer(
    client: GrocyClient,
    product: str,
    amount: float,
    to_location: str,
    from_location: str | None = None,
) -> str:
    """Transfer stock to a different location.

    Grocy needs the source location. When ``from_location`` is omitted it is taken from the
    single location that holds stock of the product; if stock is spread over several locations
    (or there is none) an error asks for ``from_location``.
    """
    product_id = await resolve_product(client, product)
    to_location_id = await resolve_location(client, to_location)
    if from_location is not None:
        from_location_id = await resolve_location(client, from_location)
    else:
        locations = [
            loc for loc in await client.get_stock_locations(product_id) if loc.get("amount", 0) > 0
        ]
        if not locations:
            raise GrocyValidationError(f"'{product}' has no stock to transfer.")
        if len(locations) > 1:
            where = ", ".join(f"{loc['location_name']} ({loc['amount']:g})" for loc in locations)
            raise GrocyValidationError(
                f"'{product}' has stock in several locations: {where}. "
                "Pass from_location to choose the source."
            )
        from_location_id = locations[0]["location_id"]
    await client.transfer_stock(product_id, amount, to_location_id, from_location_id)
    return f"Transferred {amount} of '{product}' to location '{to_location}'."


async def stock_inventory(
    client: GrocyClient,
    product: str,
    new_amount: float,
    opened_amount: float | None = None,
) -> str:
    """Set the stock amount for a product via inventory and report the opened/unopened split.

    Grocy removes opened units first when the amount goes down. With ``opened_amount`` the
    missing units are opened afterwards so the result matches the physical count. Grocy cannot
    un-open units, so if more units are open than asked for, the result says so.
    """
    if opened_amount is not None and not (
        math.isfinite(opened_amount) and 0 <= opened_amount <= new_amount
    ):
        raise GrocyValidationError("opened_amount must be between 0 and new_amount.")

    product_id = await resolve_product(client, product)
    # Serialise the read/adjust/open sequence per product, so overlapping calls in this server
    # cannot both read the same opened count and each open the missing units.
    async with _inventory_lock(product_id):
        total, _, _ = _split_amounts(await client.get_stock_product(product_id))
        if total != new_amount:
            # Grocy rejects an inventory that equals the current amount, so skip it then
            await client.inventory_stock(product_id, new_amount)
        total, opened, unopened = _split_amounts(await client.get_stock_product(product_id))

        note = ""
        if opened_amount is not None and opened < opened_amount:
            try:
                await client.open_stock(product_id, opened_amount - opened)
            except GrocyValidationError:
                note = (
                    f" The inventory was applied, but opening {_fmt(opened_amount - opened)} "
                    f"more to reach {_fmt(opened_amount)} opened failed."
                )
            total, opened, unopened = _split_amounts(await client.get_stock_product(product_id))
        if opened_amount is not None and opened > opened_amount:
            note += (
                f" {_fmt(opened)} are open but {_fmt(opened_amount)} were requested; "
                "Grocy cannot un-open units."
            )

    return (
        f"Inventory updated: '{product}' set to {new_amount} "
        f"(unopened {_fmt(unopened)}, opened {_fmt(opened)}).{note}"
    )


async def stock_open(client: GrocyClient, product: str, amount: float = 1.0) -> str:
    """Mark stock as opened for a product.

    Returns an explanatory message instead of calling Grocy when there is not enough unopened
    stock.
    """
    product_id = await resolve_product(client, product)
    info = await client.get_stock_product(product_id)
    name = (info.get("product") or {}).get("name", f"Product {product_id}")
    _, opened, unopened = _split_amounts(info)

    if unopened < amount:
        return (
            f"Cannot open {_fmt(amount)} of '{name}': unopened amount is {_fmt(unopened)} "
            f"(already opened: {_fmt(opened)}). Add stock first, or consume the opened amount."
        )

    try:
        await client.open_stock(product_id, amount)
    except GrocyValidationError:
        return (
            f"Grocy refused to open {_fmt(amount)} of '{name}' "
            f"(unopened: {_fmt(unopened)}, opened: {_fmt(opened)}). "
            "Check the product's stock and 'opened' settings."
        )
    return f"Opened {amount} of '{product}'."


async def stock_levels_data(
    client: GrocyClient,
    product_group: str | None = None,
    high_churn: bool | None = None,
) -> list[dict]:
    """Return every active product with its stock amount, including products at 0 stock.

    ``amount`` is the product's own stock; ``amount_aggregated`` also counts child products, so a
    parent whose children are in stock is not mistaken for out of stock.

    Args:
        client: Grocy client.
        product_group: Product group name or numeric ID to filter on.
        high_churn: When set, keep only products whose ``high_churn`` userfield matches.
    """
    products = await client.get_objects("products")
    stock = await client.get_stock()
    units = {u["id"]: u.get("name") for u in await client.get_objects("quantity_units")}
    locations = {loc["id"]: loc.get("name") for loc in await client.get_objects("locations")}

    amounts: dict[int, float] = {}
    aggregated: dict[int, float] = {}
    for row in stock:
        pid = row.get("product_id")
        amount = float(row.get("amount") or 0)
        amounts[pid] = amounts.get(pid, 0.0) + amount
        aggregated[pid] = aggregated.get(pid, 0.0) + float(row.get("amount_aggregated") or amount)

    group_id: int | None = None
    if product_group is not None:
        if product_group.isdigit():
            group_id = int(product_group)
        else:
            groups = await client.get_objects("product_groups")
            wanted = product_group.strip().lower()
            matches = [g for g in groups if (g.get("name") or "").strip().lower() == wanted]
            if not matches:
                names = ", ".join(g.get("name", "?") for g in groups)
                raise GrocyValidationError(
                    f"No product group named '{product_group}'. Available: {names}"
                )
            group_id = matches[0]["id"]

    result = []
    for product in products:
        if str(product.get("active", 1)) == "0":
            continue
        if group_id is not None and product.get("product_group_id") != group_id:
            continue
        churn = is_truthy_value((product.get("userfields") or {}).get("high_churn"))
        if high_churn is not None and churn != high_churn:
            continue
        result.append(
            {
                "product_id": product["id"],
                "name": product.get("name"),
                "amount": amounts.get(product["id"], 0.0),
                "amount_aggregated": aggregated.get(product["id"], 0.0),
                "stock_unit": units.get(product.get("qu_id_stock")),
                "default_location": locations.get(product.get("location_id")),
                "product_group_id": product.get("product_group_id"),
                "high_churn": churn,
            }
        )
    return result


async def stock_search(client: GrocyClient, query: str) -> str:
    """Search for products by name or barcode."""
    products = await client.get_objects("products")
    query_lower = query.lower()
    matches = [p for p in products if query_lower in p.get("name", "").lower()]

    barcodes = await client.get_objects("product_barcodes")
    barcode_ids = {b["product_id"] for b in barcodes if query_lower in b.get("barcode", "").lower()}
    for p in products:
        if p["id"] in barcode_ids and p not in matches:
            matches.append(p)

    if not matches:
        return f"No products found matching '{query}'."

    lines = [f"Products matching '{query}':"]
    for p in matches:
        lines.append(f"  [{p['id']}] {p.get('name', '?')}")
    return "\n".join(lines)


async def stock_barcode_lookup(client: GrocyClient, barcode: str) -> str:
    """Look up stock information by barcode."""
    info = await client.get_stock_by_barcode(barcode)
    product = info.get("product") or {}
    name = product.get("name", f"Barcode {barcode}")
    amount = info.get("stock_amount", 0)
    return f"Barcode {barcode}: {name} — {amount} in stock."
