"""Time zones for Frontier's US stations.

GoWild seats open around midnight in the *departure* airport's time zone, so every
time we show for a route is in its origin's zone. Unknown airports fall back to the
time zone in settings.
"""
from zoneinfo import ZoneInfo

_ZONES = {
    "America/New_York": "ATL BDL BOS BUF BWI CHS CLE CLT CMH CVG DCA DTW EWR FLL GSP IAD ILM "
                        "ISP JAX JFK LGA MCO MIA MYR ORF PBI PHL PIT PVD RDU RIC ROC SAV SDF "
                        "SRQ SYR TPA TYS IND RSW ALB",
    "America/Chicago": "ORD MDW IAH HOU DFW DAL AUS SAT MSP MSY MCI STL MKE BNA MEM OKC TUL "
                       "OMA DSM LIT XNA SGF MSN GRB CID ICT MOB BHM HSV PNS",
    "America/Denver": "DEN SLC ABQ BOI BIL BZN COS JAC ELP",
    "America/Phoenix": "PHX TUS",
    "America/Los_Angeles": "LAX SFO SAN LAS ONT SNA SJC SMF OAK PDX SEA BUR GEG RNO PSP",
    "America/Anchorage": "ANC",
    "Pacific/Honolulu": "HNL OGG",
    "America/Puerto_Rico": "SJU BQN PSE STT STX",
}

AIRPORT_TZ = {code: zone for zone, codes in _ZONES.items() for code in codes.split()}


def airport_tz(code, fallback):
    return ZoneInfo(AIRPORT_TZ.get(code.upper(), fallback))
