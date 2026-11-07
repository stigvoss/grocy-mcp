"""Shared utility functions for Grocy core modules."""

from __future__ import annotations

from datetime import UTC, date, datetime

_DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
]


def parse_datetime(value: str | None) -> datetime | None:
    """Parse a datetime string from Grocy, returning None if unparseable."""
    if not value:
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def is_iso_date(value: str) -> bool:
    """Return True only for strict ``YYYY-MM-DD`` dates (not compact or week-date forms)."""
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False
