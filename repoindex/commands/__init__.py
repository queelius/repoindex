"""Command layer utilities shared across CLI handlers."""

import sys

import click

_STALE_THRESHOLD_DAYS = 30


class TimeSpecParam(click.ParamType):
    """Validate --since/--recent style values at the CLI boundary.

    Downstream services re-parse the raw string, so this returns the value
    unchanged; it exists to turn parse_since's ValueError into a usage error
    instead of a traceback.
    """

    name = 'timespec'

    def convert(self, value, param, ctx):
        if value is None:
            return value
        from ..services.timespec import parse_since

        try:
            parse_since(value)
        except ValueError as exc:
            self.fail(str(exc), param, ctx)
        return value


TIMESPEC = TimeSpecParam()


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
