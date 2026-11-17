"""
black_week: fetch product pages with headless Chromium (Playwright) and
write the prices to black_week/results/ (latest.json, latest.md, history.csv).

Usage:
    python black_week/run.py              # fetch and write results
    python black_week/run.py --dry-run    # fetch, print to console, write nothing
    python black_week/run.py --only tink  # only entries whose shop/product contains "tink"

Ground rules (deliberately, see readme.md):
  - honest User-Agent, no stealth plugins, no fingerprint spoofing, no proxies,
    no captcha solving, no login, no fake headers
  - robots.txt is checked before every fetch; disallowed paths are skipped
  - at most one request at a time per host, 5-10 s pause between requests
    to the same host; one retry on timeout, none on a block

A failure on a single URL never aborts the run. The exit code is non-zero
only if no result file could be written.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import yaml

import extract as ex
from robots import RobotsRules, rules_from_response

MODULE_DIR = Path(__file__).resolve().parent
TARGETS_PATH = MODULE_DIR / "targets.yaml"
RESULTS_DIR = MODULE_DIR / "results"

REPO_URL = "https://github.com/muellermwolfgang-collab/Price-tracker"
USER_AGENT = f"PriceTracker/1.0 (+{REPO_URL})"
ROBOTS_TOKEN = "PriceTracker"

LOCALE = "de-DE"
TIMEZONE = "Europe/Berlin"
VIEWPORT = {"width": 1366, "height": 900}
NAV_TIMEOUT_MS = 30_000
PRICE_WAIT_MS = 10_000
HOST_PAUSE_S = (5.0, 10.0)
MAX_PARALLEL_PAGES = 4
RUN_BUDGET_S = 15 * 60          # stay well inside the 20 min job timeout

STATUSES = ("ok", "no_price", "blocked", "robots", "timeout", "error")

FIELDS = [
    "product", "shop", "url", "status", "http_status", "price", "currency",
    "shipping", "availability", "source", "offers", "page_title", "fetched_at",
    "price_high", "offer_count", "note",
]
HISTORY_FIELDS = [
    "run_at", "product", "shop", "status", "http_status", "price", "currency",
    "shipping", "availability", "source", "offer_count", "page_title", "url", "fetched_at",
]

BERLIN = ZoneInfo("Europe/Berlin")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_targets(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of entries")
    targets = []
    for i, entry in enumerate(data, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: entry {i} is not a mapping")
        missing = [k for k in ("product", "shop", "url") if not entry.get(k)]
        if missing:
            raise ValueError(f"{path}: entry {i} is missing {', '.join(missing)}")
        page_type = entry.get("type", "product")
        if page_type not in ("product", "listing"):
            raise ValueError(f"{path}: entry {i} has unknown type {page_type!r}")
        if not entry.get("active", True):
            continue
        targets.append({
            "product": str(entry["product"]),
            "shop": str(entry["shop"]),
            "url": str(entry["url"]),
            "type": page_type,
            "match": str(entry["match"]) if entry.get("match") not in (None, "") else None,
            "price_selector": entry.get("price_selector") or None,
        })
    return targets


def empty_result(target: dict, status: str, note: str | None = None) -> dict:
    return {
        "product": target["product"], "shop": target["shop"], "url": target["url"],
        "status": status, "http_status": None, "price": None, "currency": None,
        "shipping": None, "availability": None, "source": None,
        "offers": [] if target["type"] == "listing" else None,
        "page_title": None, "fetched_at": utc_now(),
        "price_high": None, "offer_count": None, "note": note,
    }


# --------------------------------------------------------------------------
# Browser side
# --------------------------------------------------------------------------

WAIT_FOR_PRICE_JS = r"""
([selector, matchSrc]) => {
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    if (/"(price|lowPrice)"\s*:/.test(s.textContent || '')) return true;
  }
  if (document.querySelector('meta[property="product:price:amount"], meta[property="og:price:amount"], [itemprop="price"]')) return true;
  if (selector) { try { if (document.querySelector(selector)) return true; } catch (e) {} }
  if (matchSrc && document.body) {
    const t = document.body.innerText || '';
    if (new RegExp(matchSrc, 'i').test(t) && /\d\s*(€|EUR)|€\s*\d/.test(t)) return true;
  }
  return false;
}
"""

# Smallest visible elements whose text contains the keyword and a euro amount.
LISTING_BLOCKS_JS = r"""
(matchSrc) => {
  const re = matchSrc ? new RegExp(matchSrc, 'i') : null;
  const priceRe = /\d\s*(€|EUR)|€\s*\d/i;
  const tags = 'article,li,a,div,section,tr';
  const cands = Array.from(document.querySelectorAll(tags)).filter(el => {
    const t = el.textContent || '';
    return t.length >= 8 && t.length <= 3000 && (!re || re.test(t)) && priceRe.test(t);
  });
  const set = new Set(cands);
  // innerText glues inline elements together ("Sehr gutab 164,25 €UVP ..."),
  // so collect visible text nodes and join them line by line instead.
  const visibleLines = (root) => {
    const parts = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const s = (n.nodeValue || '').replace(/\s+/g, ' ').trim();
      if (!s) continue;
      const p = n.parentElement;
      if (p && (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(p.tagName) ||
                (p.checkVisibility ? !p.checkVisibility({visibilityProperty: true}) : !p.getClientRects().length))) continue;
      parts.push(s);
    }
    return parts.join('\n');
  };
  const out = [];
  for (const el of cands) {
    if (Array.from(el.querySelectorAll(tags)).some(d => set.has(d))) continue;
    if (!el.getClientRects().length) continue;
    const t = visibleLines(el);
    if (t.length <= 1500 && (!re || re.test(t)) && priceRe.test(t)) out.push(t);
    if (out.length >= 200) break;
  }
  return out;
}
"""


class Fetcher:
    def __init__(self, context, log=print):
        self.context = context
        self.log = log
        self.robots: dict[str, RobotsRules] = {}
        self.sem = asyncio.Semaphore(MAX_PARALLEL_PAGES)

    async def robots_for(self, url: str) -> RobotsRules:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            status, text = None, None
            try:
                resp = await self.context.request.get(
                    origin + "/robots.txt", timeout=15_000, max_redirects=5, fail_on_status_code=False,
                )
                status = resp.status
                if 200 <= status < 300:
                    text = (await resp.body()).decode("utf-8", errors="replace")
            except Exception as exc:  # network error -> stay away (RFC 9309)
                self.log(f"  robots.txt {origin}: {type(exc).__name__}: {exc}".splitlines()[0])
            self.robots[origin] = rules_from_response(status, text)
            if status is not None:
                self.log(f"  robots.txt {origin}: HTTP {status}")
        return self.robots[origin]

    async def fetch(self, target: dict) -> tuple[dict, bool]:
        """Fetch one target once. Returns (result, retry_worthwhile)."""
        from playwright.async_api import Error as PWError
        from playwright.async_api import TimeoutError as PWTimeout

        result = empty_result(target, "error")
        page = await self.context.new_page()
        try:
            try:
                resp = await page.goto(target["url"], wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except PWTimeout:
                result.update(status="timeout", note="navigation timeout (30 s)")
                return result, True
            except PWError as exc:
                result.update(status="error", note=str(exc).splitlines()[0][:300])
                return result, False

            http_status = resp.status if resp else None
            result["http_status"] = http_status
            match_src = ex._match_regex(target["match"]).pattern if target["match"] else None

            if http_status not in ex.BLOCK_STATUS:
                try:
                    await page.wait_for_function(
                        WAIT_FOR_PRICE_JS, arg=[target["price_selector"], match_src],
                        timeout=PRICE_WAIT_MS, polling=500,
                    )
                except PWTimeout:
                    pass
                except PWError:
                    pass

            html = await page.content()
            title = (await page.title() or "").strip()
            try:
                text = await page.inner_text("body", timeout=5_000)
            except PWError:
                text = ex.visible_text(html)
            blocks = None
            if target["type"] == "listing":
                try:
                    blocks = await page.evaluate(LISTING_BLOCKS_JS, match_src)
                except PWError:
                    blocks = None   # falls back to static HTML parsing

            result["page_title"] = title[:300] or None
            result["fetched_at"] = utc_now()

            data = ex.extract(
                html, page_type=target["type"], match=target["match"],
                price_selector=target["price_selector"], listing_blocks=blocks, page_text=text,
            )
            if ex.detect_block(http_status, title, text, has_price=data.price is not None):
                result.update(status="blocked", note=f"bot wall / rate limit (HTTP {http_status})")
                return result, False
            if http_status is not None and http_status >= 400:
                result.update(status="error", note=f"HTTP {http_status}")
                return result, False

            result.update(
                status="ok" if data.price is not None else "no_price",
                price=data.price, currency=data.currency, shipping=data.shipping,
                availability=data.availability, source=data.source,
                price_high=data.price_high, offer_count=data.offer_count, note=None,
            )
            if target["type"] == "listing":
                result["offers"] = data.offers
                if data.offer_count is None and data.offers:
                    result["offer_count"] = len(data.offers)
            return result, False
        except PWTimeout as exc:
            result.update(status="timeout", note=str(exc).splitlines()[0][:300])
            return result, True
        except Exception as exc:
            result.update(status="error", note=f"{type(exc).__name__}: {str(exc).splitlines()[0][:300] if str(exc) else ''}")
            return result, False
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def run_host(self, items: list[tuple[int, dict]], results: dict[int, dict]) -> None:
        """All targets of one host, strictly one after another with a pause."""
        first = True
        for idx, target in items:
            try:
                rules = await self.robots_for(target["url"])
                if not rules.can_fetch(ROBOTS_TOKEN, target["url"]):
                    if rules.unavailable:
                        status = "blocked" if "429" in rules.unavailable else "error"
                        results[idx] = empty_result(target, status, rules.unavailable + ", page not fetched")
                    else:
                        results[idx] = empty_result(target, "robots", "disallowed by robots.txt")
                    self._log_result(target, results[idx])
                    continue
                for attempt in (1, 2):
                    if not first:
                        await asyncio.sleep(random.uniform(*HOST_PAUSE_S))
                    first = False
                    async with self.sem:
                        result, retry = await self.fetch(target)
                    results[idx] = result
                    if not (retry and attempt == 1):
                        break
                    self.log(f"[retry   ] {target['shop']}: {target['product']} ({result['note']})")
            except Exception as exc:
                results[idx] = empty_result(target, "error", f"{type(exc).__name__}: {exc}"[:300])
            self._log_result(target, results[idx])

    def _log_result(self, target: dict, r: dict) -> None:
        price = f"{r['price']:.2f} {r['currency'] or ''}".strip() if r["price"] is not None else "-"
        note = f"  ({r['note']})" if r.get("note") else ""
        self.log(f"[{r['status']:<8}] {target['shop']}: {target['product']} -> {price}{note}")


async def fetch_all(targets: list[dict], log=print) -> list[dict]:
    results: dict[int, dict] = {}
    by_host: dict[str, list[tuple[int, dict]]] = {}
    for idx, t in enumerate(targets):
        by_host.setdefault(urlsplit(t["url"]).hostname or "", []).append((idx, t))

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return [empty_result(t, "error", f"playwright not installed: {exc}") for t in targets]

    try:
        async with async_playwright() as p:
            launch_kwargs = {"headless": True}
            if os.environ.get("BLACK_WEEK_CHROMIUM"):
                launch_kwargs["executable_path"] = os.environ["BLACK_WEEK_CHROMIUM"]
            browser = await p.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                user_agent=USER_AGENT, locale=LOCALE, timezone_id=TIMEZONE, viewport=VIEWPORT,
            )
            context.set_default_timeout(NAV_TIMEOUT_MS)
            fetcher = Fetcher(context, log)
            tasks = [asyncio.create_task(fetcher.run_host(items, results)) for items in by_host.values()]
            done, pending = await asyncio.wait(tasks, timeout=RUN_BUDGET_S)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
                log(f"run budget of {RUN_BUDGET_S}s exceeded, {len(pending)} host(s) cancelled")
            await context.close()
            await browser.close()
    except Exception as exc:
        log(f"browser error: {type(exc).__name__}: {exc}")
        note = f"browser error: {type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"[:300]
        for idx, t in enumerate(targets):
            results.setdefault(idx, empty_result(t, "error", note))

    out = []
    for idx, t in enumerate(targets):
        out.append(results.get(idx) or empty_result(t, "timeout", "not reached within run budget"))
    return out


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def fmt_eur(value) -> str:
    if value is None:
        return "–"
    s = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def _md_cell(text) -> str:
    return str(text if text not in (None, "") else "–").replace("|", "\\|").replace("\n", " ")


def render_markdown(results: list[dict], run_at: datetime) -> str:
    local = run_at.astimezone(BERLIN)
    counts = {s: sum(1 for r in results if r["status"] == s) for s in STATUSES}
    summary = ", ".join(f"{s}: {n}" for s, n in counts.items() if n)
    lines = [
        "# Black Week – Preise",
        "",
        f"Stand: {local:%d.%m.%Y %H:%M} Uhr (Europe/Berlin) · {summary}",
        "",
        "| Produkt | Shop | Status | Preis | Versand | Quelle | URL |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        price = fmt_eur(r["price"]) if r["currency"] in (None, "EUR") else f"{r['price']} {r['currency']}"
        if r["price"] is not None and (r.get("price_high") or (r.get("offers") and len(r["offers"]) > 1)):
            price = "ab " + price
        if r.get("offers"):
            conds = sorted({o["condition"] for o in r["offers"] if o.get("condition")})
            extra = f"{len(r['offers'])} Angebote" + (f" ({', '.join(conds)})" if conds else "")
            price = f"{price}<br>{extra}"
        lines.append(
            "| " + " | ".join([
                _md_cell(r["product"]), _md_cell(r["shop"]), _md_cell(r["status"]),
                price if r["price"] is not None else "–",
                fmt_eur(r["shipping"]) if r["shipping"] is not None else "–",
                _md_cell(r["source"]), f"[Link]({r['url']})",
            ]) + " |"
        )
    lines += [
        "",
        "Status: ok = Preis gefunden · no_price = Seite geladen, kein Preis · blocked = Bot-Schutz/Rate-Limit "
        "· robots = durch robots.txt verboten · timeout = Zeitüberschreitung · error = sonstiger Fehler",
        "",
    ]
    return "\n".join(lines)


def write_results(results: list[dict], run_at: datetime, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_at_utc = run_at.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "generated_at": run_at_utc,
        "generated_at_berlin": run_at.astimezone(BERLIN).replace(microsecond=0).isoformat(),
        "results": [{k: r.get(k) for k in FIELDS} for r in results],
    }
    _atomic_write(out_dir / "latest.json", json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    _atomic_write(out_dir / "latest.md", render_markdown(results, run_at))

    history = out_dir / "history.csv"
    new_file = not history.exists() or history.stat().st_size == 0
    with history.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        for r in results:
            writer.writerow({**r, "run_at": run_at_utc})


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="fetch and print to console, write no files")
    ap.add_argument("--targets", type=Path, default=TARGETS_PATH, help="path to targets.yaml")
    ap.add_argument("--out-dir", type=Path, default=RESULTS_DIR, help="output directory")
    ap.add_argument("--only", help="only entries whose shop or product contains this text")
    args = ap.parse_args(argv)

    try:
        targets = load_targets(args.targets)
    except Exception as exc:
        print(f"cannot load targets: {exc}", file=sys.stderr)
        return 1
    if args.only:
        needle = args.only.lower()
        targets = [t for t in targets if needle in t["shop"].lower() or needle in t["product"].lower()]
    if not targets:
        print("no active targets", file=sys.stderr)
        return 1

    run_at = datetime.now(timezone.utc)
    print(f"black_week: {len(targets)} target(s), UA {USER_AGENT!r}")
    started = time.monotonic()
    results = asyncio.run(fetch_all(targets))
    print(f"done in {time.monotonic() - started:.0f}s")

    if args.dry_run:
        print()
        print(render_markdown(results, run_at))
        print(json.dumps([{k: r.get(k) for k in FIELDS} for r in results], indent=2, ensure_ascii=False))
        return 0

    try:
        write_results(results, run_at, args.out_dir)
    except Exception as exc:
        print(f"cannot write results: {exc}", file=sys.stderr)
        return 1
    print(f"results written to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
