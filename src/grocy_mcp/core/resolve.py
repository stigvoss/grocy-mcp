"""Name-to-ID resolution for Grocy entities."""

from __future__ import annotations

from grocy_mcp.client import GrocyClient
from grocy_mcp.exceptions import GrocyResolveError


def is_numeric_id(text: str) -> bool:
    """True for plain ASCII digits. ``str.isdigit()`` is also true for characters such as
    ``'²'`` that ``int()`` cannot parse, which would crash instead of being looked up by name."""
    return text.isascii() and text.isdigit()


async def resolve_entity(
    client: GrocyClient,
    entity: str,
    name_or_id: str,
    name_field: str = "name",
) -> int:
    if is_numeric_id(name_or_id):
        return int(name_or_id)

    items = await client.get_objects(entity)
    query_lower = name_or_id.lower()

    matches = [item for item in items if query_lower in item.get(name_field, "").lower()]

    if not matches:
        all_names = [item.get(name_field, "?") for item in items[:10]]
        suggestion = ", ".join(all_names)
        raise GrocyResolveError(
            f"No {entity} found matching '{name_or_id}'. Available: {suggestion}"
        )

    if len(matches) == 1:
        return matches[0]["id"]

    exact = [m for m in matches if m.get(name_field, "").lower() == query_lower]
    if len(exact) == 1:
        return exact[0]["id"]

    names = [f"{m.get(name_field)} (ID {m['id']})" for m in matches]
    raise GrocyResolveError(
        f"Multiple {entity} match '{name_or_id}': {', '.join(names)}. Please be more specific."
    )


async def resolve_product(client: GrocyClient, name_or_id: str) -> int:
    return await resolve_entity(client, "products", name_or_id)


async def resolve_recipe(client: GrocyClient, name_or_id: str) -> int:
    return await resolve_entity(client, "recipes", name_or_id)


async def resolve_chore(client: GrocyClient, name_or_id: str) -> int:
    return await resolve_entity(client, "chores", name_or_id)


async def resolve_location(client: GrocyClient, name_or_id: str) -> int:
    return await resolve_entity(client, "locations", name_or_id)


async def resolve_battery(client: GrocyClient, name_or_id: str) -> int:
    return await resolve_entity(client, "batteries", name_or_id)


async def resolve_equipment(client: GrocyClient, name_or_id: str) -> int:
    return await resolve_entity(client, "equipment", name_or_id)
