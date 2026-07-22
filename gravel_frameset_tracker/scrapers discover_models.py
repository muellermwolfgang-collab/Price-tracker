"""
Step 1: check curated sources for gravel frameset models not yet in
models.json, matching the known-brand + clearance criteria.

This deliberately does NOT try to be a full NLP classifier — marketing copy
is inconsistent about exact clearance numbers, and silently auto-adding a
wrong model is worse than a short manual review step. It flags candidates
by keyword co-occurrence (known brand + "gravel"/"frameset"/clearance
number in range) and writes them to candidates.json for a yes/no pass,
unless AUTO_APPROVE is set in config.py.
"""

import json
import re
from pathlib import Path

import config

CLEARANCE_RE = re.compile(r"(\d{2})\s*mm")
GRAVEL_KEYWORDS = ["gravel", "frameset", "rahmenset"]


def _load_json(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"models": []} if path == config.MODELS_FILE else {"candidates": []}
    return json.loads(p.read_text())


def _save_json(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _known_model_names(models_data: dict) -> set[str]:
    return {f"{m['brand']} {m['model']}".lower() for m in models_data["models"]}


def _scan_text(text: str, brand: str) -> list[int]:
    """Return clearance values (mm) mentioned near this brand's name in the text."""
    hits = []
    for match in re.finditer(re.escape(brand), text, re.IGNORECASE):
        window = text[max(0, match.start() - 200): match.start() + 200]
        if not any(kw in window.lower() for kw in GRAVEL_KEYWORDS):
            continue
        for clearance_match in CLEARANCE_RE.finditer(window):
            hits.append(int(clearance_match.group(1)))
    return hits


def discover(page) -> list[dict]:
    """Fetch each source and look for known-brand + in-range-clearance mentions.

    `page` is a Playwright page, reused across sources.
    """
    models_data = _load_json(config.MODELS_FILE)
    known = _known_model_names(models_data)
    candidates = []

    for url in config.DISCOVERY_SOURCES:
        page.goto(url, wait_until="networkidle")
        text = page.inner_text("body")

        for brand in config.KNOWN_BRANDS:
            clearances = _scan_text(text, brand)
            in_range = [
                c for c in clearances
                if config.MIN_TIRE_CLEARANCE_MM <= c <= config.MAX_TIRE_CLEARANCE_MM
            ]
            if not in_range:
                continue
            # We only know the brand matched, not the exact model name from
            # free text reliably — flag for manual naming/confirmation rather
            # than guess a model string.
            candidates.append({
                "brand": brand,
                "source_url": url,
                "clearance_mentions_mm": sorted(set(in_range)),
                "note": "Detected via keyword scan — confirm model name and "
                        "material before adding to models.json",
            })

    # De-dupe by (brand, source_url)
    seen = set()
    deduped = []
    for c in candidates:
        key = (c["brand"], c["source_url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    return deduped


def run(page) -> None:
    candidates = discover(page)
    if not candidates:
        print("No new candidates found.")
        return

    if config.AUTO_APPROVE:
        # Not recommended — see module docstring. Left in for completeness.
        models_data = _load_json(config.MODELS_FILE)
        models_data["models"].extend(candidates)
        _save_json(config.MODELS_FILE, models_data)
        print(f"Auto-added {len(candidates)} candidate(s) to {config.MODELS_FILE}.")
    else:
        _save_json(config.CANDIDATES_FILE, {"candidates": candidates})
        print(f"{len(candidates)} candidate(s) written to {config.CANDIDATES_FILE} "
              f"for manual review.")
