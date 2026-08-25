#!/usr/bin/env python3
"""UN General Assembly voting similarity between a base country and others.

Data source: UN Digital Library (Dag Hammarskjöld Library) — official dataset
of all UNGA recorded (roll-call) votes since 1946.
  Record: https://digitallibrary.un.org/record/4060887
  The CSV (~360 MB) is downloaded automatically to --csv (default
  data/un_ga_voting.csv) when the file does not exist: the script reads the
  record page, finds the current CSV attachment and fetches it.

Vote codes in the dataset: Y (yes), N (no), A (abstention), empty = absent.
Two countries "vote together" on a resolution when their codes are identical
(absence counts as its own category).

Usage:
  python3 scripts/unga_votes.py --csv data/un_ga_voting.csv --year 2025 \
      --base BRA --countries CHN,USA,MEX --out data/unga_votes_2025.csv
  # optionally highlight specific resolutions:
  python3 scripts/unga_votes.py ... --resolutions A/RES/ES-11/7,A/RES/80/4
  # a range of years gives a time series of aggregate similarity (one column
  # per country, one row per year) — e.g. to see how alignment shifted:
  python3 scripts/unga_votes.py --year 1988:2025 --base BRA --countries USA,CHN,RUS --out data/unga_series.csv

Output CSV: one row per country with its vote on each highlighted resolution
(if any) and the aggregate similarity with the base country over the year
(share of resolutions with identical votes). A summary is printed.
"""
import argparse
import csv
import os
import re
import sys
import urllib.request
from collections import defaultdict

RECORD_URL = "https://digitallibrary.un.org/record/4060887"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) comex-tools/1.0"}


def ensure_csv(path):
    """Download the UN voting CSV from the Digital Library record if missing."""
    if os.path.exists(path):
        return
    print(f"{path} not found: locating the CSV on {RECORD_URL} ...", file=sys.stderr)
    html = urllib.request.urlopen(urllib.request.Request(RECORD_URL, headers=UA), timeout=60).read().decode()
    m = re.search(r'href="(/record/4060887/files/[^"]+\.csv)"', html)
    if not m:
        sys.exit("could not find a .csv attachment on the record page; download it manually")
    url = "https://digitallibrary.un.org" + m[1]
    print(f"downloading {url} (~360 MB) ...", file=sys.stderr)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, \
            open(path, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    print(f"saved to {path}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="UNGA voting similarity")
    ap.add_argument("--csv", default="data/un_ga_voting.csv",
                    help="path to the UN voting CSV (downloaded if missing; default data/un_ga_voting.csv)")
    ap.add_argument("--year", required=True, help="year (e.g. 2025) or range (e.g. 1988:2025)")
    ap.add_argument("--base", default="BRA", help="base country ISO3 (default BRA)")
    ap.add_argument("--countries", default="",
                    help="comma-separated ISO3 codes to compare with the base country (not needed with --list)")
    ap.add_argument("--resolutions", default="",
                    help="comma-separated resolution symbols to highlight (optional)")
    ap.add_argument("--out", default=None, help="output CSV path")
    ap.add_argument("--list", action="store_true",
                    help="only list the resolutions voted in the year (or range) and exit")
    ap.add_argument("--filter", default="",
                    help="with --list: show only titles containing this text (case-insensitive)")
    a = ap.parse_args()
    if not a.list and not a.countries:
        ap.error("--countries is required unless --list is given")

    others = [c.strip().upper() for c in a.countries.split(",") if c.strip()]
    countries = [a.base.upper()] + others
    highlights = [r.strip() for r in a.resolutions.split(",") if r.strip()]

    ensure_csv(a.csv)
    y0, y1 = (a.year.split(":") + [None])[:2]
    years = [str(y) for y in range(int(y0), int(y1 or y0) + 1)]
    by_year = {y: defaultdict(dict) for y in years}   # year -> resolution -> {country: vote}
    titles = {}
    with open(a.csv, newline="") as f:
        for r in csv.DictReader(f):
            y = r["date"][:4]
            if y not in by_year:
                continue
            titles.setdefault(r["resolution"], (r["date"], r["title"]))
            if r["ms_code"] in countries:
                by_year[y][r["resolution"]][r["ms_code"]] = r["ms_vote"] or "-"

    if a.list:
        shown = 0
        for res, (date, title) in sorted(titles.items(), key=lambda x: x[1][0]):
            if a.filter and a.filter.lower() not in title.lower():
                continue
            print(f"{date}  {res:<18} {title[:100]}")
            shown += 1
        print(f"\n{shown} of {len(titles)} resolutions with recorded votes in {a.year}")
        return

    base = a.base.upper()
    if len(years) > 1:
        # Time series of aggregate similarity: one row per year, one column per country
        out = a.out or f"data/unga_similarity_{years[0]}_{years[-1]}.csv"
        with open(out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["year", "resolutions"] + others)
            print(f"{'year':<6}{'n':>5}" + "".join(f"{c:>8}" for c in others))
            for y in years:
                vv_all = by_year[y]
                n = len(vv_all)
                sims = [sum(1 for vv in vv_all.values() if vv.get(base, "-") == vv.get(c, "-")) / n
                        if n else float("nan") for c in others]
                w.writerow([y, n] + [round(s, 3) for s in sims])
                print(f"{y:<6}{n:>5}" + "".join(f"{s:>8.3f}" for s in sims))
        print(f"\nSaved to {out}")
        return

    votes = by_year[years[0]]


    agg = {}
    for c in others:
        same = sum(1 for vv in votes.values() if vv.get(base, "-") == vv.get(c, "-"))
        agg[c] = same / len(votes) if votes else float("nan")

    print(f"Resolutions with recorded votes in {a.year}: {len(votes)}\n")
    print(f"Aggregate similarity with {base} (share of identical votes):")
    for c, s in sorted(agg.items(), key=lambda x: -x[1]):
        print(f"  {c}  {s:.3f}")

    if highlights:
        print("\nVotes on highlighted resolutions (Y=yes, N=no, A=abstention, -=absent):")
        print(f"{'resolution':<18}" + "".join(f"{c:>5}" for c in countries))
        for res in highlights:
            vv = votes.get(res, {})
            print(f"{res:<18}" + "".join(f"{vv.get(c, '-'):>5}" for c in countries)
                  + f"   {titles.get(res, ('', ''))[1][:60]}")

    out = a.out or f"data/unga_votes_{a.year}.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country"] + highlights + [f"aggregate_similarity_{a.year}"])
        for c in countries:
            row = [c] + [votes.get(r, {}).get(c, "-") for r in highlights]
            row.append("" if c == base else round(agg[c], 3))
            w.writerow(row)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
