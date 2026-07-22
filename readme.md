# Price Tracker: iPhone 17 / Pro / Pro Max contracts

Watches handyhase.de and logitel.de for Vodafone/Telekom bundles with at
least 20GB data (no Young or GigaKombi tariffs) and pushes a phone
notification when the effective price drops below your threshold:

- iPhone 17: under 2 €/month
- iPhone 17 Pro / Pro Max: under 4 €/month

No coding required to run it - just the setup steps below.

## 1. Get the push notification app (2 minutes)

1. Install **ntfy** on your phone: [App Store](https://apps.apple.com/app/ntfy/id1625396347) / [Play Store](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
2. Open the app, tap "+", and pick a **topic name** - this is like a private channel name. Make it hard to guess since anyone who knows it could send you (or read) notifications on it, e.g. `tom-iphone17-deals-x7k2`.
3. Subscribe to that topic in the app.

## 2. Put the project on GitHub (5 minutes)

1. Create a free account at [github.com](https://github.com) if you don't have one.
2. Click "+" → "New repository". Name it e.g. `price-tracker`. Keep it **private** if you'd rather the code not be public (works exactly the same either way).
3. On the new repo's page, use "Add file" → "Upload files" and drag in all the files from this project (keep the folder structure, including the `.github/workflows` folder).
4. Open `config.json` in the GitHub web editor (click the file → pencil icon) and replace `REPLACE-WITH-YOUR-OWN-NTFY-TOPIC` with the topic name you picked in step 1. Commit the change.

## 3. Turn on the schedule (1 minute)

1. Go to the repo's **Actions** tab. If prompted, click "I understand my workflows, go ahead and enable them".
2. You'll see "Check Prices" listed. Click it, then "Run workflow" to try it immediately rather than waiting for the schedule.
3. After it finishes, click into the run and open the "Run price check" step to see what it found - it prints every matching offer, plus a warning with sample page text if a site returned nothing (see below).

From here it runs automatically every 3 hours.

## Updating the "market value" numbers

Handyhase publishes its own effective price directly, so nothing to
maintain there. For Logitel, the script nets out an assumed resale value
of the phone (`market_value_eur` in `config.json`) to make its number
comparable to Handyhase's. Check handyhase.de's device page now and then
("Wert des Apple iPhone ... laut Preisvergleich") and update the number in
`config.json` if it's drifted.

## Heads-up: this is a first version

I wrote the page parsers based on directly inspecting both sites, but
couldn't run the script against the live pages from where I built it,
so the very first Actions run is the real test. Two known rough edges
already:

- **Logitel's unlimited-data tariffs** (e.g. "Vodafone Smart L" with
  unlimited GB) aren't picked up yet - only tariffs that show a specific
  GB number are. Worth adding once the basics are confirmed working.
- **Logitel's price formatting** can render the Euro-cents part
  separately, which occasionally garbles plain-text extraction.

If a run shows "0 offers" for a source, or the numbers look wrong, copy
the printed log output back to me and I'll adjust the parsing together
with you.
