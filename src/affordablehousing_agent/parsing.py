from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from src.housing_agent.listing_parsing import add_structured_listing_fields

PRICE_RE = re.compile(
    r"\$\s?[\d,]+(?:\s*-\s*\$\s?[\d,]+)?(?:\s*/\s?(?:mo|month|m|week|wk|night|day))?",
    re.I,
)
BED_RE = re.compile(r"\b(?:studio(?:-\d+)?|\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?)\s*beds?\b", re.I)
BATH_RE = re.compile(r"\b\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s*baths?\b", re.I)
SQFT_RE = re.compile(r"\b\d[\d,]*(?:\s*-\s*\d[\d,]*)?\s*sqft\b", re.I)
AVAILABILITY_RE = re.compile(r"\b(?:Available Now|Available Soon|Waiting List)\b", re.I)
PROPERTY_TYPE_RE = re.compile(
    r"\b(?:Apartment|Apartments|House|Houses|Single Family House|Townhouse|Townhouses|Condo|Condos)\b",
    re.I,
)


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _first_match(pattern: re.Pattern[str], raw_text: str) -> str:
    match = pattern.search(raw_text)
    return clean_text(match.group(0)) if match else ""


def guess_title(raw_text: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    skip_patterns = [PRICE_RE, BED_RE, BATH_RE, SQFT_RE, AVAILABILITY_RE]
    for line in lines:
        if len(line) < 4:
            continue
        if any(pattern.fullmatch(line) for pattern in skip_patterns):
            continue
        if line.lower() in {"trusted owner", "income restricted", "lease incentives"}:
            continue
        return line[:160]
    return lines[0][:160] if lines else ""


def guess_price(raw_text: str) -> str:
    return _first_match(PRICE_RE, raw_text)


def guess_bedrooms(raw_text: str) -> str:
    return normalize_bedrooms(_first_match(BED_RE, raw_text))


def normalize_bedrooms(text: str) -> str:
    bedrooms = clean_text(text)
    return re.sub(r"\bStud(?=\b|-)", "Studio", bedrooms, flags=re.I)


def guess_bathrooms(raw_text: str) -> str:
    return _first_match(BATH_RE, raw_text)


def guess_sqft(raw_text: str) -> str:
    return _first_match(SQFT_RE, raw_text)


def guess_availability(raw_text: str) -> str:
    return _first_match(AVAILABILITY_RE, raw_text)


def guess_property_type(raw_text: str) -> str:
    return _first_match(PROPERTY_TYPE_RE, raw_text)


def stable_id(url: str, raw_text: str) -> str:
    base = url or raw_text[:500]
    return hashlib.sha256(base.encode("utf-8", errors="ignore")).hexdigest()[:16]


def normalize_listing(
    *,
    raw_text: str,
    source_url: str,
    base_url: str,
    title: str = "",
    price: str = "",
    location: str = "",
    url: str = "",
    image_urls: list[str] | None = None,
    availability: str = "",
    bedrooms: str = "",
    bathrooms: str = "",
    sqft: str = "",
    property_type: str = "",
) -> dict:
    raw_text_clean = clean_text(raw_text)
    absolute_url = urljoin(base_url, url) if url else source_url
    images = [urljoin(base_url, image) for image in (image_urls or []) if image]

    record = {
        "id": stable_id(url, raw_text_clean),
        "source": "affordablehousing",
        "title": clean_text(title) or guess_title(raw_text),
        "price": clean_text(price) or guess_price(raw_text),
        "location": clean_text(location),
        "availability": clean_text(availability) or guess_availability(raw_text),
        "bedrooms": normalize_bedrooms(bedrooms) or guess_bedrooms(raw_text),
        "bathrooms": clean_text(bathrooms) or guess_bathrooms(raw_text),
        "sqft": clean_text(sqft) or guess_sqft(raw_text),
        "property_type": clean_text(property_type) or guess_property_type(raw_text),
        "url": absolute_url,
        "image_urls": list(dict.fromkeys(images)),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "raw_text": raw_text_clean,
    }
    return add_structured_listing_fields(record)
