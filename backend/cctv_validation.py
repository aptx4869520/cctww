from __future__ import annotations

import io
import math
import time
import warnings
from dataclasses import dataclass

import requests
from PIL import Image, UnidentifiedImageError
from urllib3.exceptions import InsecureRequestWarning

from backend.schema import CCTV


DARK_MEAN_THRESHOLD = 35.0
DARK_PIXEL_THRESHOLD = 20
DARK_RATIO_THRESHOLD = 0.85
DETAIL_THRESHOLD = 18.0
FLAT_DETAIL_THRESHOLD = 2.0
FLAT_CONTRAST_THRESHOLD = 3.0
MIN_IMAGE_BYTES = 128
MAX_IMAGE_BYTES = 5_000_000
MAX_IMAGE_PIXELS = 4_000_000
SNAPSHOT_CACHE_TTL_SECONDS = 30
QUALITY_DETAIL_TARGET = 100.0
QUALITY_CONTRAST_TARGET = 40.0
QUALITY_BRIGHTNESS_TARGET = 80.0
QUALITY_DARK_RATIO_GOOD = 0.30
# Five bounded attempts must still finish before the frontend's 30-second API
# timeout, including normal DB and image-processing overhead.
REQUEST_TIMEOUT_SECONDS = (2, 3)


class CCTVValidationError(Exception):
    """The CCTV response cannot safely be used as a game image."""


@dataclass(frozen=True)
class CCTVValidationResult:
    image_bytes: bytes
    media_type: str
    width: int
    height: int
    mean_brightness: float
    median_brightness: float
    dark_ratio: float
    detail_score: float
    contrast: float
    quality_score: float


@dataclass(frozen=True)
class _CachedSnapshot:
    expires_at: float
    result: CCTVValidationResult


_snapshot_cache: dict[str, _CachedSnapshot] = {}


def _cache_key(cctv: CCTV) -> str:
    return str(cctv.ID if cctv.ID is not None else cctv.cctvID)


def _reasonable_content_type(content_type: str) -> bool:
    media_type = content_type.partition(";")[0].strip().lower()
    return (
        media_type.startswith("image/")
        or media_type.startswith("multipart/")
        or media_type == "application/octet-stream"
    )


def _read_first_image(response: requests.Response) -> bytes:
    content_type = response.headers.get("content-type", "")
    is_multipart = content_type.lower().startswith("multipart/")
    body = bytearray()

    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > MAX_IMAGE_BYTES:
            raise CCTVValidationError("CCTV image is too large")

        # CCTV streams are commonly multipart MJPEG. One complete JPEG frame is
        # enough for both validation and the game's snapshot response.
        if is_multipart:
            start = body.find(b"\xff\xd8")
            if start >= 0:
                end = body.find(b"\xff\xd9", start + 2)
                if end >= 0:
                    return bytes(body[start : end + 2])

    if not body:
        raise CCTVValidationError("CCTV response body is empty")
    if is_multipart:
        raise CCTVValidationError("CCTV stream did not contain a complete JPEG frame")
    if len(body) < MIN_IMAGE_BYTES:
        raise CCTVValidationError("CCTV image body is too small")
    return bytes(body)


def _laplacian_variance(gray: Image.Image) -> float:
    width, height = gray.size
    if width < 3 or height < 3:
        return 0.0
    pixels = gray.load()
    count = 0
    mean = 0.0
    squared_delta = 0.0
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            value = (
                4 * pixels[x, y]
                - pixels[x - 1, y]
                - pixels[x + 1, y]
                - pixels[x, y - 1]
                - pixels[x, y + 1]
            )
            count += 1
            delta = value - mean
            mean += delta / count
            squared_delta += delta * (value - mean)
    return squared_delta / count if count else 0.0


def _histogram_median(histogram: list[int], pixel_count: int) -> float:
    midpoint = (pixel_count - 1) / 2
    cumulative = 0
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative > midpoint:
            return float(value)
    return 0.0


def _quality_score(
    mean_brightness: float,
    median_brightness: float,
    dark_ratio: float,
    detail_score: float,
    contrast: float,
) -> float:
    """Return an informational 0-100 score; eligibility remains rule based."""
    clamp = lambda value: max(0.0, min(value, 1.0))
    brightness = clamp(mean_brightness / QUALITY_BRIGHTNESS_TARGET)
    median = clamp(median_brightness / QUALITY_BRIGHTNESS_TARGET)
    detail = clamp(math.log1p(detail_score) / math.log1p(QUALITY_DETAIL_TARGET))
    contrast_score = clamp(contrast / QUALITY_CONTRAST_TARGET)
    visibility = clamp(
        (DARK_RATIO_THRESHOLD - dark_ratio)
        / (DARK_RATIO_THRESHOLD - QUALITY_DARK_RATIO_GOOD)
    )
    return round(
        100
        * (
            0.10 * brightness
            + 0.10 * median
            + 0.45 * detail
            + 0.20 * contrast_score
            + 0.15 * visibility
        ),
        2,
    )


def _analyse_image(image_bytes: bytes) -> CCTVValidationResult:
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise CCTVValidationError("CCTV image has invalid dimensions")
            source.load()
            media_type = Image.MIME.get(source.format, "image/jpeg")
            gray = source.convert("L")
    except CCTVValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise CCTVValidationError("CCTV image cannot be decoded") from exc

    gray.thumbnail((320, 240))
    histogram = gray.histogram()
    pixel_count = sum(histogram)
    if not pixel_count:
        raise CCTVValidationError("CCTV image has no pixels")

    mean_brightness = sum(value * count for value, count in enumerate(histogram)) / pixel_count
    median_brightness = _histogram_median(histogram, pixel_count)
    dark_ratio = sum(histogram[:DARK_PIXEL_THRESHOLD]) / pixel_count
    variance = sum(
        ((value - mean_brightness) ** 2) * count
        for value, count in enumerate(histogram)
    ) / pixel_count
    contrast = variance ** 0.5
    detail_score = _laplacian_variance(gray)

    dark_and_indistinct = (
        mean_brightness < DARK_MEAN_THRESHOLD
        and dark_ratio >= DARK_RATIO_THRESHOLD
        and detail_score < DETAIL_THRESHOLD
    )
    uniformly_blank = (
        detail_score < FLAT_DETAIL_THRESHOLD
        and contrast < FLAT_CONTRAST_THRESHOLD
    )
    if dark_and_indistinct or uniformly_blank:
        raise CCTVValidationError("CCTV image is too dark or lacks usable detail")

    return CCTVValidationResult(
        image_bytes=image_bytes,
        media_type=media_type,
        width=width,
        height=height,
        mean_brightness=mean_brightness,
        median_brightness=median_brightness,
        dark_ratio=dark_ratio,
        detail_score=detail_score,
        contrast=contrast,
        quality_score=_quality_score(
            mean_brightness,
            median_brightness,
            dark_ratio,
            detail_score,
            contrast,
        ),
    )


def validate_cctv(cctv: CCTV, *, force_refresh: bool = False) -> CCTVValidationResult:
    """Fetch, decode and score one CCTV snapshot; raises when it is unusable."""
    key = _cache_key(cctv)
    cached = _snapshot_cache.get(key)
    now = time.monotonic()
    if not force_refresh and cached is not None and cached.expires_at > now:
        return cached.result

    source_url = cctv.screenshot_url or cctv.stream_url
    if not source_url:
        raise CCTVValidationError("CCTV image URL is missing")

    try:
        try:
            response = requests.get(
                source_url,
                stream=True,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.exceptions.SSLError as exc:
            # Some official THB cameras use a certificate chain that Python's
            # OpenSSL rejects for a missing Subject Key Identifier. Preserve
            # normal TLS verification for every other certificate failure.
            if "Missing Subject Key Identifier" not in str(exc):
                raise
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                response = requests.get(
                    source_url,
                    stream=True,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    verify=False,
                )

        with response:
            if response.status_code != 200:
                raise CCTVValidationError(f"CCTV returned HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "")
            if not _reasonable_content_type(content_type):
                raise CCTVValidationError("CCTV returned an unsupported content type")
            result = _analyse_image(_read_first_image(response))
    except CCTVValidationError:
        raise
    except requests.RequestException as exc:
        raise CCTVValidationError("CCTV request failed") from exc

    _snapshot_cache[key] = _CachedSnapshot(
        expires_at=now + SNAPSHOT_CACHE_TTL_SECONDS,
        result=result,
    )
    return result
