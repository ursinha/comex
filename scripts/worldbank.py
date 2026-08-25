#!/usr/bin/env python3
"""Fetch a World Bank indicator for a set of countries and years.

Source: World Bank Indicators API (World Development Indicators), v2.
  https://api.worldbank.org/v2/country/{codes}/indicator/{indicator}?date=...&format=json
  Docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
  Common indicators: NY.GDP.MKTP.CD (GDP, current US$),
  NY.GDP.PCAP.CD (GDP per capita, current US$), SP.POP.TOTL (population).

Usage:
  python3 scripts/worldbank.py --countries CHN,USA,MEX --years 2024:2025
  python3 scripts/worldbank.py --countries CHN,USA,MEX --years 2025 --sort value  # largest first
  python3 scripts/worldbank.py --countries BRA --indicator SP.POP.TOTL --years 2020:2025 \
      --out data/population.csv

Output: a table printed to the terminal; with --out, a CSV with columns
country,iso3,year,value (raw API JSON saved alongside). Missing values are
reported as empty.
"""
import argparse
import csv
import json
import os
import urllib.request

BASE = "https://api.worldbank.org/v2/country/{codes}/indicator/{indicator}"


def main():
    ap = argparse.ArgumentParser(description="World Bank indicator by country and year")
    ap.add_argument("--countries", required=True, help="comma-separated ISO3 codes")
    ap.add_argument("--indicator", default="NY.GDP.MKTP.CD",
                    help="indicator code (default NY.GDP.MKTP.CD = GDP, current US$)")
    ap.add_argument("--years", required=True, help="year or range, e.g. 2025 or 2020:2025")
    ap.add_argument("--out", default=None, help="write the result as CSV to this path (otherwise print only)")
    ap.add_argument("--sort", default="given", choices=["given", "value", "name"],
                    help="row order: as given in --countries (default), by value (largest first) "
                         "or by country name")
    a = ap.parse_args()

    codes = ";".join(c.strip().upper() for c in a.countries.split(",") if c.strip())
    url = (BASE.format(codes=codes, indicator=a.indicator)
           + f"?date={a.years}&format=json&per_page=2000")
    req = urllib.request.Request(url, headers={"User-Agent": "comex-tools/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    if len(payload) < 2 or not payload[1]:
        raise SystemExit(f"No data returned: {payload[0] if payload else payload}")

    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        json.dump(payload, open(a.out.rsplit(".", 1)[0] + "_raw.json", "w"))

    if a.sort == "value":
        rows = sorted(payload[1], key=lambda r: (r["date"], -(r["value"] or 0)))
    elif a.sort == "name":
        rows = sorted(payload[1], key=lambda r: (r["country"]["value"], r["date"]))
    else:
        order = {c: i for i, c in enumerate(codes.split(";"))}
        rows = sorted(payload[1], key=lambda r: (r["date"], order.get(r["countryiso3code"], 999)))
    if a.out:
        with open(a.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["country", "iso3", "year", "value"])
            for r in rows:
                w.writerow([r["country"]["value"], r["countryiso3code"], r["date"],
                            "" if r["value"] is None else r["value"]])

    print(f"{a.indicator} — {len(rows)} rows\n")
    print(f"{'Country':<28}{'ISO3':<6}{'Year':<6}{'Value':>22}")
    for r in rows:
        v = "" if r["value"] is None else f"{r['value']:,.0f}"
        print(f"{r['country']['value']:<28}{r['countryiso3code']:<6}{r['date']:<6}{v:>22}")
    if a.out:
        print(f"\nSaved to {a.out}")


if __name__ == "__main__":
    main()
