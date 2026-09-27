# ============================================================
#  macro_calendar.py — Scheduled macro-event entry blackout
#
#  Rules (pre-registered 2026-09-27, risk control — NOT tuned on P&L):
#
#   FOMC statement day (14:00 ET statement, 14:30 press conference):
#     no new entries from FOMC_BLACKOUT_FROM onward. The swing book's
#     4h holds opened after ~13:30 would sit straight through the statement.
#
#   CPI / jobs-report (Employment Situation) day, both released 08:30 ET:
#     - CRT: skip the whole day. The 08:00-09:00 box straddles the release,
#       so the "narrative box" is a news spike, not overnight positioning.
#     - Swing: no new entries before RELEASE_DAY_ENTRIES_FROM — let the
#       release volatility settle before trusting 15-minute signals.
#
#  Open positions are never force-closed by this module; stops still apply.
#  Dates are from federalreserve.gov and bls.gov (see DATE SOURCES below).
#  Extend the lists each year — is_known_year() warns when they run out.
# ============================================================

import logging
from datetime import date, datetime, time

logger = logging.getLogger(__name__)

FOMC_BLACKOUT_FROM      = time(13, 30)
RELEASE_DAY_ENTRIES_FROM = time(10, 0)

# ── DATE SOURCES ──────────────────────────────────────────────
def _d(*isos: str) -> set[date]:
    return {date.fromisoformat(s) for s in isos}


# FOMC statement day (second day of each meeting).
# federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_DATES: set[date] = _d(
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20",
    "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18",
    "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17",
    "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16",
    "2026-10-28", "2026-12-09",
)

# CPI release days, 08:30 ET. bls.gov/schedule/news_release/cpi.htm
# 2025: Sep CPI delayed to 10-24 and Oct CPI cancelled (shutdown); Nov CPI 12-18.
CPI_DATES: set[date] = _d(
    "2023-01-12", "2023-02-14", "2023-03-14", "2023-04-12", "2023-05-10", "2023-06-13",
    "2023-07-12", "2023-08-10", "2023-09-13", "2023-10-12", "2023-11-14", "2023-12-12",
    "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15", "2024-06-12",
    "2024-07-11", "2024-08-14", "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
    "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13", "2025-06-11",
    "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-24", "2025-12-18",
    "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10",
    "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10",
)

# Employment Situation (jobs report) days, 08:30 ET.
# bls.gov/schedule/news_release/empsit.htm
# 2025: Sep report delayed to 11-20, Oct not published, Nov report 12-16.
JOBS_DATES: set[date] = _d(
    "2023-01-06", "2023-02-03", "2023-03-10", "2023-04-07", "2023-05-05", "2023-06-02",
    "2023-07-07", "2023-08-04", "2023-09-01", "2023-10-06", "2023-11-03", "2023-12-08",
    "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03", "2024-06-07",
    "2024-07-05", "2024-08-02", "2024-09-06", "2024-10-04", "2024-11-01", "2024-12-06",
    "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04", "2025-05-02", "2025-06-06",
    "2025-07-03", "2025-08-01", "2025-09-05", "2025-11-20", "2025-12-16",
    "2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08", "2026-06-05",
    "2026-07-02", "2026-08-07", "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
)


def is_known_year(d: date) -> bool:
    return any(x.year == d.year for x in FOMC_DATES) and any(x.year == d.year for x in CPI_DATES)


_warned_years: set[int] = set()


def _check_coverage(d: date) -> None:
    if not is_known_year(d) and d.year not in _warned_years:
        _warned_years.add(d.year)
        logger.warning(f"macro_calendar has no {d.year} dates — blackout inactive; "
                       f"add that year's FOMC/CPI/jobs dates")


def event_labels(d: date) -> list:
    labels = []
    if d in FOMC_DATES: labels.append("FOMC")
    if d in CPI_DATES:  labels.append("CPI")
    if d in JOBS_DATES: labels.append("jobs report")
    return labels


def is_release_day(d: date) -> bool:
    """08:30 ET data-release day (CPI or jobs report)."""
    return d in CPI_DATES or d in JOBS_DATES


def crt_blocked_today(d: date) -> str | None:
    """Reason the CRT model should sit the whole day out, else None."""
    _check_coverage(d)
    if is_release_day(d):
        return f"macro_blackout ({' + '.join(event_labels(d))} 08:30 ET release inside the 08:00-09:00 box)"
    return None


def entry_blocked(now: datetime) -> str | None:
    """Reason new entries are blocked at `now` (ET), else None. Applies to both books."""
    d, t = now.date(), now.time()
    _check_coverage(d)
    if d in FOMC_DATES and t >= FOMC_BLACKOUT_FROM:
        return f"macro_blackout (FOMC statement day, no entries after {FOMC_BLACKOUT_FROM:%H:%M} ET)"
    if is_release_day(d) and t < RELEASE_DAY_ENTRIES_FROM:
        return (f"macro_blackout ({' + '.join(event_labels(d))} day, no entries before "
                f"{RELEASE_DAY_ENTRIES_FROM:%H:%M} ET)")
    return None
