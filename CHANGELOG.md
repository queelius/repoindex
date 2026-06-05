# Changelog

All notable changes to repoindex are documented here.

## Unreleased

### Changed (behavior)

- Duration tokens are now parsed by a single shared parser
  (`repoindex/services/timespec.py`, `parse_since`). The token `m` now means
  MONTHS everywhere; use `min` for minutes. This silently changes
  `repoindex events --since 6m` and `repoindex digest --since 6m` from six
  minutes to six months. Supported tokens: `s`/`sec` (seconds), `min`
  (minutes), `h` (hours), `d` (days), `w` (weeks), `m`/`M` (months, approximated
  as 30 days), `y` (years, approximated as 365 days).
- Invalid duration strings now raise an error instead of silently falling back
  to a default window (the old `events` 7d, `refresh` 90d, and `--recent` 30d
  silent fallbacks were footguns). Click option defaults (`events --since 7d`,
  `refresh --since 90d`, `digest --since 7d`) are unchanged.
