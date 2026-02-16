"""Command layer utilities shared across CLI handlers."""

import sys

_STALE_THRESHOLD_DAYS = 30


def warn_if_stale(db, threshold_days: int = _STALE_THRESHOLD_DAYS) -> None:
    """Emit a stderr warning if the database cache is older than *threshold_days*."""
    from ..database import get_cache_age_days

    age = get_cache_age_days(db)
    if age is not None and age > threshold_days:
        days = int(age)
        print(
            f"Warning: Database last refreshed {days} days ago. "
            f"Run 'repoindex refresh' for current data.",
            file=sys.stderr,
        )
