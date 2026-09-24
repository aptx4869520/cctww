from __future__ import annotations

import re
import time
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import Lock
from typing import Callable

import requests
from urllib3.exceptions import InsecureRequestWarning

from backend.schema import CCTV


NLSC_TOWN_LOOKUP_URL = (
    "https://api.nlsc.gov.tw/other/TownVillagePointQuery1/{lon}/{lat}/4326"
)
LOCATION_LOOKUP_TIMEOUT_SECONDS = (1.5, 2.0)
LOCATION_CACHE_TTL_SECONDS = 24 * 60 * 60
LOCATION_FAILURE_CACHE_TTL_SECONDS = 5 * 60

_MILEAGE_AT_START = re.compile(r"^\s*0*\d{1,3}K(?:\+\d+|\.\d+)?", re.IGNORECASE)
_ROUTE_AND_MILEAGE_ONLY = re.compile(
    r"^\s*(?:台|臺|國|縣|市|鄉)?[^\s()]{0,12}?\s*"
    r"\d{1,3}K(?:\+\d+|\.\d+)?"
    r"(?:[-_\s]*(?:東|西|南|北|N|S|E|W|NE|NW|SE|SW|向))*"
    r"(?:\([^)]*向?\))?\s*$",
    re.IGNORECASE,
)
_CAMERA_CODE = re.compile(r"^\s*(?:CCTV|T\d+)(?:[-_.][A-Z0-9]+)+\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class _CachedTown:
    expires_at: float
    town_name: str | None


_town_cache: dict[tuple[str, str], _CachedTown] = {}
_town_cache_lock = Lock()


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def needs_location_enrichment(description: str | None) -> bool:
    """Return True only for descriptions that are hard to guess from."""
    value = _clean_text(description)
    if not value:
        return True
    return bool(
        _MILEAGE_AT_START.search(value)
        or _ROUTE_AND_MILEAGE_ONLY.fullmatch(value)
        or _CAMERA_CODE.fullmatch(value)
    )


def _normalise_coordinate(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def resolve_town_from_coordinates(lon: object, lat: object) -> str | None:
    """Resolve a Taiwan township through NLSC; failures intentionally return None."""
    longitude = _normalise_coordinate(lon)
    latitude = _normalise_coordinate(lat)
    if longitude is None or latitude is None:
        return None
    if not (Decimal("118") <= longitude <= Decimal("123")):
        return None
    if not (Decimal("21") <= latitude <= Decimal("26.5")):
        return None

    lon_key = format(longitude.quantize(Decimal("0.000001")), "f")
    lat_key = format(latitude.quantize(Decimal("0.000001")), "f")
    cache_key = (lon_key, lat_key)
    now = time.monotonic()
    with _town_cache_lock:
        cached = _town_cache.get(cache_key)
        if cached is not None and cached.expires_at > now:
            return cached.town_name

    town_name: str | None = None
    try:
        request_url = NLSC_TOWN_LOOKUP_URL.format(lon=lon_key, lat=lat_key)
        request_options = {
            "headers": {
                "Accept": "application/xml",
                "User-Agent": "CCTWW/1.0 location-label-resolver",
            },
            "timeout": LOCATION_LOOKUP_TIMEOUT_SECONDS,
        }
        try:
            response = requests.get(request_url, **request_options)
        except requests.exceptions.SSLError as exc:
            # The official NLSC endpoint currently serves a certificate that
            # Python 3.13 rejects for this specific legacy extension. Retry
            # only that known certificate error and only against the fixed
            # government endpoint above.
            if "Missing Subject Key Identifier" not in str(exc):
                raise
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                response = requests.get(request_url, verify=False, **request_options)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        town_name = _clean_text(root.findtext(".//townName")) or None
    except (requests.RequestException, ET.ParseError, ValueError):
        town_name = None

    ttl = (
        LOCATION_CACHE_TTL_SECONDS
        if town_name is not None
        else LOCATION_FAILURE_CACHE_TTL_SECONDS
    )
    with _town_cache_lock:
        _town_cache[cache_key] = _CachedTown(now + ttl, town_name)
    return town_name


def build_cctv_display_name(
    cctv: CCTV,
    *,
    town_resolver: Callable[[object, object], str | None] = resolve_town_from_coordinates,
) -> str:
    """Return a friendlier option label without changing the API response shape."""
    original_name = _clean_text(cctv.cctv_name)
    if not needs_location_enrichment(original_name):
        return original_name

    try:
        town_name = _clean_text(town_resolver(cctv.lon, cctv.lat))
    except Exception:
        town_name = ""
    road_name = _clean_text(cctv.road_name)

    if town_name and road_name:
        return f"{town_name}・{road_name}附近"
    return original_name
