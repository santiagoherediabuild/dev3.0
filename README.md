# Manifest: tender intelligence for Daniel

A static site that ranks Australian government tenders against Daniel's
Supply Chain & Operations Advisory criteria, refreshed on a schedule and
hosted free on GitHub Pages.

Live demo data ships in `data/tenders.json` so the site isn't empty the
first time you open it. Replace it with real data using the steps below.

## How it works

```
CSV export from AusTender / a state portal
            │
            ▼
   data/incoming/*.csv
            │
            ▼
  scripts/fetch_tenders.py   (reads config/scoring_config.json)
            │
            ▼
     data/tenders.json        ← the only file the website reads
            │
            ▼
        index.html            (filters, sorts, ranks in the browser)
```

A scheduled GitHub Action runs the script daily and commits the refreshed
`data/tenders.json`, so the page updates itself without anyone visiting
the repo.

## What's verified and what isn't

I built and tested the scoring engine, the CSV parser, and the site end
to end against sample data, that all works.

What I could **not** test: I don't have network access to tenders.gov.au
from where this was built, so `fetch_austender_live()` in
`scripts/fetch_tenders.py` has never actually reached the live site. It's
a real, complete scraper (not a stub), it searches AusTender directly for
every term in `live_search_terms` and parses the results, but the first
scheduled run on GitHub is the real first test of it. GitHub's servers
have normal internet access, unlike the environment this was built in, so
it will actually attempt the search once it's running there.

It fails safe either way: if AusTender blocks the request or the page
structure doesn't match what the parser expects, it logs a warning and
moves on. Nothing crashes, and the CSV-import path (below) still works
regardless.

### If the live fetch comes back empty

Go to the **Actions** tab, open the latest "Refresh tender data" run, and
read the log. Two likely outcomes:

- **It lists a 403, blocked, or similar error for every search term.**
  AusTender is rejecting the request outright, most often because it
  wants a real browser session rather than a plain request. This needs a
  different approach (e.g. a headless browser step in the workflow)
  rather than a small fix, tell me what the log says and I'll help adapt it.
- **It says "0 results" with no errors.** The request went through but the
  page layout didn't match what the parser looks for. Check
  `data/debug/*.html` (committed alongside the data), each file is the
  raw page AusTender sent back for that search term. Open one in a
  browser or send it to me, and I can adjust the parsing in
  `parse_search_results()` to match the real structure.

Either way, nothing is lost while this gets sorted, the site keeps
running on whatever's in `data/tenders.json` from the last successful run
or CSV import.

## Getting real data in

### The live search runs on its own

Every morning (see the schedule in
`.github/workflows/update-tenders.yml`), GitHub automatically runs
`scripts/fetch_tenders.py`, which searches AusTender for every term in
`config/scoring_config.json`'s `live_search_terms` list, scores what it
finds, and publishes the result. No action needed once it's confirmed
working, see the debugging section above for the first-run check.

### CSV import (reliable fallback, and useful for state portals)

The live search only covers AusTender. For state portals (buy.nsw,
Tenders VIC, QTenders, Tenders WA, SA Tenders) or to double check
AusTender results:

1. Run a search on the portal and export the results to CSV.
2. Drop the CSV file(s) into `data/incoming/`.
3. Push it, the workflow triggers automatically on any push touching
   `data/incoming/`, or run `python scripts/fetch_tenders.py` locally.

The parser looks for common column names (title, agency, close date,
value, description, URL, reference, state) and a few aliases for each.
If a portal's export uses different headers, add the alias to
`COLUMN_ALIASES` near the top of `scripts/fetch_tenders.py`.

## Tuning what counts as a match

Everything Daniel cares about lives in `config/scoring_config.json`, no
code changes needed to retune it:

- `keywords`: term to weight. Higher weight means a bigger contribution
  to the match score.
- `priority_buyers`: federal and state agencies that earn a bonus.
- `related_organisations`: bodies like AgriFutures or port authorities.
- `capability_map`: which KPMG capability gets recommended based on
  which keywords matched.
- `exclude_keywords`: anything matching these gets dropped entirely
  (pure IT, ERP, payroll, HR, audit work).
- `scoring`: the weight caps and bonus sizes that combine into the
  0 to 10 score.

After editing the config, re-run `scripts/fetch_tenders.py` (or wait for
the next scheduled run, it re-scores existing `data/incoming/` files
against the new config too).

## Local preview

No build step, it's a static site.

```
python3 -m http.server 8000
```

Then open `http://localhost:8000`.

## Deploying to GitHub Pages

1. Create a new GitHub repository and push this folder to it.
2. In the repo, go to **Settings > Pages**.
3. Under **Build and deployment**, set **Source** to "Deploy from a
   branch", branch `main`, folder `/ (root)`.
4. Save. GitHub gives you a URL like
   `https://<your-username>.github.io/<repo-name>/` within a minute or two.
5. Go to the **Actions** tab and confirm the "Refresh tender data"
   workflow is enabled (it runs on a daily schedule and can also be
   triggered manually from that tab with "Run workflow").

No secrets or API keys are needed for the CSV-import path.

## Project structure

```
index.html                     the page itself
assets/style.css               visual design
assets/app.js                  filtering, sorting, rendering
data/tenders.json              scored output, what the site reads
data/incoming/                 drop CSV exports here
data/debug/                    raw AusTender pages, only appears if live search returns nothing
config/scoring_config.json     Daniel's matching criteria and live search terms, editable
scripts/fetch_tenders.py       searches AusTender live, parses CSVs, scores, writes tenders.json
scripts/requirements.txt       Python packages the workflow installs before running
examples/sample_austender_export.csv   a demo CSV to try the pipeline on
.github/workflows/update-tenders.yml   the daily morning refresh job
```

## Trying the pipeline yourself

```
cp examples/sample_austender_export.csv data/incoming/
python3 scripts/fetch_tenders.py
```

This regenerates `data/tenders.json` from the sample data so you can see
scoring, exclusion and capability mapping in action before pointing it at
a real export.
