from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_COCOA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def apple_date_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    if n == 0:
        return None
    if abs(n) > 10**14:
        seconds = n / 1_000_000_000
    elif abs(n) > 10**11:
        seconds = n / 1_000
    else:
        seconds = float(n)
    # Prefer timedelta from Cocoa epoch — avoids Windows fromtimestamp limits
    # on pre-1970 / far-future values.
    if seconds > 978307200:  # looks like unix seconds already
        try:
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    else:
        try:
            from datetime import timedelta

            dt = _COCOA_EPOCH + timedelta(seconds=seconds)
        except (OverflowError, ValueError):
            return None
    return dt.replace(microsecond=0).isoformat()


def unix_seconds_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    if n <= 0:
        return None
    return datetime.fromtimestamp(n, tz=timezone.utc).replace(microsecond=0).isoformat()
