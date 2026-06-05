"""Unified duration / timestamp parser for repoindex.

Single source of truth for the ``--since`` / ``--recent`` style strings used by
events, digest, refresh, and the flag-query builder. Returns the cutoff
datetime (now minus the parsed duration), or the parsed absolute datetime for
ISO inputs.

Token semantics (locked, v2.1):
    s, sec   seconds
    min      minutes
    h        hours
    d        days
    w        weeks
    m, M     months (approximated as 30 days)
    y        years  (approximated as 365 days)

Note: ``m`` means MONTHS (not minutes); use ``min`` for minutes. Invalid input
raises ``ValueError`` with no silent fallback.
"""

import re
from datetime import datetime, timedelta
from typing import Optional

# Order matters: longer suffixes ('sec', 'min') are matched before single
# letters so '30sec' is seconds and '15min' is minutes.
_RELATIVE_RE = re.compile(r"^(\d+)\s*(sec|min|s|h|d|w|m|M|y)$")

_UNIT_TO_TIMEDELTA = {
    "s": lambda n: timedelta(seconds=n),
    "sec": lambda n: timedelta(seconds=n),
    "min": lambda n: timedelta(minutes=n),
    "h": lambda n: timedelta(hours=n),
    "d": lambda n: timedelta(days=n),
    "w": lambda n: timedelta(weeks=n),
    "m": lambda n: timedelta(days=n * 30),
    "M": lambda n: timedelta(days=n * 30),
    "y": lambda n: timedelta(days=n * 365),
}


def parse_since(spec: str, now: Optional[datetime] = None) -> datetime:
    """Parse a duration or ISO timestamp into a cutoff datetime.

    Args:
        spec: A relative duration ('7d', '6m', '15min', '24h', '1y') or an ISO
            date / datetime ('2024-01-15', '2024-01-15T10:30:00').
        now: Reference time for relative durations. Defaults to ``datetime.now()``.

    Returns:
        For a relative duration, ``now - duration``. For an ISO input, the
        parsed datetime.

    Raises:
        ValueError: If ``spec`` is empty or cannot be parsed. There is no
            silent default.
    """
    if now is None:
        now = datetime.now()

    if spec is None:
        raise ValueError("Cannot parse empty time specification")

    s = spec.strip().strip("'\"")
    if not s:
        raise ValueError("Cannot parse empty time specification")

    match = _RELATIVE_RE.match(s)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        return now - _UNIT_TO_TIMEDELTA[unit](amount)

    # Absolute ISO datetime (handles both date and datetime forms).
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass

    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        pass

    raise ValueError(f"Cannot parse time specification: {spec}")
