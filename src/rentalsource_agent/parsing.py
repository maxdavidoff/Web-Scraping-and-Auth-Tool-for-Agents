from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

PRICE_RE = re.compile(r"\$\s?[\d,]+(?:\s*(?:-|to)\s*\$?\s?[\d,]+|\+)?", re.I)
BED_RE = re.compile(r"\b(?:studio|\d+(?:\.\d+)?\s*(?:br|bed|beds|bedroom|bedrooms))\b", re.I)
BATH_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:bath|baths|bathroom|bathrooms)\b", re.I)
SQFT_RE = re.compile(
    r"\b[\d,]+(?:\s*-\s*[\d,]+)?\s*(?:sq\.?\s*ft\.?|sqft|ft2|ft\^2|ft)\b",
    re.I,
)
LOCATION_RE = re.compile(
    r"\b[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b"
)
PROPERTY_TYPE_RE = re.compile(r"\b(?:Apartment|House|Townhouse|Condo|Duplex|Studio)\b", re.I)


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def guess_title(raw_text: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return ""

    for line in lines:
        if PRICE_RE.search(line):
            continue
        if line.lower().startswith(("managed by", "updated", "featured", "verified")):
            continue
        if len(line) >= 6:
            return line[:160]

    return lines[0][:160]


def guess_price(raw_text: str) -> str:
    match = PRICE_RE.search(raw_text)
    return clean_text(match.group(0)) if match else ""


def guess_bedrooms(raw_text: str) -> str:
    match = BED_RE.search(raw_text)
    return clean_text(match.group(0)) if match else ""


def guess_bathrooms(raw_text: str) -> str:
    match = BATH_RE.search(raw_text)
    return clean_text(match.group(0)) if match else ""


def guess_square_feet(raw_text: str) -> str:
    match = SQFT_RE.search(raw_text)
    return clean_text(match.group(0)) if match else ""


def guess_location(raw_text: str) -> str:
    for line in raw_text.splitlines():
        match = LOCATION_RE.search(clean_text(line))
        if match:
            return clean_text(match.group(0))

    match = LOCATION_RE.search(clean_text(raw_text))
    return clean_text(match.group(0)) if match else ""


def guess_property_type(raw_text: str) -> str:
    match = PROPERTY_TYPE_RE.search(raw_text)
    return clean_text(match.group(0)).title() if match else ""


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
    property_type: str = "",
) -> dict:
    raw_text_clean = clean_text(raw_text)
    absolute_url = urljoin(base_url, url) if url else source_url
    images = [urljoin(base_url, image) for image in (image_urls or []) if image]
    title_clean = clean_text(title)

    record = {
        "id": stable_id(absolute_url, raw_text_clean),
        "source": "rentalsource",
        "title": title_clean or guess_title(raw_text),
        "price": clean_text(price) or guess_price(raw_text),
        "property_type": guess_property_type(property_type) or guess_property_type(raw_text),
        "location": clean_text(location) or guess_location(raw_text),
        "bedrooms": guess_bedrooms(raw_text),
        "bathrooms": guess_bathrooms(raw_text),
        "square_feet": guess_square_feet(raw_text),
        "url": absolute_url,
        "image_urls": list(dict.fromkeys(images)),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "raw_text": raw_text_clean,
    }
    return record
