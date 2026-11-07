"""Core stock management functions for Grocy."""

from __future__ import annotations

import asyncio
import math
import weakref

from grocy_mcp.client import GrocyClient
from grocy_mcp.core.products import is_truthy_value
from grocy_mcp.core.resolve import resolve_location, resolve_product
from grocy_mcp.core.utils import format_amount, is_iso_date, tidy_amount, zero_rows_note
from grocy_mcp.exceptions import GrocyNotFoundError, GrocyValidationError


async def stock_overview(client: GrocyClient) -> str:
    """Return a formatted overview of current stock."""
    items = await client.get_stock()
    if not items:
        return "No stock found."
    lines = ["Current stock:"]
    hidden = 0
    for item in items:
        amount = tidy_amount(item.get("amount", 0))
        if amount == 0:
            hidden += 1
            continue
        product = item.get("product") or {}
        name = product.get("name", f"Product {item.get('product_id')}")
        shown = format_amount(amount) if amount is not None else item.get("amount")
        lines.append(f"  [{item.get('product_id', '?')}] {name} — {shown}")
    if hidden:
        lines.append(f"  {zero_rows_note(hidden)}")
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


_AMOUNT_EPSILON = 1e-9  # tolerance for float residue in the stock balance

# asyncio.Lock objects belong to one event loop, so the registries are keyed by the running loop.
# Both levels are weak: a closed loop and idle locks are dropped, while a caller that is
# waiting for or holding a lock keeps it alive for the duration of its ``async with``.
_LockRegistry = weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, weakref.WeakValueDictionary[int, asyncio.Lock]
]
_product_locks: _LockRegistry = weakref.WeakKeyDictionary()


def _keyed_lock(registry: _LockRegistry, key: int) -> asyncio.Lock:
    locks = registry.setdefault(asyncio.get_running_loop(), weakref.WeakValueDictionary())
    lock = locks.get(key)
    if lock is None:
        lock = locks[key] = asyncio.Lock()
    return lock


def _product_lock(product_id: int) -> asyncio.Lock:
    """One lock per product for every action that reads then rewrites its stock entries.

    Inventory, consume, transfer and entry edits all read the state and write back a result
    derived from it, so an overlapping pair could otherwise undo each other (an edit that
    restores a unit a consume just took). It covers calls within this server process.
    """
    return _keyed_lock(_product_locks, product_id)


def _split_amounts(info: dict) -> tuple[float, float, float]:
    """Return (total, opened, unopened) amounts from a stock product details response."""
    total = float(info.get("stock_amount") or 0)
    opened = float(info.get("stock_amount_opened") or 0)
    return total, opened, max(total - opened, 0.0)


async def stock_product_info(client: GrocyClient, product: str) -> str:
    """Return detailed stock information for a specific product."""
    product_id = await resolve_product(client, product)
    info = await client.get_stock_product(product_id)

    product_data = info.get("product") or {}
    name = product_data.get("name", f"Product {product_id}")
    total, opened, unopened = _split_amounts(info)
    best_before = info.get("next_best_before_date", "unknown")
    unit = (info.get("quantity_unit_stock") or {}).get("name", "unknown")
    default_location = (info.get("location") or {}).get("name", "unknown")
    where = []
    for row in await client.get_stock_locations(product_id):
        amount = tidy_amount(row.get("amount"))
        if amount:
            where.append(f"{row.get('location_name', '?')} {format_amount(amount)}")

    return (
        f"Product: {name}\n"
        f"  In stock: {format_amount(total)} {unit}\n"
        f"  Unopened: {format_amount(unopened)}\n"
        f"  Opened: {format_amount(opened)}\n"
        f"  Stock locations: {', '.join(where) if where else 'none'}\n"
        f"  Default location (where new stock goes, not necessarily where it is): "
        f"{default_location}\n"
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


async def stock_consume(
    client: GrocyClient,
    product: str,
    amount: float,
    from_location: str | None = None,
    spoiled: bool = False,
    **kwargs,
) -> str:
    """Consume stock for a product, optionally from one location and/or as spoiled.

    With ``from_location`` the stock is taken from that location only. If it holds less than
    ``amount``, nothing is consumed and the error lists where the stock is.
    """
    product_id = await resolve_product(client, product)
    async with _product_lock(product_id):
        options = dict(kwargs)
        where = ""
        if from_location is not None:
            location_id = await resolve_location(client, from_location)
            # Keep every raw balance for the check: rounding is for display only, so a request for
            # exactly what is held is never refused and a shortfall is never rounded away.
            held = {
                row.get("location_id"): (
                    row.get("location_name", "?"),
                    float(row.get("amount") or 0),
                )
                for row in await client.get_stock_locations(product_id)
            }
            have = held.get(location_id, (from_location, 0.0))[1]
            if have < amount - _AMOUNT_EPSILON:
                elsewhere = (
                    ", ".join(f"{n} {format_amount(a)}" for n, a in held.values() if tidy_amount(a))
                    or "none"
                )
                raise GrocyValidationError(
                    f"Cannot consume {format_amount(amount)} of '{product}' from '{from_location}': "
                    f"it holds {format_amount(have)}. Stock is at: {elsewhere}."
                )
            options["location_id"] = location_id
            where = f" from '{from_location}'"
        if spoiled:
            options["spoiled"] = True
        await client.consume_stock(product_id, amount, **options)
        kind = "Marked as spoiled" if spoiled else "Consumed"
        return f"{kind} {amount} of '{product}'{where}."


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
    async with _product_lock(product_id):
        to_location_id = await resolve_location(client, to_location)
        if from_location is not None:
            from_location_id = await resolve_location(client, from_location)
        else:
            locations = [
                loc
                for loc in await client.get_stock_locations(product_id)
                if loc.get("amount", 0) > 0
            ]
            if not locations:
                raise GrocyValidationError(f"'{product}' has no stock to transfer.")
            if len(locations) > 1:
                where = ", ".join(
                    f"{loc['location_name']} ({loc['amount']:g})" for loc in locations
                )
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
    async with _product_lock(product_id):
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
                    f" The inventory was applied, but opening {format_amount(opened_amount - opened)} "
                    f"more to reach {format_amount(opened_amount)} opened failed."
                )
            total, opened, unopened = _split_amounts(await client.get_stock_product(product_id))
        if opened_amount is not None and opened > opened_amount:
            note += (
                f" {format_amount(opened)} are open but {format_amount(opened_amount)} were requested; "
                "Grocy cannot un-open units."
            )

    return (
        f"Inventory updated: '{product}' set to {new_amount} "
        f"(unopened {format_amount(unopened)}, opened {format_amount(opened)}).{note}"
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
            f"Cannot open {format_amount(amount)} of '{name}': unopened amount is {format_amount(unopened)} "
            f"(already opened: {format_amount(opened)}). Add stock first, or consume the opened amount."
        )

    try:
        await client.open_stock(product_id, amount)
    except GrocyValidationError:
        return (
            f"Grocy refused to open {format_amount(amount)} of '{name}' "
            f"(unopened: {format_amount(unopened)}, opened: {format_amount(opened)}). "
            "Check the product's stock and 'opened' settings."
        )
    return f"Opened {amount} of '{product}'."


async def stock_levels_data(
    client: GrocyClient,
    product_group: str | None = None,
    high_churn: bool | None = None,
    location: str | None = None,
) -> list[dict]:
    """Return every active product with its stock amount, including products at 0 stock.

    ``amount`` is the product's own stock; ``amount_aggregated`` also counts child products, so a
    parent whose children are in stock is not mistaken for out of stock.

    Args:
        client: Grocy client.
        product_group: Product group name or numeric ID to filter on.
        high_churn: When set, keep only products whose ``high_churn`` userfield matches.
        location: Location name or ID; keeps only products with stock there and adds
            ``amount_in_location``.
    """
    in_location: dict[int, float] | None = None
    if location is not None:
        location_id = await _existing_location_id(client, location)
        in_location = {}
        for row in await client.get_objects("stock_current_locations"):
            if row.get("location_id") == location_id:
                in_location[row["product_id"]] = in_location.get(row["product_id"], 0.0) + float(
                    row.get("amount") or 0
                )
        in_location = {pid: amt for pid, amt in in_location.items() if tidy_amount(amt)}
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
        if in_location is not None and product["id"] not in in_location:
            continue
        churn = is_truthy_value((product.get("userfields") or {}).get("high_churn"))
        if high_churn is not None and churn != high_churn:
            continue
        row = {
            "product_id": product["id"],
            "name": product.get("name"),
            "amount": tidy_amount(amounts.get(product["id"], 0.0)),
            "amount_aggregated": tidy_amount(aggregated.get(product["id"], 0.0)),
            "stock_unit": units.get(product.get("qu_id_stock")),
            "default_location": locations.get(product.get("location_id")),
            "product_group_id": product.get("product_group_id"),
            "high_churn": churn,
        }
        if in_location is not None:
            row["amount_in_location"] = tidy_amount(in_location[product["id"]])
        result.append(row)
    return result


async def _existing_location_id(client: GrocyClient, location: str) -> int:
    """Resolve a location name or ID and make sure it exists (IDs are not checked by resolve)."""
    location_id = await resolve_location(client, location)
    known = await client.get_objects("locations")
    if not any(loc.get("id") == location_id for loc in known):
        available = ", ".join(f"{loc.get('name')} ({loc.get('id')})" for loc in known) or "none"
        raise GrocyValidationError(f"Unknown location '{location}'. Available: {available}.")
    return location_id


async def stock_by_location_data(
    client: GrocyClient,
    location: str | None = None,
    freezer_only: bool = False,
) -> list[dict]:
    """Return the stock held at each location, with product names.

    Unlike the product's default location, this is where the stock actually is. Rows that round
    to zero (float residue) are left out.

    Args:
        client: Grocy client.
        location: Location name or numeric ID; all locations when omitted.
        freezer_only: Keep only freezer locations.
    """
    location_id = await _existing_location_id(client, location) if location is not None else None
    rows = await client.get_objects("stock_current_locations")
    products = {p["id"]: p for p in await client.get_objects("products")}
    units = {u["id"]: u.get("name") for u in await client.get_objects("quantity_units")}

    result = []
    for row in rows:
        amount = tidy_amount(row.get("amount"))
        if not amount:
            continue
        if location_id is not None and row.get("location_id") != location_id:
            continue
        is_freezer = bool(int(row.get("location_is_freezer") or 0))
        if freezer_only and not is_freezer:
            continue
        product = products.get(row.get("product_id"), {})
        result.append(
            {
                "product_id": row.get("product_id"),
                "name": product.get("name", f"Product {row.get('product_id')}"),
                "amount": amount,
                "stock_unit": units.get(product.get("qu_id_stock")),
                "location": row.get("location_name"),
                "is_freezer": is_freezer,
            }
        )
    result.sort(key=lambda r: ((r["location"] or ""), (r["name"] or "").lower()))
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


async def stock_entries_data(
    client: GrocyClient, product: str, location: str | None = None
) -> list[dict]:
    """Return a product's individual stock entries, with the entry IDs the edit tool needs."""
    product_id = await resolve_product(client, product)
    location_id = await _existing_location_id(client, location) if location is not None else None
    names = {loc["id"]: loc.get("name") for loc in await client.get_objects("locations")}
    result = []
    for entry in await client.get_stock_entries(product_id):
        if location_id is not None and entry.get("location_id") != location_id:
            continue
        result.append(
            {
                "entry_id": entry.get("id"),
                "amount": tidy_amount(entry.get("amount")),
                "opened": bool(int(entry.get("open") or 0)),
                "best_before_date": entry.get("best_before_date"),
                "purchased_date": entry.get("purchased_date"),
                "price": entry.get("price"),
                "location": names.get(entry.get("location_id")),
                "shopping_location_id": entry.get("shopping_location_id"),
            }
        )
    return result


async def stock_entry_edit(
    client: GrocyClient,
    entry_id: int,
    amount: float | None = None,
    best_before_date: str | None = None,
    price: float | None = None,
    purchased_date: str | None = None,
    location: str | None = None,
    open: bool | None = None,
) -> str:
    """Correct one stock entry (this rewrites history; confirm with the user first).

    Only the fields given are changed. Grocy requires the full entry, so the current values are
    read first and sent back with the changes applied.
    """
    if (
        all(v is None for v in (amount, best_before_date, price, purchased_date, location, open))
        or entry_id is None
    ):
        raise GrocyValidationError("Give at least one field to change.")
    if amount is not None and not (math.isfinite(amount) and amount > 0):
        raise GrocyValidationError(
            "amount must be greater than 0 (use stock_consume_tool to remove stock)."
        )
    if price is not None and not (math.isfinite(price) and price >= 0):
        raise GrocyValidationError("price must be a finite number that is not negative.")
    for field, value in (
        ("best_before_date", best_before_date),
        ("purchased_date", purchased_date),
    ):
        if value is not None and not is_iso_date(value):
            raise GrocyValidationError(f"{field} must be formatted as YYYY-MM-DD.")

    # Hold the product lock across read, merge and write (and re-read under it): each PUT carries
    # values from its own read, so an overlapping edit or consume would otherwise be undone.
    product_id = (await client.get_stock_entry(entry_id))["product_id"]
    async with _product_lock(product_id):
        current = await client.get_stock_entry(entry_id)
        changes = {
            "amount": amount,
            "best_before_date": best_before_date,
            "price": price,
            "purchased_date": purchased_date,
            "open": None if open is None else int(open),
        }
        if location is not None:
            changes["location_id"] = await _existing_location_id(client, location)
        changes = {k: v for k, v in changes.items() if v is not None}

        # Grocy writes back every field it is sent and clears the ones it is not, so everything
        # the entry has (including its note) is sent again.
        keep = (
            "amount",
            "best_before_date",
            "purchased_date",
            "price",
            "location_id",
            "open",
            "note",
            "shopping_location_id",
        )
        payload = {k: current[k] for k in keep if current.get(k) is not None}
        payload.update(changes)
        await client.update_stock_entry(entry_id, payload)

    def show(value: object) -> str:
        return format_amount(value) if isinstance(value, float) else str(value)

    diffs = [
        f"{k} {show(current.get(k))} -> {show(v)}"
        for k, v in changes.items()
        if current.get(k) != v
    ]
    detail = "; ".join(diffs) if diffs else "no change"
    return f"Updated stock entry {entry_id}: {detail}."


async def stock_undo(client: GrocyClient, booking_id: int) -> str:
    """Reverse a stock booking (a stock journal entry). This rewrites history.

    The booking's product is looked up first so the undo runs under the same per-product lock as
    consume, transfer, inventory, opening and entry edits; otherwise it could race with them.
    """
    try:
        booking = await client.get_object("stock_log", booking_id)
    except GrocyNotFoundError as e:
        raise GrocyValidationError(
            f"Could not undo booking {booking_id}: it does not exist. "
            "Booking IDs are the numbers in brackets in stock_journal_tool."
        ) from e
    async with _product_lock(booking["product_id"]):
        try:
            await client.undo_booking(booking_id)
        except GrocyValidationError as e:
            raise GrocyValidationError(
                f"Could not undo booking {booking_id}: it may already be undone ({e})."
            ) from e
    return f"Undid booking {booking_id}."
