"""Per-product usage statistics built from the Grocy stock journal."""

from __future__ import annotations

import itertools
import statistics
from datetime import UTC, datetime, timedelta

from grocy_mcp.client import GrocyClient
from grocy_mcp.core.resolve import resolve_product
from grocy_mcp.core.utils import parse_datetime, tidy_amount
from grocy_mcp.exceptions import GrocyValidationError

_MAX_DAYS = 3650


def _gaps_in_days(dates: list[datetime]) -> list[int]:
    """Whole days between consecutive distinct event dates (oldest first)."""
    days = sorted({d.date() for d in dates})
    return [(b - a).days for a, b in itertools.pairwise(days)]


def _gap_summary(dates: list[datetime]) -> dict:
    gaps = _gaps_in_days(dates)
    return {
        "median_gap_days": statistics.median(gaps) if gaps else None,
        "last_gap_days": gaps[-1] if gaps else None,
    }


async def stock_usage_stats_data(
    client: GrocyClient,
    product: str,
    days: int = 90,
    now: datetime | None = None,
) -> dict:
    """Summarise a product's purchases, consumption and opens over the last ``days`` days.

    Built from the stock journal: undone bookings and rows that round to zero (float residue) are
    ignored. Dates are the journal's creation timestamps. ``avg_daily_use`` is the amount
    consumed (spoiled units excluded) divided by ``days``.
    """
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= _MAX_DAYS:
        raise GrocyValidationError(f"days must be a whole number between 1 and {_MAX_DAYS}.")
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)

    product_id = await resolve_product(client, product)
    info = await client.get_stock_product(product_id)
    name = (info.get("product") or {}).get("name", f"Product {product_id}")
    rows = await client.get_objects("stock_log", f"product_id={product_id}")

    entries = []
    for row in rows:
        amount = tidy_amount(row.get("amount"))
        when = parse_datetime(row.get("row_created_timestamp"))
        if not amount or when is None or int(row.get("undone") or 0):
            continue
        entries.append((when, row.get("transaction_type"), amount, row))
    entries.sort(key=lambda e: e[0])

    in_window = [e for e in entries if e[0] >= since]
    purchases = [e for e in in_window if e[1] == "purchase"]
    consumes = [e for e in in_window if e[1] == "consume"]
    opens = [e for e in in_window if e[1] == "product-opened"]
    used = [e for e in consumes if not int(e[3].get("spoiled") or 0)]
    spoiled = [e for e in consumes if int(e[3].get("spoiled") or 0)]

    prices = [(abs(a), float(r["price"])) for _, _, a, r in purchases if r.get("price") is not None]
    last_movement = entries[-1][0] if entries else None

    return {
        "product": name,
        "product_id": product_id,
        "window_days": days,
        "current_stock": tidy_amount(info.get("stock_amount")),
        "purchases": {
            "count": len(purchases),
            "total_amount": round(sum(abs(a) for _, _, a, _ in purchases), 6),
            "dates": [w.date().isoformat() for w, *_ in purchases],
            "total_spent": round(sum(a * p for a, p in prices), 2) if prices else None,
            "average_unit_price": (
                round(sum(a * p for a, p in prices) / sum(a for a, _ in prices), 4)
                if prices
                else None
            ),
            **_gap_summary([w for w, *_ in purchases]),
        },
        "consumes": {
            "count": len(used),
            "total_amount": round(sum(abs(a) for _, _, a, _ in used), 6),
            "spoiled_count": len(spoiled),
            "spoiled_amount": round(sum(abs(a) for _, _, a, _ in spoiled), 6),
            **_gap_summary([w for w, *_ in used]),
        },
        "opens": {
            "count": len(opens),
            "total_amount": round(sum(abs(a) for _, _, a, _ in opens), 6),
            **_gap_summary([w for w, *_ in opens]),
        },
        "average_daily_use": round(sum(abs(a) for _, _, a, _ in used) / days, 6),
        "last_movement": last_movement.isoformat() if last_movement else None,
        "days_since_last_movement": (now - last_movement).days if last_movement else None,
    }
