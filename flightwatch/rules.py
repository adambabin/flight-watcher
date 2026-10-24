"""GoWild pass rules.

Domestic GoWild fares open the day before departure, usually around midnight in the
departure airport's local time. International ones open 10 days out (not tracked here).

Blackout dates have no GoWild fares at all. They come from Frontier's GoWild page
(flyfrontier.com/deals/gowild-pass) and are posted per pass period; add new ones to
BLACKOUTS as Frontier publishes them.
"""
from datetime import date


def _expand(year, spec):
    out = set()
    for month, days in spec.items():
        for part in days.split(","):
            a, _, b = part.strip().partition("-")
            out.update(date(year, month, d) for d in range(int(a), int(b or a) + 1))
    return out


BLACKOUTS = (
    _expand(2026, {1: "1,3-4,15-16,19", 2: "12-13,16", 3: "13-15,20-22,27-29", 4: "3-6,10-12",
                   5: "21-22,25", 6: "25-28", 7: "2-6", 9: "3-4,7", 10: "8-9,11-12",
                   11: "24-25,28-30", 12: "19-24,26-31"})
    | _expand(2027, {1: "1-3,14-15,18", 2: "11-12,15", 3: "12-14,19-21,26-29", 4: "2-4"})
)
BLACKOUTS_POSTED_THROUGH = date(2027, 4, 30)


def is_blackout(d):
    return d in BLACKOUTS
