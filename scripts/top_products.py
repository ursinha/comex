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
    chapter's total cannot beat the N-th best product found so far. Codes from
    several chapters are packed into the same query (as many as fit in the
    URL length the API honours, ~250), and a short pause (--pause) is kept
    between calls to stay under the rate limit.
    Exact; typically 4-6 calls and about a minute.

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
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comtrade import fetch, get_key, query, resolve_country  # noqa: E402

H6_URL = "https://comtradeapi.un.org/files/v1/app/reference/H6.json"
H6_CACHE = "comtrade_h6.json"
# The preview endpoint silently ignores codes beyond roughly 2,000 characters of
# URL (~260 six-digit codes), so batches are packed by URL length, not count.
MAX_CODES_CHARS = 1800


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


def without_key(code, year, flow, top, out_dir, pause):
    """Pruned drill-down: visit chapters in descending order of total value,
    packing their HS6 codes into queries of at most MAX_CODES_CHARS characters
    (chapters may share a query), and stop when the next chapter's total can
    no longer beat the current N-th best product."""
    params = base_params(code, year, flow)
    chapters = rows_of(query({**params, "cmdCode": "AG2"}))
    chapters.sort(key=lambda r: -r["primaryValue"])
    groups = hs6_by_chapter(out_dir)
    best, pending, n_queries = [], [], 1

    def flush():
        nonlocal best, pending, n_queries
        if not pending:
            return
        time.sleep(pause)
        d = query({**params, "cmdCode": ",".join(pending)})
        n_queries += 1
        best.extend(rows_of(d))
        best.sort(key=lambda r: -r["primaryValue"])
        best = best[:top]
        pending = []

    for ch in chapters:
        # Results still pending may raise the bar; check the bound only after flushing
        if len(best) >= top and ch["primaryValue"] <= best[-1]["primaryValue"]:
            flush()
            if len(best) >= top and ch["primaryValue"] <= best[-1]["primaryValue"]:
                break
        codes = groups.get(ch["cmdCode"], [])
        print(f"chapter {ch['cmdCode']} ({ch['primaryValue']/1e9:,.2f} bn): "
              f"{len(codes)} HS6 codes", file=sys.stderr)
        for c in codes:
            if len(",".join(pending)) + 7 > MAX_CODES_CHARS:
                flush()
            pending.append(c)
    flush()
    print(f"{n_queries} queries", file=sys.stderr)
    return best


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "The N most exported (or imported) products of a country in a year,\n"
            "at the 6-digit Harmonized System level, from UN Comtrade. Without an\n"
            "API key it walks the HS hierarchy (chapters first, then only the\n"
            "chapters that can still contain a top-N product), which is exact and\n"
            "takes a minute or two; with a premium key it is a single query."),
        epilog=(
            "examples:\n"
            "  %(prog)s --country BRA --year 2025 --flow X --top 10\n"
            "  %(prog)s --country ARG --year 2024 --flow M --top 20\n"))
    ap.add_argument("--country", required=True, metavar="ISO3|M49",
                    help="the country whose trade is ranked")
    ap.add_argument("--year", required=True, metavar="YYYY", help="year (e.g. 2025)")
    ap.add_argument("--flow", default="X", choices=["X", "M"],
                    help="X = exports, M = imports (default X)")
    ap.add_argument("--top", type=int, default=10, metavar="N",
                    help="how many products (default 10)")
    ap.add_argument("--out-dir", default="data", metavar="DIR",
                    help="where raw responses, the result CSV and cached reference tables "
                         "are stored (default data/)")
    ap.add_argument("--key", default=None, metavar="KEY",
                    help="Comtrade subscription key (premium accounts only); also read from "
                         "COMTRADE_API_KEY or a .comtrade_key file")
    ap.add_argument("--pause", type=float, default=3.0, metavar="SECONDS",
                    help="pause between keyless queries, to respect the rate limit (default 3)")
    a = ap.parse_args()

    key = get_key(a.key)
    os.makedirs(a.out_dir, exist_ok=True)
    code, iso3 = resolve_country(a.country, a.out_dir)

    if key:
        rows = with_key(code, a.year, a.flow, key)
    else:
        print("no API key: using pruned drill-down over the public preview endpoint",
              file=sys.stderr)
        rows = without_key(code, a.year, a.flow, a.top, a.out_dir, a.pause)
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
