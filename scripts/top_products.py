#!/usr/bin/env python3
"""Top traded products (6-digit HS) of any country in a given year.

Source: UN Comtrade — see comtrade.py for endpoints, key handling and limits.

Two strategies, chosen automatically:
  - With an API key: a single query for all HS6 lines (cmdCode=AG6) with the
    world as partner, then sorted locally.
  - Without a key (public preview, 500 unsorted rows per query): a pruned
    drill-down over the HS hierarchy. Chapter totals (AG2) are fetched first;
    chapters are visited in descending order and their HS6 codes (from the
    Comtrade H6 reference list) are queried in batches, stopping as soon as a
    chapter's total cannot beat the N-th best product found so far. Exact, but
    needs several rate-limited calls (a few minutes).

Usage:
  python3 scripts/top_products.py --country BRA --year 2025 --flow X --top 10
  python3 scripts/top_products.py --country ARG --year 2024 --flow M --top 20

Output: data/comtrade_top_<country>_<year>_<flow>.csv and a ranking printed
to the terminal.
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comtrade import fetch, get_key, query, resolve_country  # noqa: E402

H6_URL = "https://comtradeapi.un.org/files/v1/app/reference/H6.json"
H6_CACHE = "comtrade_h6.json"
BATCH = 400  # HS6 codes per preview query (one row each, below the 500 cap)


def base_params(code, year, flow):
    return {"reporterCode": code, "period": year, "flowCode": flow,
            "partnerCode": 0, "partner2Code": 0, "motCode": 0,
            "customsCode": "C00", "includeDesc": "true"}


def rows_of(d):
    return [r for r in d.get("data", []) if r.get("primaryValue")]


def hs6_by_chapter(out_dir):
    path = os.path.join(out_dir, H6_CACHE)
    if not os.path.exists(path):
        json.dump(fetch(H6_URL), open(path, "w"))
    codes = [r["id"] for r in json.load(open(path))["results"]
             if len(r["id"]) == 6 and r["id"].isdigit()]
    groups = {}
    for c in codes:
        groups.setdefault(c[:2], []).append(c)
    return groups


def with_key(code, year, flow, key):
    d = query({**base_params(code, year, flow), "cmdCode": "AG6"}, key)
    return rows_of(d)


def without_key(code, year, flow, top, out_dir):
    chapters = rows_of(query({**base_params(code, year, flow), "cmdCode": "AG2"}))
    chapters.sort(key=lambda r: -r["primaryValue"])
    groups = hs6_by_chapter(out_dir)
    best = []
    for ch in chapters:
        if len(best) >= top and ch["primaryValue"] <= best[-1]["primaryValue"]:
            break
        codes = groups.get(ch["cmdCode"], [])
        print(f"chapter {ch['cmdCode']} ({ch['primaryValue']/1e9:,.2f} bn): "
              f"{len(codes)} HS6 codes", file=sys.stderr)
        for i in range(0, len(codes), BATCH):
            d = query({**base_params(code, year, flow),
                       "cmdCode": ",".join(codes[i:i + BATCH])})
            best.extend(rows_of(d))
            best.sort(key=lambda r: -r["primaryValue"])
            best = best[:top]
    return best


def main():
    ap = argparse.ArgumentParser(description="Top HS6 products of a country (UN Comtrade)")
    ap.add_argument("--country", required=True, help="reporter country: ISO3 or M49 code")
    ap.add_argument("--year", required=True, help="year (e.g. 2025)")
    ap.add_argument("--flow", default="X", choices=["X", "M"],
                    help="X = exports, M = imports (default X)")
    ap.add_argument("--top", type=int, default=10, help="how many products (default 10)")
    ap.add_argument("--out-dir", default="data", help="output directory (default data/)")
    ap.add_argument("--key", default=None, help="Comtrade subscription key (optional)")
    a = ap.parse_args()

    key = get_key(a.key)
    os.makedirs(a.out_dir, exist_ok=True)
    code, iso3 = resolve_country(a.country, a.out_dir)

    if key:
        rows = with_key(code, a.year, a.flow, key)
    else:
        print("no API key: using pruned drill-down over the public preview endpoint",
              file=sys.stderr)
        rows = without_key(code, a.year, a.flow, a.top, a.out_dir)
    if not rows:
        sys.exit(f"No data for {iso3}, {a.year}, flow {a.flow}.")
    rows.sort(key=lambda r: -r["primaryValue"])

    total_d = query({**base_params(code, a.year, a.flow), "cmdCode": "TOTAL"}, key)
    total = rows_of(total_d)[0]["primaryValue"] if rows_of(total_d) else sum(r["primaryValue"] for r in rows)

    out = os.path.join(a.out_dir, f"comtrade_top_{iso3}_{a.year}_{a.flow}.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "hs6", "description", "value_usd", "share"])
        for i, r in enumerate(rows[: a.top], 1):
            w.writerow([i, r["cmdCode"], r.get("cmdDesc", ""), f"{r['primaryValue']:.0f}",
                        f"{r['primaryValue']/total:.4f}"])

    flow_name = "exports" if a.flow == "X" else "imports"
    print(f"\n{iso3} — top {a.top} {flow_name} by HS6 in {a.year} "
          f"(total US$ {total:,.0f})\n")
    print(f"{'#':<4}{'HS6':<8}{'Product':<52}{'US$ million':>14}{'%':>7}")
    for i, r in enumerate(rows[: a.top], 1):
        v = r["primaryValue"]
        print(f"{i:<4}{r['cmdCode']:<8}{r.get('cmdDesc', '')[:50]:<52}{v/1e6:>14,.0f}{100*v/total:>6.1f}%")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
