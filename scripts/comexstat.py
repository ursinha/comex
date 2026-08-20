#!/usr/bin/env python3
"""Query Comex Stat (Brazilian official trade statistics, MDIC): annual trade
by NCM product, broken down by Brazilian state and/or partner country.

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

Output: CSV (default data/comexstat_<ncm>_<year>_<flow>_<by>.csv) and a
ranking printed to the terminal.
"""
import argparse
import csv
import json
import os
import urllib.request

URL = "https://api-comexstat.mdic.gov.br/general"


def main():
    ap = argparse.ArgumentParser(description="Comex Stat (MDIC) trade by state/country")
    ap.add_argument("--ncm", required=True, help="8-digit NCM code (e.g. 02023000)")
    ap.add_argument("--year", required=True, help="year (e.g. 2025)")
    ap.add_argument("--flow", default="export", choices=["export", "import"])
    ap.add_argument("--by", default="state", choices=["state", "country"],
                    help="breakdown dimension (default state)")
    ap.add_argument("--country", default=None, help="MDIC numeric country code to filter by")
    ap.add_argument("--top", type=int, default=15, help="rows to print")
    ap.add_argument("--out", default=None, help="output CSV path")
    a = ap.parse_args()

    filters = [{"filter": "ncm", "values": [a.ncm]}]
    if a.country:
        filters.append({"filter": "country", "values": [int(a.country)]})
    body = {"flow": a.flow, "monthDetail": False,
            "period": {"from": f"{a.year}-01", "to": f"{a.year}-12"},
            "filters": filters, "details": [a.by], "metrics": ["metricFOB"]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "comex-tools/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        rows = json.load(r)["data"]["list"]
    if not rows:
        raise SystemExit("No data returned (check NCM format: 8 digits as a string).")

    rows.sort(key=lambda r: -float(r["metricFOB"]))
    total = sum(float(r["metricFOB"]) for r in rows)
    out = a.out or f"data/comexstat_{a.ncm}_{a.year}_{a.flow}_{a.by}.csv"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([a.by, "fob_usd"])
        for r in rows:
            w.writerow([r[a.by], r["metricFOB"]])

    label = "exports" if a.flow == "export" else "imports"
    print(f"Brazil — {label} of NCM {a.ncm} in {a.year} by {a.by}"
          + (f" (country {a.country})" if a.country else ""))
    print(f"Total: US$ {total:,.0f} | {len(rows)} rows\n")
    print(f"{'#':<4}{a.by:<28}{'US$ 1000':>14}{'%':>7}")
    for i, r in enumerate(rows[: a.top], 1):
        v = float(r["metricFOB"])
        print(f"{i:<4}{r[a.by]:<28}{v/1000:>14,.1f}{100*v/total:>6.1f}%")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
