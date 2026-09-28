#!/usr/bin/env python3
"""
Tender Intelligence: fetch, score and publish tenders for Daniel's dashboard.

Two data paths feed this script, and both are safe to run at any time:

1. Live search (runs automatically every morning via GitHub Actions).
   fetch_austender_live() searches tenders.gov.au directly for every term
   in config['live_search_terms'] and parses the results. This was built
   against AusTender's public search page but could not be tested from a
   live network connection while building it, so the first scheduled run
   is the real test. If it comes back empty, data/debug/*.html holds the
   raw page AusTender returned for inspection, see the README section
   "If the live fetch comes back empty" for how to fix it. It always
   fails safe: an empty result here just means the CSV path (below)
   carries that day's run, nothing gets wiped.

2. CSV import (reliable fallback, no scraping). Export a search from
   AusTender or a state portal to CSV, drop the file(s) into
   data/incoming/, and this script will parse, score and merge them in
   too, on top of whatever the live search found.

Run:
    python scripts/fetch_tenders.py

Output:
    data/tenders.json  (scored, ranked, deduplicated, with a run timestamp)
"""

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "scoring_config.json")
INCOMING_DIR = os.path.join(ROOT, "data", "incoming")
OUTPUT_PATH = os.path.join(ROOT, "data", "tenders.json")

# Common column name variants seen across AusTender / state portal CSV exports.
# Add more aliases here if a real export uses different headers.
COLUMN_ALIASES = {
    "title": ["title", "atm title", "tender title", "opportunity title", "name"],
    "agency": ["agency", "buyer", "organisation", "organization", "procuring entity"],
    "close_date": ["close date", "closing date", "atm close date", "close_date"],
    "publish_date": ["publish date", "published date", "open date"],
    "value": ["value", "estimated value", "contract value", "atm value"],
    "description": ["description", "summary", "details", "atm description"],
    "url": ["url", "link", "atm url", "source url"],
    "reference": ["reference", "atm id", "tender id", "reference number"],
    "state": ["state", "jurisdiction"],
}


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def normalise_headers(fieldnames):
    """Map a CSV's real headers onto our canonical field names."""
    mapping = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for field in fieldnames:
            if field.strip().lower() in aliases:
                mapping[canonical] = field
                break
    return mapping


def parse_value(raw):
    if not raw:
        return None
    digits = re.sub(r"[^\d.]", "", raw)
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def parse_date(raw):
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return raw.strip()


def read_csv_file(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        mapping = normalise_headers(reader.fieldnames or [])
        for r in reader:
            item = {}
            for canonical, real_col in mapping.items():
                item[canonical] = (r.get(real_col) or "").strip()
            if item.get("title"):
                rows.append(item)
    return rows


def collect_incoming():
    """Read every CSV sitting in data/incoming/."""
    items = []
    if not os.path.isdir(INCOMING_DIR):
        return items
    for fname in sorted(os.listdir(INCOMING_DIR)):
        if fname.lower().endswith(".csv"):
            path = os.path.join(INCOMING_DIR, fname)
            try:
                found = read_csv_file(path)
                print(f"  read {len(found)} rows from {fname}")
                items.extend(found)
            except Exception as e:
                print(f"  WARNING: could not read {fname}: {e}", file=sys.stderr)
    return items


AUSTENDER_SEARCH_URL = "https://www.tenders.gov.au/atm"
DEBUG_DIR = os.path.join(ROOT, "data", "debug")
REQUEST_DELAY_SECONDS = 1.5
REQUEST_TIMEOUT = 25
USER_AGENT = "Mozilla/5.0 (compatible; tender-intel-bot/1.0; +https://github.com/)"

# A tender detail page link is the one structural feature least likely to
# change even if AusTender restyles its search results, so parsing anchors
# on for this rather than a specific CSS class name.
DETAIL_LINK_PATTERN = re.compile(r"/atm/(show/)?\d+")
DATE_PATTERN = re.compile(r"\b(\d{1,2}[/\-. ](?:\d{1,2}|[A-Za-z]{3,9})[/\-. ]\d{2,4})\b")
VALUE_PATTERN = re.compile(r"\$\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|m|k))?", re.IGNORECASE)


def save_debug_html(label, html):
    """Write the raw response to disk so a zero-result search can be diagnosed
    by opening the file, rather than guessing blind."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        safe = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        path = os.path.join(DEBUG_DIR, f"{safe or 'search'}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass


def parse_search_results(html, source_label):
    """Best-effort parse of an AusTender search results page.

    Looks for links to a tender detail page, then pulls the surrounding
    block of text for the title, agency, close date and value. AusTender's
    exact markup was not verified against a live connection when this was
    written, so if this returns nothing for every search term, open one of
    the files written to data/debug/ to see what was actually returned and
    adjust the parsing below (or the request itself, some government search
    pages require a session/cookie rather than plain query parameters).
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  ERROR: beautifulsoup4 is not installed, add it to "
              "scripts/requirements.txt and let the workflow install it.")
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen_hrefs = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not DETAIL_LINK_PATTERN.search(href):
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        title = a.get_text(strip=True)
        if not title or len(title) < 8:
            continue

        container = a.find_parent(["tr", "li", "article", "div"]) or a
        block_text = container.get_text(" ", strip=True)

        date_match = DATE_PATTERN.search(block_text)
        value_match = VALUE_PATTERN.search(block_text)

        full_url = href if href.startswith("http") else f"https://www.tenders.gov.au{href}"

        items.append({
            "title": title,
            "agency": "",
            "state": "National",
            "close_date": date_match.group(1) if date_match else "",
            "value": value_match.group(0) if value_match else "",
            "description": block_text[:400],
            "url": full_url,
            "reference": re.sub(r"\D", "", href) or href,
        })

    if not items:
        save_debug_html(source_label, html)

    return items


def fetch_austender_live(config):
    """
    Searches AusTender's public tender search directly for each term in
    config['live_search_terms'], parses each results page, and returns
    the combined list ready for scoring.

    This has not been run against a live connection to tenders.gov.au from
    the environment this was built in, so the first real run is the real
    test. If every search comes back with zero results, check data/debug/
    for the raw HTML AusTender actually returned, that tells you whether
    the URL, the parsing, or something else (blocked request, needs a
    session) needs fixing. The CSV-import path keeps working regardless.
    """
    try:
        import requests
    except ImportError:
        print("  ERROR: requests is not installed, add it to "
              "scripts/requirements.txt and let the workflow install it.")
        return []

    import time

    terms = config.get("live_search_terms", [])
    if not terms:
        print("  No live_search_terms configured, skipping live fetch.")
        return []

    all_items = []
    headers = {"User-Agent": USER_AGENT}

    for term in terms:
        try:
            resp = requests.get(
                AUSTENDER_SEARCH_URL,
                params={"keyword": term},
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            found = parse_search_results(resp.text, term)
            print(f"  \"{term}\": {len(found)} results")
            all_items.extend(found)
        except Exception as e:
            print(f"  WARNING: search for \"{term}\" failed: {e}")
        time.sleep(REQUEST_DELAY_SECONDS)

    if not all_items:
        print("  Live fetch returned 0 results across every search term. "
              "Check data/debug/*.html to see what AusTender actually sent "
              "back, this almost always means the request needs adjusting "
              "(see the README section on fixing the live fetch).")

    return all_items


def strip_punctuation(s):
    return re.sub(r"[^\w\s]", "", s)


def score_item(item, config):
    text = f"{item.get('title', '')} {item.get('description', '')} {item.get('agency', '')}".lower()
    text_loose = strip_punctuation(text)
    scoring_cfg = config["scoring"]

    reasons = []
    score = 0.0

    # Exclusions first, hard penalty
    for bad in config["exclude_keywords"]:
        if bad in text:
            score -= scoring_cfg["exclusion_penalty"]
            reasons.append(f"Contains excluded term \"{bad}\"")

    # Keyword matches, capped contribution
    keyword_total = 0.0
    matched_keywords = []
    for kw, weight in config["keywords"].items():
        if kw in text:
            keyword_total += weight
            matched_keywords.append(kw)
    keyword_score = min(keyword_total / 10.0, scoring_cfg["keyword_weight_cap"])
    score += keyword_score
    if matched_keywords:
        top = sorted(matched_keywords, key=lambda k: -config["keywords"][k])[:4]
        reasons.append("Matches: " + ", ".join(top))

    # Priority buyer bonus
    buyer_hit = None
    for tier in ("federal", "state"):
        for buyer, weight in config["priority_buyers"][tier].items():
            if strip_punctuation(buyer.lower()) in text_loose:
                buyer_hit = (buyer, tier, weight)
                break
        if buyer_hit:
            break
    if buyer_hit:
        score += scoring_cfg["buyer_bonus"] * (buyer_hit[2] / 9.0)
        reasons.append(f"Priority {buyer_hit[1]} buyer: {buyer_hit[0]}")

    # Related organisation bonus
    for org in config["related_organisations"]:
        if org.lower() in text:
            score += scoring_cfg["related_org_bonus"]
            reasons.append(f"Related organisation: {org}")
            break

    score = max(0.0, min(score, scoring_cfg["max_score"]))
    score = round(score, 1)

    # Capability recommendation: pick the capability with the most matched keywords
    capability = "Supply Chain & Operations Advisory"
    best_count = -1
    for cap, cap_keywords in config["capability_map"].items():
        count = sum(1 for k in cap_keywords if k in text)
        if count > best_count:
            best_count = count
            capability = cap

    excluded = score <= 0.0 and any(
        bad in text for bad in config["exclude_keywords"]
    )

    return score, reasons, capability, excluded


def build_record(item, config):
    score, reasons, capability, excluded = score_item(item, config)
    return {
        "title": item.get("title", "").strip(),
        "agency": item.get("agency", "").strip(),
        "state": item.get("state", "").strip(),
        "close_date": parse_date(item.get("close_date")),
        "publish_date": parse_date(item.get("publish_date")),
        "value": parse_value(item.get("value")),
        "description": item.get("description", "").strip(),
        "url": item.get("url", "").strip(),
        "reference": item.get("reference", "").strip(),
        "match_score": score,
        "match_reasons": reasons,
        "recommended_capability": capability,
        "excluded": excluded,
    }


def dedupe(records):
    seen = {}
    for r in records:
        key = (r["reference"] or r["title"]).lower().strip()
        if key not in seen:
            seen[key] = r
    return list(seen.values())


def main():
    print("Loading scoring configuration...")
    config = load_config()

    print("Collecting CSV imports from data/incoming/...")
    raw_items = collect_incoming()

    print("Searching AusTender live for Daniel's terms...")
    raw_items.extend(fetch_austender_live(config))

    if not raw_items:
        print("No new source data found. data/tenders.json left unchanged.")
        if not os.path.exists(OUTPUT_PATH):
            os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "tenders": [],
                }, f, indent=2)
        return

    print(f"Scoring {len(raw_items)} tenders...")
    records = [build_record(item, config) for item in raw_items]
    records = dedupe(records)
    records = [r for r in records if not r["excluded"]]
    records.sort(key=lambda r: r["match_score"], reverse=True)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tenders": records,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(records)} scored tenders to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
