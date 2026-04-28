from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

PRICE_RE = re.compile(r"\$\s?[\d,]+(?:\s*/\s?(?:mo|month|m|week|wk|night|day))?", re.I)
BED_RE = re.compile(r"\b(?:studio|\d+\s*(?:br|bed|beds|bedroom|bedrooms))\b", re.I)
BED_ICON_RE = re.compile(r"(?:^|\n)\s*bed\s*\n\s*(\d+(?:\.\d+)?)\b", re.I)
DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:\s*[-–]\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)?[a-z]*\.?\s*\d{1,2})?\b",
    re.I,
)
ICON_TEXT = {
    "bed",
    "chevron_left",
    "chevron_right",
    "keyboard_arrow_right",
    "shower",
}
TITLE_HINT_RE = re.compile(r"\b(?:room|apartment|house|studio|sublet)\b", re.I)


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def guess_title(raw_text: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return ""
    for line in lines:
        if line.lower() in ICON_TEXT:
            continue
        if PRICE_RE.fullmatch(line) or DATE_RE.search(line):
            continue
        if TITLE_HINT_RE.search(line):
            return line[:160]
    for line in lines:
        if line.lower() in ICON_TEXT:
            continue
        if len(line) >= 8 and not PRICE_RE.fullmatch(line) and not DATE_RE.search(line):
            return line[:160]
    return lines[0][:160]


def guess_price(raw_text: str) -> str:
    match = PRICE_RE.search(raw_text)
    return clean_text(match.group(0)) if match else ""


def guess_bedrooms(raw_text: str) -> str:
    match = BED_RE.search(raw_text)
    if match:
        return clean_text(match.group(0))

    icon_match = BED_ICON_RE.search(raw_text)
    if icon_match:
        number = icon_match.group(1)
        suffix = "bed" if number == "1" else "beds"
        return f"{number} {suffix}"

    return ""


def guess_dates(raw_text: str) -> str:
    matches = DATE_RE.findall(raw_text)
    return " | ".join(dict.fromkeys(clean_text(match) for match in matches if match))


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
) -> dict:
    raw_text_clean = clean_text(raw_text)
    absolute_url = urljoin(base_url, url) if url else source_url
    images = [urljoin(base_url, image) for image in (image_urls or []) if image]

    record = {
        "id": stable_id(url, raw_text_clean),
        "source": "ohana",
        "title": clean_text(title) or guess_title(raw_text),
        "price": clean_text(price) or guess_price(raw_text),
        "location": clean_text(location),
        "dates": guess_dates(raw_text),
        "bedrooms": guess_bedrooms(raw_text),
        "url": absolute_url,
        "image_urls": list(dict.fromkeys(images)),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "raw_text": raw_text_clean,
    }
    return record
