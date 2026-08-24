#!/usr/bin/env python3
"""Query the UN Comtrade public API: annual trade by partner country.

Source: UN Comtrade (United Nations Statistics Division).
  - Without an API key, the public "preview" endpoint is used:
      https://comtradeapi.un.org/public/v1/preview/C/A/HS
    limited to 500 records per query, unsorted, and rate-limited (HTTP 429;
    this script retries with backoff).
  - With a free subscription key (register at https://comtradeplus.un.org),
    the full endpoint is used instead, returning up to 100k records per call:
      https://comtradeapi.un.org/data/v1/get/C/A/HS
    The key is read from --key, the COMTRADE_API_KEY environment variable, or
    a file named .comtrade_key in the current directory (keep it out of git).
  - values in US$ FOB (exports) / CIF (imports), field `primaryValue`
  Developer docs: https://comtradedeveloper.un.org
  Manual cross-check UI: https://comtradeplus.un.org

Usage:
  python3 scripts/comtrade.py --hs 100590 --year 2025 --country BRA --flow X
  python3 scripts/comtrade.py --hs 870380 --year 2025 --country 76 --flow M --top 15

  --country accepts an M49 numeric code (76 = Brazil) or ISO3 (BRA); the
  reporter list is downloaded from the API on first run and cached in
  <out-dir>/comtrade_reporters.json.

Output: <out-dir>/comtrade_<hs>_<year>_<country>_<flow>.json (raw response,
default out-dir data/) and a partner ranking printed to the terminal.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

PREVIEW = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
FULL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
KEY_FILE = ".comtrade_key"
REPORTERS_URL = "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json"
REPORTERS_CACHE = "comtrade_reporters.json"
RETRIES = 4


def get_key(explicit=None):
    """Return the API key from --key, the environment or .comtrade_key, else None."""
    if explicit:
        return explicit
    if os.environ.get("COMTRADE_API_KEY"):
        return os.environ["COMTRADE_API_KEY"]
    if os.path.exists(KEY_FILE):
        return open(KEY_FILE).read().strip() or None
    return None


def fetch(url, key=None):
    """GET a JSON URL, retrying with exponential backoff on HTTP 429."""
    headers = {"User-Agent": "comex-tools/1.0"}
    if key:
        headers["Ocp-Apim-Subscription-Key"] = key
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < RETRIES - 1:
                wait = 15 * (2 ** attempt)
                print(f"rate limited (429), retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def query(params, key=None):
    """Run a trade query; uses the full endpoint when a key is available."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return fetch(f"{FULL if key else PREVIEW}?{qs}", key)


def resolve_country(country, out_dir):
    """Accept an M49 numeric code ('76') or ISO3 ('BRA'); return (code, iso3)."""
    cache = os.path.join(out_dir, REPORTERS_CACHE)
    if not os.path.exists(cache):
        json.dump(fetch(REPORTERS_URL), open(cache, "w"))
    reporters = json.load(open(cache))["results"]
    if country.isdigit():
        for r in reporters:
            if str(r["id"]) == country:
                return country, r.get("reporterCodeIsoAlpha3", country)
        return country, country
    for r in reporters:
        if r.get("reporterCodeIsoAlpha3", "").upper() == country.upper():
            return str(r["id"]), country.upper()
    sys.exit(f"Country '{country}' not found (use ISO3 or an M49 numeric code).")


def main():
    ap = argparse.ArgumentParser(description="Annual trade by partner (UN Comtrade)")
    ap.add_argument("--hs", required=True, help="6-digit HS product code (e.g. 100590)")
    ap.add_argument("--year", required=True, help="year (e.g. 2025)")
    ap.add_argument("--country", default="BRA", help="reporter country: ISO3 or M49 (default BRA)")
    ap.add_argument("--flow", default="X", choices=["X", "M"],
                    help="X = exports, M = imports (default X)")
    ap.add_argument("--top", type=int, default=15, help="how many partners to list")
    ap.add_argument("--out-dir", default="data", help="directory for raw JSON output (default data/)")
    ap.add_argument("--key", default=None, help="Comtrade subscription key (optional)")
    a = ap.parse_args()

    key = get_key(a.key)
    os.makedirs(a.out_dir, exist_ok=True)
    code, iso3 = resolve_country(a.country, a.out_dir)
    d = query({"reporterCode": code, "period": a.year, "cmdCode": a.hs,
               "flowCode": a.flow, "partnerCode": "", "partner2Code": 0,
               "motCode": 0, "customsCode": "C00", "includeDesc": "true"}, key)

    out = os.path.join(a.out_dir, f"comtrade_{a.hs}_{a.year}_{iso3}_{a.flow}.json")
    json.dump(d, open(out, "w"))

    rows = [r for r in d.get("data", []) if r["partnerCode"] != 0 and r.get("primaryValue")]
    world = [r for r in d.get("data", []) if r["partnerCode"] == 0 and r.get("primaryValue")]
    if not rows and not world:
        sys.exit(f"No data for HS {a.hs}, {a.year}, {iso3}, flow {a.flow}.")
    total = world[0]["primaryValue"] if world else sum(r["primaryValue"] for r in rows)
    desc = (world or rows)[0].get("cmdDesc", "")
    flow_name = "exports" if a.flow == "X" else "imports"

    print(f"{iso3} — {flow_name} of HS {a.hs} in {a.year}")
    print(f"Product: {desc}")
    print(f"World total: US$ {total:,.0f} | {len(rows)} partners | raw: {out}\n")
    rows.sort(key=lambda r: -r["primaryValue"])
    print(f"{'#':<4}{'Partner':<32}{'ISO':<6}{'US$ 1000':>14}{'%':>7}")
    for i, r in enumerate(rows[: a.top], 1):
        v = r["primaryValue"]
        name = r.get("partnerDesc") or r.get("partnerISO", "?")
        print(f"{i:<4}{name:<32}{r.get('partnerISO','?'):<6}{v/1000:>14,.1f}{100*v/total:>6.1f}%")


if __name__ == "__main__":
    main()
