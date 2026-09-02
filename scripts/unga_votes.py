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
  # a range with --resolutions gives every country's vote on those resolutions
  # (whatever their year) plus a 0/1 "same as base" column per country:
  python3 scripts/unga_votes.py --year 2022:2025 --base BRA --countries USA,CHN \
      --resolutions A/RES/ES-11/1,A/RES/ES-11/7 --out data/unga_key_votes.csv
  # or every resolution of the range (one row each):
  python3 scripts/unga_votes.py --year 2022:2025 --base BRA --countries USA,CHN \
      --resolutions ALL --out data/unga_all_votes_2022_2025.csv

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
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Voting similarity in the UN General Assembly between a base country\n"
            "and others, from the official roll-call dataset (Dag Hammarskjold\n"
            "Library; ~360 MB, downloaded automatically on first run). Two\n"
            "countries vote together when their records match: yes, no,\n"
            "abstention or absence."),
        epilog=(
            "examples:\n"
            "  # find a resolution's symbol, then get everyone's vote on it\n"
            "  %(prog)s --year 2022:2025 --list --filter Ukraine\n"
            "  %(prog)s --year 2025 --base BRA --countries CHN,USA,CHL \\\n"
            "      --resolutions A/RES/ES-11/7 --out data/unga_votes_2025.csv\n"
            "\n"
            "  # yearly similarity series, e.g. to see foreign-policy shifts\n"
            "  %(prog)s --year 1988:2025 --base BRA --countries USA,CHN,RUS --out data/series.csv\n"))
    ap.add_argument("--csv", default="data/un_ga_voting.csv", metavar="FILE",
                    help="the UN voting dataset (auto-downloaded here if missing)")
    ap.add_argument("--year", required=True, metavar="YYYY[:YYYY]",
                    help="a year (2025) or an inclusive range (1988:2025); a range gives a "
                         "similarity series per year, or a votes table with --resolutions")
    ap.add_argument("--base", default="BRA", metavar="ISO3",
                    help="country against which similarity is measured (default BRA)")
    ap.add_argument("--countries", default="", metavar="ISO3,ISO3,...",
                    help="countries to compare with the base (not needed with --list)")
    ap.add_argument("--resolutions", default="", metavar="SYMBOL,...|ALL",
                    help="resolutions to show votes for (A/RES/ES-11/7), or ALL for every "
                         "resolution in the range; find symbols with --list")
    ap.add_argument("--out", default=None, metavar="FILE",
                    help="save as CSV; without this flag the results are only printed")
    ap.add_argument("--list", action="store_true",
                    help="just list the resolutions voted in the period (date, symbol, title)")
    ap.add_argument("--filter", default="", metavar="TEXT",
                    help="with --list: only titles containing this text (case-insensitive)")
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
        listed = [(date, res, title) for res, (date, title) in sorted(titles.items(), key=lambda x: x[1][0])
                  if not a.filter or a.filter.lower() in title.lower()]
        for date, res, title in listed:
            print(f"{date}  {res:<18} {title[:100]}")
        print(f"\n{len(listed)} of {len(titles)} resolutions with recorded votes in {a.year}")
        if a.out:
            with open(a.out, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "resolution", "title"])
                w.writerows(listed)
            print(f"Saved to {a.out}")
        return

    base = a.base.upper()
    if highlights == ["ALL"]:
        # every resolution voted in the year(s), in date order
        highlights = [res for res, _ in sorted(titles.items(), key=lambda x: x[1][0])]
    if len(years) > 1 and highlights:
        # Votes of every country on the highlighted resolutions, across the whole range
        all_votes = {res: vv for y in years for res, vv in by_year[y].items()}
        print("Votes on highlighted resolutions (Y=yes, N=no, A=abstention, -=absent):")
        print(f"{'resolution':<18}{'date':<12}" + "".join(f"{c:>5}" for c in countries))
        table = []
        for res in highlights:
            vv = all_votes.get(res, {})
            date, title = titles.get(res, ("", ""))
            print(f"{res:<18}{date:<12}" + "".join(f"{vv.get(c, '-'):>5}" for c in countries)
                  + f"   {title[:50]}")
            table.append([res, date, title] + [vv.get(c, "-") for c in countries]
                         + [int(vv.get(c, "-") == vv.get(base, "-")) for c in others])
        if a.out:
            with open(a.out, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["resolution", "date", "title"] + countries
                           + [f"same_as_{base}_{c}" for c in others])
                w.writerows(table)
            print(f"\nSaved to {a.out}")
        return

    if len(years) > 1:
        # Time series of aggregate similarity: one row per year, one column per country
        table = []
        print(f"{'year':<6}{'n':>5}" + "".join(f"{c:>8}" for c in others))
        for y in years:
            vv_all = by_year[y]
            n = len(vv_all)
            sims = [sum(1 for vv in vv_all.values() if vv.get(base, "-") == vv.get(c, "-")) / n
                    if n else float("nan") for c in others]
            table.append([y, n] + [round(s, 3) for s in sims])
            print(f"{y:<6}{n:>5}" + "".join(f"{s:>8.3f}" for s in sims))
        if a.out:
            with open(a.out, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["year", "resolutions"] + others)
                w.writerows(table)
            print(f"\nSaved to {a.out}")
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

    if a.out:
        with open(a.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["country"] + highlights + [f"aggregate_similarity_{a.year}"])
            for c in countries:
                row = [c] + [votes.get(r, {}).get(c, "-") for r in highlights]
                row.append("" if c == base else round(agg[c], 3))
                w.writerow(row)
        print(f"\nSaved to {a.out}")


if __name__ == "__main__":
    main()
