"""Read-only client for Frontier's public booking site.

Frontier has no public API. Its flight-select page (the one a logged-out visitor sees
after searching) embeds a JSON blob, FlightData, with every itinerary and, per
itinerary, whether a GoWild fare is open, its price, and the "N seats left" text.
No pass login is needed to read it.

The site sits behind DataDome bot protection, which tolerates one steady visitor but
blocks bursts. So: one Chrome-fingerprinted session, one request at a time, a few
seconds apart.
"""
import html
import json
import random
import re
import time
import urllib.parse

BASE = "https://booking.flyfrontier.com"
MIN_GAP = 4.0
MAX_GAP = 7.0


class FrontierError(Exception):
    """Frontier refused or returned something we can't read. `blocked` = bot wall / rate limit."""

    def __init__(self, msg, status=None, blocked=False):
        super().__init__(msg)
        self.status = status
        self.blocked = blocked


def search_url(origin, dest, d):
    q = urllib.parse.urlencode({"o1": origin, "d1": dest, "dd1": d.strftime("%b %d, %Y"),
                                "ADT": 1, "mon": "true", "promo": ""})
    return f"{BASE}/Flight/InternalSelect?{q}"


class Frontier:
    def __init__(self, session_factory=None, sleep=time.sleep):
        self._session_factory = session_factory or _chrome_session
        self._session = None
        self._sleep = sleep
        self._last_request = 0.0

    def reset(self):
        """Drop cookies and start over; sometimes enough to get past a soft block."""
        self._session = None

    def _get(self, url):
        wait = self._last_request + random.uniform(MIN_GAP, MAX_GAP) - time.time()
        if wait > 0:
            self._sleep(wait)
        if self._session is None:
            self._session = self._session_factory()
        try:
            r = self._session.get(url, timeout=40, allow_redirects=True)
        except Exception as e:
            raise FrontierError(f"network error: {e}") from None
        finally:
            self._last_request = time.time()
        if r.status_code != 200:
            body = (r.text or "")[:500].lower()
            blocked = r.status_code in (403, 405, 406, 429) or "captcha" in body or "datadome" in body
            raise FrontierError(f"HTTP {r.status_code} from Frontier", r.status_code, blocked)
        return r.text

    def search(self, origin, dest, d):
        """All itineraries Frontier lists for origin->dest on date d. See parse_select_page."""
        return parse_select_page(self._get(search_url(origin, dest, d)))


def _chrome_session():
    from curl_cffi import requests as cffi

    s = cffi.Session(impersonate="chrome")
    s.headers.update({"Accept-Language": "en-US,en;q=0.9"})
    return s


# ---------------------------------------------------------------- parsing

_FLIGHTDATA_RE = re.compile(r"FlightData\s*=\s*'(.*?)';", re.S)


def _enclosing_object(text, pos):
    """The {...} that contains text[pos], found by brace matching (ignores braces in strings)."""
    depth = 0
    for start in range(pos, -1, -1):
        c = text[start]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
    else:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _extract_flight_data(page):
    m = _FLIGHTDATA_RE.search(page)
    if m:
        try:
            return json.loads(html.unescape(m.group(1)))
        except ValueError:
            pass
    # Fallback: the same JSON entity-escaped somewhere else in the page.
    decoded = html.unescape(page)
    k = decoded.find('"journeys"')
    if k >= 0:
        frag = _enclosing_object(decoded, k)
        if frag:
            try:
                return json.loads(frag)
            except ValueError:
                pass
    low = page.lower()
    raise FrontierError("no flight data on select page",
                        blocked="captcha" in low or "datadome" in low)


def _price(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, 2) if v > 0 else None


def _seats(text):
    """'2 Seats Left!' -> 2. None when Frontier shows no count (usually: more than a handful)."""
    m = re.search(r"(\d+)", str(text)) if text else None
    return int(m.group(1)) if m else None


def parse_select_page(page):
    """Normalize the select page into
    {'flights': [...], 'out_of_range': bool|None, 'lowest_gowild': float|None}.

    Each flight: flight ("F9 1234" or "F9 1234+F9 567"), dep/arr (local ISO), stops,
    gowild (bool), price, seats (int|None), seats_text, standard (price).
    """
    data = _extract_flight_data(page)
    flights = []
    for j in data.get("journeys") or []:
        if j.get("isReturnTrip"):
            continue
        for f in j.get("flights") or []:
            legs = f.get("legs") or []
            if not legs:
                continue
            gw_on = bool(f.get("isGoWildFareEnabled"))
            price = _price(f.get("goWildFare")) if gw_on else None
            flights.append({
                "flight": "+".join(f"{l.get('carrierCode') or 'F9'} {l.get('flightNumber')}" for l in legs),
                "dep": legs[0].get("departureDate"),
                "arr": legs[-1].get("arrivalDate"),
                "stops": len(legs) - 1,
                "gowild": gw_on and price is not None,
                "price": price,
                "seats": _seats(f.get("goWildFareSeatsRemaining")) if gw_on else None,
                "seats_text": f.get("goWildFareSeatsRemaining") if gw_on else None,
                "standard": _price(f.get("standardFare")),
            })
    flights.sort(key=lambda x: x["dep"] or "")
    oor = data.get("isGoWildOutOfRange")
    return {
        "flights": flights,
        "out_of_range": None if oor is None else bool(oor),
        "lowest_gowild": _price(data.get("lowestGWAmount")),
    }
