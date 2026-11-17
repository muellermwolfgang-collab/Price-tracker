"""
black_week scout: find shops for every product - daily, in the background.

For every product in products.yaml and every shop in shops.yaml that has no
entry in targets.yaml yet, the shop's sitemaps are searched for the product
(see discover.py). Candidates are opened and checked strictly (price on the
page, 85 % of the product words and every brand/model word in the product
name). Verified offers are appended to targets.yaml, so the price runs pick
them up. Existing entries are never changed or removed here - repairing
URLs is done by run.py, deactivating entries stays with you.

Usage:
    python black_week/scout.py                       # check all products x shops
    python black_week/scout.py --add "Dyson V15 Detect" --keywords "V15" \
                               --shops "otto.de, mediamarkt"   # new product, scout it now
    python black_week/scout.py --dry-run             # search, print, change nothing

Same ground rules as run.py: honest User-Agent, robots.txt, one request per
host every 5-10 s, no bypassing of bot protection.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

import discover
import run

MODULE_DIR = Path(__file__).resolve().parent
PRODUCTS_PATH = MODULE_DIR / "products.yaml"
SHOPS_PATH = MODULE_DIR / "shops.yaml"
SCOUT_BUDGET_S = 25 * 60          # job timeout is 35 min
MAX_VERIFY_PER_PRODUCT = 2        # candidate pages opened per product and shop


# --------------------------------------------------------------------------
# Config files
# --------------------------------------------------------------------------

def _load_list(path: Path) -> list:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of entries")
    return data


def load_products(path: Path = PRODUCTS_PATH) -> list[dict]:
    out = []
    for i, e in enumerate(_load_list(path), 1):
        if not isinstance(e, dict) or not e.get("product"):
            raise ValueError(f"{path}: entry {i} needs a 'product'")
        if not e.get("active", True):
            continue
        kw = e.get("keywords") or []
        out.append({"product": str(e["product"]), "keywords": [kw] if isinstance(kw, str) else [str(k) for k in kw]})
    return out


def normalise_site(site: str) -> str:
    site = site.strip().rstrip("/")
    if not site.startswith(("http://", "https://")):
        site = "https://" + site
    return site


def load_shops(path: Path = SHOPS_PATH) -> list[dict]:
    out = []
    for i, e in enumerate(_load_list(path), 1):
        if not isinstance(e, dict) or not e.get("shop") or not e.get("site"):
            raise ValueError(f"{path}: entry {i} needs 'shop' and 'site'")
        if not e.get("active", True):
            continue
        out.append({"shop": str(e["shop"]), "site": normalise_site(str(e["site"]))})
    return out


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def existing_coverage(targets_path: Path) -> list[tuple[str, set[str]]]:
    """(host, product tokens) of every entry in targets.yaml - inactive ones
    included, so an entry you switched off is not added again."""
    cov = []
    for e in _load_list(targets_path):
        if not isinstance(e, dict) or not e.get("product"):
            continue
        where = e.get("url") or e.get("site")
        if where:
            cov.append((host_of(normalise_site(str(where))), set(discover.tokens(str(e["product"])))))
    return cov


def is_covered(product: dict, shop: dict, coverage) -> bool:
    want = set(discover.tokens(product["product"]))
    host = host_of(shop["site"])
    return any(h == host and want <= toks for h, toks in coverage)


def _append_yaml_entries(path: Path, entries: list[dict], header: str) -> None:
    """Append list entries as text, so comments and layout of the file stay."""
    if not entries:
        return
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    block = yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=200)
    block = re.sub(r"\n(?=- )", "\n\n", block)          # blank line between entries
    path.write_text(text + f"\n# {header}\n" + block, encoding="utf-8")


def add_product(product: str, keywords: list[str], path: Path = PRODUCTS_PATH) -> bool:
    """Add a product to products.yaml unless it is already there."""
    want = discover.tokens(product)
    for e in _load_list(path):
        if isinstance(e, dict) and discover.tokens(str(e.get("product", ""))) == want:
            return False
    entry = {"product": product}
    if keywords:
        entry["keywords"] = keywords
    entry["active"] = True
    _append_yaml_entries(path, [entry], f"added {datetime.now(timezone.utc):%Y-%m-%d}")
    return True


def resolve_shops(spec: str | None, catalog: list[dict], path: Path = SHOPS_PATH,
                  persist: bool = True) -> list[dict]:
    """--shops "otto.de, mediamarkt": names are looked up in shops.yaml,
    unknown domains are added to it (unless persist=False). Empty -> all shops."""
    if not spec:
        return catalog
    chosen, new = [], []
    for item in [s.strip() for s in spec.split(",") if s.strip()]:
        hit = [s for s in catalog if s["shop"].lower() == item.lower() or host_of(s["site"]) == host_of(normalise_site(item))]
        if hit:
            chosen += hit
        elif "." in item:
            shop = {"shop": host_of(normalise_site(item)), "site": normalise_site(item)}
            new.append(shop)
            chosen.append(shop)
        else:
            print(f"unknown shop {item!r} - add it to shops.yaml with its site", file=sys.stderr)
    if new and persist:
        _append_yaml_entries(path, [{**s, "active": True} for s in new],
                             f"added {datetime.now(timezone.utc):%Y-%m-%d}")
    return chosen


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

def _scout_target(product: dict, shop: dict) -> dict:
    return {"product": product["product"], "shop": shop["shop"], "url": None, "seed_url": None,
            "site": shop["site"], "type": "product", "match": None, "price_selector": None,
            "keywords": product["keywords"]}


async def scout_shop(fetcher, shop: dict, products: list[dict], report: list[dict], log=print) -> None:
    """All missing products for one shop: one pass over its sitemaps, then
    the best candidates are opened one by one (paced)."""
    targets = [_scout_target(p, shop) for p in products]
    rules = await fetcher.robots_for(shop["site"])
    if rules.unavailable:
        for t in targets:
            report.append({"product": t["product"], "shop": shop["shop"], "status": "blocked", "note": rules.unavailable})
        return
    try:
        found, how = await discover.collect_candidates_multi(
            fetcher, shop["site"], targets, [set() for _ in targets], cache=False, prefix=shop["site"])
    except Exception as exc:
        found, how = [[] for _ in targets], f"search failed: {type(exc).__name__}"
    shop_blocked = None
    for t, cands in zip(targets, found):
        entry = {"product": t["product"], "shop": shop["shop"], "status": "not_found", "note": how}
        if shop_blocked:
            entry.update(status="blocked", note=shop_blocked)
        for url in ([] if shop_blocked else cands[:MAX_VERIFY_PER_PRODUCT]):
            res = await fetcher.fetch_paced(dict(t, url=url))
            if res["status"] in ("blocked", "robots"):
                shop_blocked = res.get("note") or res["status"]
                entry.update(status="blocked", note=shop_blocked)
                break
            ok = res["status"] == "ok" and discover.page_matches_strict(t, res.get("_name"), res.get("page_title"))
            log(f"  {shop['shop']}: {url} -> {res['status']}{' (match)' if ok else ''}")
            if ok:
                entry.update(status="added", url=url, price=res["price"], page_title=res.get("page_title"), note=None)
                break
        report.append(entry)
        log(f"[{entry['status']:<9}] {shop['shop']}: {t['product']}"
            + (f" -> {entry['url']}" if entry.get("url") else ""))


async def scout(products: list[dict], shops: list[dict], coverage, log=print) -> list[dict]:
    report: list[dict] = []
    jobs = []
    for shop in shops:
        missing = [p for p in products if not is_covered(p, shop, coverage)]
        for p in products:
            if p not in missing:
                report.append({"product": p["product"], "shop": shop["shop"], "status": "listed", "note": None})
        if missing:
            jobs.append((shop, missing))
    if not jobs:
        return report
    async with run.open_fetcher(log) as fetcher:
        await run.run_bounded([scout_shop(fetcher, shop, missing, report, log) for shop, missing in jobs],
                              SCOUT_BUDGET_S, log)
    done = {(r["product"], r["shop"]) for r in report}
    for shop, missing in jobs:
        for p in missing:
            if (p["product"], shop["shop"]) not in done:
                report.append({"product": p["product"], "shop": shop["shop"], "status": "timeout",
                               "note": "not reached within the run budget"})
    return report


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

STATUS_TEXT = {
    "listed": "✔ schon in targets.yaml",
    "added": "➕ neu hinzugefügt",
    "not_found": "– nicht gefunden",
    "blocked": "⛔ blockiert",
    "timeout": "⏱ nicht geschafft",
}


def new_target_entries(report: list[dict], shops: list[dict]) -> list[dict]:
    site = {s["shop"]: s["site"] for s in shops}
    out = []
    for r in report:
        if r["status"] == "added":
            out.append({"product": r["product"], "shop": r["shop"], "url": r["url"],
                        "site": site.get(r["shop"]), "active": True, "added_by": "scout"})
    return out


def render_report(report: list[dict], run_at: datetime) -> str:
    local = run_at.astimezone(run.BERLIN)
    products = list(dict.fromkeys(r["product"] for r in report))
    lines = [
        "# Black Week – Shop-Suche",
        "",
        f"Stand: {local:%d.%m.%Y %H:%M} Uhr (Europe/Berlin)",
        "",
    ]
    added = [r for r in report if r["status"] == "added"]
    if added:
        lines += ["## Neu hinzugefügt", ""]
        for r in added:
            price = run.fmt_eur(r.get("price")) if r.get("price") is not None else "–"
            lines.append(f"- {run._md_cell(r['product'])} bei {run._md_cell(r['shop'])}: {price} – [Link]({r['url']})")
        lines.append("")
    lines += ["## Übersicht", "", "| Produkt | Shop | Ergebnis |", "|---|---|---|"]
    for p in products:
        for r in sorted((r for r in report if r["product"] == p), key=lambda r: r["shop"].lower()):
            lines.append(f"| {run._md_cell(p)} | {run._md_cell(r['shop'])} | {STATUS_TEXT.get(r['status'], r['status'])} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Find shops for the products in products.yaml.")
    ap.add_argument("--add", metavar="PRODUCT", help="add this product to products.yaml and scout only it")
    ap.add_argument("--keywords", default="", help="comma-separated words the product page must contain")
    ap.add_argument("--shops", default="", help="comma-separated shop names or domains (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="search and print, change no files")
    ap.add_argument("--targets", type=Path, default=run.TARGETS_PATH)
    ap.add_argument("--out-dir", type=Path, default=run.RESULTS_DIR)
    args = ap.parse_args(argv)

    try:
        products = load_products()
        catalog = load_shops()
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
        if args.add:
            name = args.add.strip()
            if not args.dry_run and add_product(name, keywords):
                print(f"added to products.yaml: {name}")
            products = [{"product": name, "keywords": keywords}]
        shops = resolve_shops(args.shops, catalog, persist=not args.dry_run)
        coverage = existing_coverage(args.targets)
    except Exception as exc:
        print(f"cannot load configuration: {exc}", file=sys.stderr)
        return 1
    if not products or not shops:
        print("nothing to do (no active products or shops)")
        return 0

    run_at = datetime.now(timezone.utc)
    print(f"scout: {len(products)} product(s) x {len(shops)} shop(s)")
    started = time.monotonic()
    try:
        report = asyncio.run(scout(products, shops, coverage))
    except Exception as exc:
        print(f"scout failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"done in {time.monotonic() - started:.0f}s")

    entries = new_target_entries(report, shops)
    md = render_report(report, run_at)
    if args.dry_run:
        print()
        print(md)
        return 0
    try:
        _append_yaml_entries(args.targets, entries, f"found by scout {run_at:%Y-%m-%d}")
        args.out_dir.mkdir(parents=True, exist_ok=True)
        run._atomic_write(args.out_dir / "scout.md", md)
        run._atomic_write(args.out_dir / "scout.json", json.dumps(
            {"generated_at": run_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "results": report},
            indent=2, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"cannot write results: {exc}", file=sys.stderr)
        return 1
    print(f"{len(entries)} new target(s) added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
