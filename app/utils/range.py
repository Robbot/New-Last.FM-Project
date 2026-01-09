from __future__ import annotations
from datetime import date, timedelta
import calendar

def parse_ymd(s: str) -> date:
    return date.fromisoformat(s)

def end_of_month(d: date) -> date:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last_day)

def end_of_year(d: date) -> date:
    return date(d.year, 12, 31)

def compute_range(from_s: str | None, to_s: str | None, rangetype: str | None) -> tuple[str | None, str | None]:
    """
    Returns (from_ymd, to_ymd) as ISO strings (YYYY-MM-DD), inclusive.
    - If to is provided -> use it.
    - Else derive to from rangetype (1day/1month/year).
    """
    if not from_s:
        return None, None

    d_from = parse_ymd(from_s)

    if to_s:
        d_to = parse_ymd(to_s)
        return d_from.isoformat(), d_to.isoformat()

    rt = (rangetype or "").strip().lower()

    if rt == "1day":
        d_to = d_from
    elif rt == "1month":
        d_to = end_of_month(d_from)
    elif rt == "year":
        d_to = end_of_year(d_from)
    else:
        # fallback if rangetype missing: treat as single day
        d_to = d_from

    return d_from.isoformat(), d_to.isoformat()
