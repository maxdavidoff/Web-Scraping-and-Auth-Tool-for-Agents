from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable


def write_jsonl(records: Iterable[dict], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def write_csv(records: list[dict], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return 0

    fieldnames = sorted({key for record in records for key in record.keys()})
    preferred = [
        "source",
        "title",
        "price",
        "location",
        "dates",
        "bedrooms",
        "url",
        "image_urls",
        "scraped_at",
        "raw_text",
    ]
    ordered = [key for key in preferred if key in fieldnames] + [
        key for key in fieldnames if key not in preferred
    ]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ordered, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            cleaned = dict(record)
            if isinstance(cleaned.get("image_urls"), list):
                cleaned["image_urls"] = " | ".join(cleaned["image_urls"])
            writer.writerow(cleaned)
    return len(records)
