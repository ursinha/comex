#!/usr/bin/env python3
"""Query Comex Stat (Brazilian official trade statistics, MDIC): annual trade
broken down by Brazilian state, partner country, product (NCM / HS6), customs
unit of clearance (URF — usually the port of shipment) or transport mode.

Source: Comex Stat API (Ministério do Desenvolvimento, Indústria, Comércio e
Serviços), endpoint POST https://api-comexstat.mdic.gov.br/general
  Web UI for manual cross-check: https://comexstat.mdic.gov.br
  Values in US$ FOB (field metricFOB). Country codes follow the MDIC table
  (e.g. 158 = Chile, 160 = China, 249 = United States); use --country with
  the numeric code, or omit it for all partners.

Usage:
  python3 scripts/comexstat.py --ncm 02023000 --year 2025 --flow export --by state
  python3 scripts/comexstat.py --ncm 02023000 --year 2025 --flow export --by state --country 158
  python3 scripts/comexstat.py --ncm 87038000 --year 2025 --flow import --by country --top 10
  # top products (all NCMs aggregated to 6-digit HS; --ncm not needed):
  python3 scripts/comexstat.py --year 2025 --flow export --by hs6 --top 10
  python3 scripts/comexstat.py --year 2025 --flow export --by ncm --country 158
  # where a product is shipped from (customs unit ~ port) and by which mode:
  python3 scripts/comexstat.py --ncm 27090010 --year 2025 --flow export --by urf
  python3 scripts/comexstat.py --ncm 27090010 --year 2025 --flow export --by via

Output: a ranking printed to the terminal and, with --out, a CSV. For --by hs6 the description shown is that of
the largest NCM line within each HS6 group.
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = "https://api-comexstat.mdic.gov.br/general"
RETRIES = 4


def post(body):
    """POST a JSON body, retrying with exponential backoff on HTTP 429."""
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "comex-tools/1.0"})
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < RETRIES - 1:
                wait = 20 * (2 ** attempt)
                print(f"rate limited (429), retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Brazilian official trade statistics (Comex Stat, MDIC), one year at\n"
            "a time, broken down by --by: Brazilian state of origin, partner\n"
            "country, product (NCM 8-digit lines, or hs6 to aggregate them to the\n"
            "6-digit Harmonized System), customs unit of clearance (urf, usually\n"
            "the port of shipment) or transport mode (via). Values in US$ FOB.\n"
            "NCM = the HS6 code plus two Mercosur digits (020230 -> 02023000)."),
        epilog=(
            "examples:\n"
            "  # which states export a product, and by which transport mode\n"
            "  %(prog)s --ncm 02023000 --year 2025 --flow export --by state\n"
            "  %(prog)s --ncm 02023000 --year 2025 --flow export --by via --country 158\n"
            "\n"
            "  # Brazil's top export products (all NCM lines, aggregated to HS6)\n"
            "  %(prog)s --year 2025 --flow export --by hs6 --top 10\n"
            "\n"
            "  # country codes are MDIC's own (158 = Chile, 160 = China)\n"))
    ap.add_argument("--ncm", default=None, metavar="NCM8",
                    help="8-digit NCM product code (02023000); optional for --by ncm/hs6")
    ap.add_argument("--year", required=True, help="year (e.g. 2025)")
    ap.add_argument("--flow", default="export", choices=["export", "import"])
    ap.add_argument("--by", default="state",
                    choices=["state", "country", "ncm", "hs6", "urf", "via"],
                    help="breakdown dimension (default state); hs6 aggregates NCM lines to "
                         "6 digits; urf = customs unit (port) of clearance; via = transport mode")
    ap.add_argument("--country", default=None, metavar="CODE",
                    help="filter by partner country, MDIC numeric code (158 = Chile)")
    ap.add_argument("--top", type=int, default=15, metavar="N", help="rows to print (default 15)")
    ap.add_argument("--out", default=None, metavar="FILE",
                    help="save as CSV; without this flag the results are only printed")
    a = ap.parse_args()

    if a.by in ("state", "country", "urf", "via") and not a.ncm:
        raise SystemExit(f"--ncm is required for --by {a.by}")
    filters = [{"filter": "ncm", "values": [a.ncm]}] if a.ncm else []
    if a.country:
        filters.append({"filter": "country", "values": [int(a.country)]})
    body = {"flow": a.flow, "monthDetail": False,
            "period": {"from": f"{a.year}-01", "to": f"{a.year}-12"},
            "filters": filters, "details": ["ncm" if a.by == "hs6" else a.by],
            "metrics": ["metricFOB"]}
    rows = post(body)["data"]["list"]
    if not rows:
        raise SystemExit("No data returned (check NCM format: 8 digits as a string).")

    # Normalise to (key, label, value)
    if a.by == "ncm":
        items = [(r["coNcm"], r["ncm"], float(r["metricFOB"])) for r in rows]
    elif a.by == "hs6":
        groups = {}
        for r in rows:
            k, v = r["coNcm"][:6], float(r["metricFOB"])
            g = groups.setdefault(k, {"value": 0.0, "top": (0.0, "")})
            g["value"] += v
            if v > g["top"][0]:
                g["top"] = (v, r["ncm"])
        items = [(k, g["top"][1], g["value"]) for k, g in groups.items()]
    else:
        items = [(r[a.by], r[a.by], float(r["metricFOB"])) for r in rows]

    items.sort(key=lambda t: -t[2])
    total = sum(t[2] for t in items)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([a.by, "description", "fob_usd"])
            for k, label, v in items:
                w.writerow([k, label, f"{v:.0f}"])

    label = "exports" if a.flow == "export" else "imports"
    print(f"Brazil — {label}" + (f" of NCM {a.ncm}" if a.ncm else "") + f" in {a.year} by {a.by}"
          + (f" (country {a.country})" if a.country else ""))
    print(f"Total: US$ {total:,.0f} | {len(items)} rows\n")
    wide = a.by in ("ncm", "hs6")
    head = f"{'#':<4}" + (f"{'code':<10}" if wide else "") + f"{('description' if wide else a.by):<44}"
    print(head + f"{'US$ 1000':>16}{'%':>7}")
    for i, (k, desc, v) in enumerate(items[: a.top], 1):
        line = f"{i:<4}" + (f"{k:<10}" if wide else "") + f"{desc[:42]:<44}"
        print(line + f"{v/1000:>16,.1f}{100*v/total:>6.1f}%")
    if a.out:
        print(f"\nSaved to {a.out}")


if __name__ == "__main__":
    main()
