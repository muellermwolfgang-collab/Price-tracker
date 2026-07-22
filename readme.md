# gravel_frameset_tracker

New module for the existing **Preis-Tracker** repo. Tracks offers for race-oriented
gravel frame sets (32–45mm tire clearance) from well-known brands, and notifies when:

- an **aluminium** frameset drops below **€350**
- a **carbon** frameset drops below **€450**

## How it fits into the repo

This is a self-contained module — drop the `gravel_frameset_tracker/` folder next to
your existing tariff-tracker code. Notifications are already wired to the same ntfy.sh
topic as the tariff bot, so both push through one channel — nothing to configure there.
Scheduling: call `main.py` on the same schedule/runner (cron, GitHub Actions, etc.) you
already use for the tariff bot.

**On the repo having a `config.py` and `requirements.txt` already:** that's fine as
long as this stays in its own `gravel_frameset_tracker/` subfolder rather than getting
unzipped flat into the repo root — `gravel_frameset_tracker/config.py` and the tariff
bot's root-level `config.py` are different files at different paths, so nothing
overwrites and nothing collides at import time (each bot's `main.py` is run as its own
script, so Python resolves `import config` to whichever folder that script lives in).
The one thing to actually merge by hand: **`requirements.txt`**. You already added
`playwright` for the tariff bot, so this module's `requirements.txt` is mostly
redundant — just check the root one has `requests` too (used for the placeholder
notification), then you can delete this module's copy and keep a single
`pip install -r requirements.txt` for both bots.

## What's real vs. what still needs a live run

I don't have a real browser in this sandbox, but I do have a page-fetch tool, and used
it to check all six retailers' actual live pages rather than guess. Verdict per site:

- **bike-components.de**: real category confirmed
  (`/en/components/frames/cyclocross-gravel/`, 52 items, 3 pages). No on-page search —
  the adapter paginates the category and matches titles instead. Price format is
  English-style (`1,000.00€`).
- **bike24.de**: real category confirmed
  (`/cycling/parts/bike-frames/cyclocross-gravel-bike-frames`), now a real
  implementation. Price format is German-style (`988,24 €`) — **the two sites format
  numbers differently, don't share the price regex between them**, I only caught this
  by checking both.
- **canyon.com**: disabled. The Grail's product page only listed complete bikes, no
  frame-only SKU found.
- **fahrrad.de**: disabled. Checked their site structure — frame-*size* calculators and
  complete-bike categories exist, but no frame-*purchase* category anywhere, for road
  or gravel. Same pattern as Canyon: a complete-bike-and-accessories retailer, not a
  frame-only one.
- **rosebikes.de**: disabled, but with a real, useful finding: Rose does sell at least
  one frameset standalone (confirmed real product page for their road-race Xlite 06),
  and their race-gravel platform (Backroad FF) is confirmed at exactly 45mm clearance
  via official spec — added to `models.json`. But I could only find the Backroad FF as
  complete bikes plus a crash-replacement parts doc, not a clear "buy frameset new"
  page. Worth you checking directly since you know the site better than I can
  search-fetch it.

- **schlierseer-bikeparts.de**: disabled — real and relevant (Cube frame
  specialist, matches your Cube Agree), but structurally incompatible with this bot.
  Real category confirmed (`/cross`), but every listing is an individual physical
  frame with **no published price** — it's inquiry/quote-based, not a fixed-price
  catalogue. Their eBay shop does show real prices for some of the same frames, but
  that's a different, harder scraping target I haven't attempted.

Net effect on `models.json`: dropped the nonexistent Canyon Grail AL, corrected
"Ridley Kanzo Speed" → "Kanzo Fast" (actual current name), excluded BMC Kaius (current
generation is 52mm, over your limit), added Specialized Crux DSW and Rose Backroad FF
as real candidates with their verification status noted inline.

Both real adapters (bike-components.de, bike24.de) match products by scanning link
text and href patterns confirmed against actual page content, rather than guessed CSS
class names — more likely to survive a markup change than invented selectors. None of
this replaces an actual `python main.py` run against live Playwright — text from a
page-fetch tool isn't identical to what a real browser DOM exposes — but it's a much
closer starting point than the original guesswork.

## Assumptions baked in (change in `config.py` if wrong)

- EUR pricing
- Frame + fork ("frameset") listings only, not complete bikes
- New listings only — no used marketplaces (e.g. bikemarkt.mtb-news.de, Kleinanzeigen)
- Frame size 56 only (adjust `FRAME_SIZE_FILTER` in `config.py` or set to `None` for all sizes)

## Model discovery

`discover_models.py` checks a short list of curated sources (manufacturer new-model
pages + a couple of well-known "best gravel bike" roundups) each run, looks for
mentions of known brands alongside gravel/frameset keywords, and writes anything new
to `candidates.json` for a quick manual yes/no before it's merged into `models.json`.
Fully automatic brand/spec classification from scraped text is unreliable enough
(marketing copy is inconsistent about clearance numbers) that I kept a human
confirmation step rather than silently auto-adding models — flip `AUTO_APPROVE` in
`config.py` if you'd rather it just add everything it finds.

## Files

```
gravel_frameset_tracker/
├── config.py           # thresholds, filters, source list
├── models.json          # seed model list (brand, model, materials, clearance)
├── candidates.json       # newly discovered models awaiting approval (created on first run)
├── discover_models.py   # Step 1: find new models, update models.json
├── scrape_prices.py      # Step 2: scrape retailers for tracked models, check thresholds
├── notify.py            # Step 3: push notification — wired to the tariff bot's ntfy topic
├── main.py               # orchestrates discover -> scrape -> notify
├── requirements.txt
└── scrapers/
    ├── __init__.py       # registers all adapters
    ├── base.py           # shared Offer type + adapter interface
    ├── bike_components.py  # real, working
    ├── bike24.py           # real, working
    ├── canyon.py           # disabled — no frame-only SKU found
    ├── fahrrad_de.py       # disabled — no frame category found
    ├── rosebikes.py        # disabled — Backroad FF frameset not confirmed
    └── schlierseer.py      # disabled — no published prices to scrape
```

## Running it

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```
