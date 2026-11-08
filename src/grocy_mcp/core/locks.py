"""In-process locks shared by the core modules.

``asyncio.Lock`` objects belong to one event loop, so each registry is keyed by the running loop.
Both levels are weak: a closed loop and idle locks are dropped, while a caller that is waiting for
or holding a lock keeps it alive for the duration of its ``async with``.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Hashable

LockRegistry = weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, weakref.WeakValueDictionary[Hashable, asyncio.Lock]
]


def new_registry() -> LockRegistry:
    return weakref.WeakKeyDictionary()


def keyed_lock(registry: LockRegistry, key: Hashable) -> asyncio.Lock:
    """Return the lock for ``key`` on the running event loop, creating it on first use."""
    locks = registry.setdefault(asyncio.get_running_loop(), weakref.WeakValueDictionary())
    lock = locks.get(key)
    if lock is None:
        lock = locks[key] = asyncio.Lock()
    return lock
