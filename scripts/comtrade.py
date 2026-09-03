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
  # mode of transport (sea/road/rail/air/...) for each of the top partners,
  # one extra query per partner; or for a single partner with --partner:
  python3 scripts/comtrade.py --hs 020230 --year 2025 --country BRA --flow X --top 10 --mode
  python3 scripts/comtrade.py --hs 020230 --year 2025 --country BRA --flow X --partner CHL --mode

  Mode of transport (Comtrade motCode) is reported by many, but not all,
  countries; when the reporter does not break it down, the table shows "n/a".

  --country accepts an M49 numeric code (76 = Brazil) or ISO3 (BRA); the
  reporter list is downloaded from the API on first run and cached in
  <out-dir>/comtrade_reporters.json. --country ALL flips the question: it
  ranks every reporting country by its trade of the product with the world
  (e.g. the world's exporters of HS 020230):
  python3 scripts/comtrade.py --hs 020230 --year 2025 --country ALL --flow X --top 15

Output: <out-dir>/comtrade_<hs>_<year>_<country>_<flow>.json (raw response)
and .csv (rank, partner, iso3, value_usd, share, and mode of transport when
--mode is given), default out-dir data/; the ranking is also printed.
"""
import argparse
import csv
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
PARTNERS_URL = "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json"
PARTNERS_CACHE = "comtrade_partners.json"
# Comtrade motCode is hierarchical: 1000 air; 2000 water (2100 sea, 2200 inland
# waterway, 2900 water n.e.c.); 3000 land (3100 rail, 3200 road, 3900 land
# n.e.c.); 9000 other (9100 pipelines and cables). Reporters sometimes use the
# generic parent code (e.g. 2000) without specifying the child.
MODE_LABELS = {"1000": "air", "2000": "water (unspecified)", "2100": "sea",
               "2200": "inland waterway", "2900": "water n.e.c.", "3000": "land (unspecified)",
               "3100": "rail", "3200": "road", "3900": "land n.e.c.", "9000": "other",
               "9100": "pipeline"}
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
                # Honour the server's Retry-After header when present; otherwise back off
                retry_after = e.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 15 * (2 ** attempt)
                body = e.read().decode(errors="replace").strip()[:200]
                print(f"HTTP 429 (server says: {body or 'no message'}); retrying in {wait}s...",
                      file=sys.stderr)
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


def resolve_partner(partner, out_dir):
    """Accept an M49 code or ISO3 for a partner area; return (code, iso3)."""
    cache = os.path.join(out_dir, PARTNERS_CACHE)
    if not os.path.exists(cache):
        json.dump(fetch(PARTNERS_URL), open(cache, "w"))
    partners = json.load(open(cache))["results"]
    for r in partners:
        if (partner.isdigit() and str(r["id"]) == partner) or \
           r.get("PartnerCodeIsoAlpha3", "").upper() == partner.upper():
            return str(r["id"]), r.get("PartnerCodeIsoAlpha3", partner)
    sys.exit(f"Partner '{partner}' not found (use ISO3 or an M49 numeric code).")


def mode_breakdown(code, year, hs, flow, partner_code, key):
    """Return {label: value} of the flow to one partner by mode of transport,
    plus the reported total (None values when the reporter gives no breakdown)."""
    d = query({"reporterCode": code, "period": year, "cmdCode": hs, "flowCode": flow,
               "partnerCode": partner_code, "partner2Code": 0, "motCode": "",
               "customsCode": "C00", "includeDesc": "true"}, key)
    rows = [r for r in d.get("data", []) if r.get("primaryValue")]
    total = next((r["primaryValue"] for r in rows if str(r["motCode"]) == "0"), None)
    modes = {}
    for r in rows:
        mc = str(r["motCode"])
        if mc == "0":
            continue
        label = MODE_LABELS.get(mc, f"mode {mc}")
        modes[label] = modes.get(label, 0) + r["primaryValue"]
    return modes, total


def mode_line(modes, total):
    """Format the modal shares as 'road 99.8% · sea 0.2%' (largest first)."""
    if not modes or not total:
        return "n/a (reporter gives no mode breakdown)"
    parts = sorted(modes.items(), key=lambda kv: -kv[1])
    return " · ".join(f"{k} {100*v/total:.1f}%" for k, v in parts if v / total >= 0.0005)


def world_ranking(a, key):
    """--country ALL: every reporter's trade of the product with the world, ranked."""
    d = query({"reporterCode": "", "period": a.year, "cmdCode": a.hs, "flowCode": a.flow,
               "partnerCode": 0, "partner2Code": 0, "motCode": 0, "customsCode": "C00",
               "includeDesc": "true"}, key)
    out = os.path.join(a.out_dir, f"comtrade_{a.hs}_{a.year}_ALL_{a.flow}.json")
    json.dump(d, open(out, "w"))
    rows = [r for r in d.get("data", []) if r.get("primaryValue")]
    if not rows:
        sys.exit(f"No data for HS {a.hs}, {a.year}, flow {a.flow}.")
    if d.get("count") == 500:
        print("warning: 500 rows returned, the public endpoint may have truncated the list",
              file=sys.stderr)
    rows.sort(key=lambda r: -r["primaryValue"])
    total = sum(r["primaryValue"] for r in rows)
    flow_name = "exporters" if a.flow == "X" else "importers"
    print(f"World {flow_name} of HS {a.hs} in {a.year} (reporting countries)")
    print(f"Product: {rows[0].get('cmdDesc', '')}")
    print(f"Sum of reported values: US$ {total:,.0f} | {len(rows)} reporters | raw: {out}\n")
    print(f"{'#':<4}{'Country':<32}{'ISO':<6}{'US$ 1000':>14}{'%':>7}")
    csv_rows = []
    for i, r in enumerate(rows[: a.top], 1):
        v = r["primaryValue"]
        name = r.get("reporterDesc") or r.get("reporterISO", "?")
        print(f"{i:<4}{name:<32}{r.get('reporterISO', '?'):<6}{v/1000:>14,.1f}{100*v/total:>6.1f}%")
        csv_rows.append([i, name, r.get("reporterISO", ""), f"{v:.0f}", f"{v/total:.4f}"])
    out_csv = out.rsplit(".", 1)[0] + ".csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "country", "iso3", "value_usd", "share_of_reported"])
        w.writerows(csv_rows)
    print(f"\nSaved to {out_csv}")


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Annual trade of one product (6-digit Harmonized System code) broken\n"
            "down by partner country, from UN Comtrade. Works without an API key\n"
            "(public endpoint, rate-limited; the script waits and retries on\n"
            "HTTP 429). --country ALL flips the question and ranks every\n"
            "reporting country's trade of the product with the world."),
        epilog=(
            "examples:\n"
            "  # where Brazil's frozen beef went in 2025, with transport mode\n"
            "  %(prog)s --hs 020230 --year 2025 --country BRA --flow X --top 12 --mode\n"
            "\n"
            "  # one partner only\n"
            "  %(prog)s --hs 020230 --year 2025 --country BRA --flow X --partner CHL --mode\n"
            "\n"
            "  # the world's exporters of coffee\n"
            "  %(prog)s --hs 090111 --year 2024 --country ALL --flow X --top 15\n"))
    ap.add_argument("--hs", required=True, metavar="HS6",
                    help="6-digit HS product code (100590 = maize), or TOTAL for all products")
    ap.add_argument("--year", required=True, metavar="YYYY", help="year (e.g. 2025)")
    ap.add_argument("--country", default="BRA", metavar="ISO3|M49|ALL",
                    help="reporting country (default BRA); ALL ranks every reporter vs the world")
    ap.add_argument("--flow", default="X", choices=["X", "M"],
                    help="X = exports, M = imports (default X)")
    ap.add_argument("--top", type=int, default=15, metavar="N",
                    help="how many partners to list (default 15)")
    ap.add_argument("--out-dir", default="data", metavar="DIR",
                    help="where raw API responses, the result CSV and cached reference "
                         "tables are stored (default data/)")
    ap.add_argument("--key", default=None, metavar="KEY",
                    help="Comtrade subscription key (premium accounts only); also read from "
                         "COMTRADE_API_KEY or a .comtrade_key file")
    ap.add_argument("--partner", default=None, metavar="ISO3|M49",
                    help="restrict the query to a single partner country")
    ap.add_argument("--mode", action="store_true",
                    help="add each partner's transport mode (sea/road/rail/air), as reported "
                         "by the origin country; one extra query per partner")
    ap.add_argument("--pause", type=float, default=2.0, metavar="SECONDS",
                    help="pause between the extra --mode queries, to respect the rate limit (default 2)")
    a = ap.parse_args()

    key = get_key(a.key)
    os.makedirs(a.out_dir, exist_ok=True)
    if a.country.upper() == "ALL":
        return world_ranking(a, key)
    code, iso3 = resolve_country(a.country, a.out_dir)
    partner_code = resolve_partner(a.partner, a.out_dir)[0] if a.partner else ""
    d = query({"reporterCode": code, "period": a.year, "cmdCode": a.hs,
               "flowCode": a.flow, "partnerCode": partner_code, "partner2Code": 0,
               "motCode": 0, "customsCode": "C00", "includeDesc": "true"}, key)

    suffix = f"_{a.partner.upper()}" if a.partner else ""
    out = os.path.join(a.out_dir, f"comtrade_{a.hs}_{a.year}_{iso3}_{a.flow}{suffix}.json")
    json.dump(d, open(out, "w"))

    rows = [r for r in d.get("data", []) if r["partnerCode"] != 0 and r.get("primaryValue")]
    world = [r for r in d.get("data", []) if r["partnerCode"] == 0 and r.get("primaryValue")]
    if not rows and not world:
        sys.exit(f"No data for HS {a.hs}, {a.year}, {iso3}, flow {a.flow}"
                 + (f", partner {a.partner}" if a.partner else "") + ".")
    if a.partner:
        total = sum(r["primaryValue"] for r in rows)   # share of the partner = 100%
    else:
        total = world[0]["primaryValue"] if world else sum(r["primaryValue"] for r in rows)
    desc = (world or rows)[0].get("cmdDesc", "")
    flow_name = "exports" if a.flow == "X" else "imports"

    print(f"{iso3} — {flow_name} of HS {a.hs} in {a.year}"
          + (f" to/from {a.partner.upper()}" if a.partner else ""))
    print(f"Product: {desc}")
    print(f"{'Total' if a.partner else 'World total'}: US$ {total:,.0f} | "
          f"{len(rows)} partners | raw: {out}\n")
    rows.sort(key=lambda r: -r["primaryValue"])
    shown = rows[: a.top]
    print(f"{'#':<4}{'Partner':<32}{'ISO':<6}{'US$ 1000':>14}{'%':>7}"
          + ("   mode of transport" if a.mode else ""))
    csv_rows = []
    for i, r in enumerate(shown, 1):
        v = r["primaryValue"]
        name = r.get("partnerDesc") or r.get("partnerISO", "?")
        line = f"{i:<4}{name:<32}{r.get('partnerISO','?'):<6}{v/1000:>14,.1f}{100*v/total:>6.1f}%"
        mode_txt = ""
        if a.mode:
            if i > 1:
                time.sleep(a.pause)
            modes, mtotal = mode_breakdown(code, a.year, a.hs, a.flow, r["partnerCode"], key)
            mode_txt = mode_line(modes, mtotal or v)
            line += "   " + mode_txt
        print(line)
        csv_rows.append([i, name, r.get("partnerISO", ""), f"{v:.0f}", f"{v/total:.4f}", mode_txt])
    out_csv = out.rsplit(".", 1)[0] + ".csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "partner", "iso3", "value_usd", "share", "mode_of_transport"])
        w.writerows(csv_rows)
    print(f"\nSaved to {out_csv}")


if __name__ == "__main__":
    main()
