"""Dates the Ministry's way, shared by letters, check messages and (later) the frontend's rules."""

import calendar
from datetime import date


def _ordinal(n: int) -> str:
    # 11th, 12th and 13th break the 1st/2nd/3rd pattern.
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def long_date(day: date) -> str:
    """The Ministry's format: "16th September, 2026"."""
    return f"{_ordinal(day.day)} {day:%B}, {day.year}"


def add_months(day: date, months: int) -> date:
    """The same day `months` later; the month's last day when it has no such
    day (31st August + 6 months = 28th or 29th February)."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
