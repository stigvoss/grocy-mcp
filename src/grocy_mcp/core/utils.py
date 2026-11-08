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


AMOUNT_DECIMALS = 6


def tidy_amount(value: object) -> float | None:
    """Round an amount to remove float noise (e.g. 1.0000000000000007); None if not a number."""
    try:
        return round(float(value), AMOUNT_DECIMALS) + 0.0
    except (TypeError, ValueError):
        return None


def format_amount(value: float) -> str:
    """Format with up to six decimals and no trailing zeros (``g`` would cut significant digits).

    Rounds first, so float residue of either sign (``-2.2e-16``) shows as ``0``, never ``-0``.
    """
    value = round(float(value), AMOUNT_DECIMALS) + 0.0
    return f"{value:.{AMOUNT_DECIMALS}f}".rstrip("0").rstrip(".")


def zero_rows_note(hidden: int) -> str:
    """Line that tells the reader float-noise rows were left out."""
    return f"({hidden} zero-amount row{'' if hidden == 1 else 's'} hidden)"
