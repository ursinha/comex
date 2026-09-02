#!/usr/bin/env python3
"""Sea-route distances and transit times from one origin port to many ports.

Routes are computed with the `searoute` library (PyPI), which finds the
shortest path over the global Marnet shipping-lane graph (derived from open
data). Transit time = distance / speed, 1 nm = 1.852 km. The methodology is
equivalent to the Searates (DP World) distance/time calculator:
https://www.searates.com/distance-time/

Speed is a premise, not a measurement, and the two usual references differ:
  - 13 knots is the documented default of the Searates calculator ("if speed
    is not set, it will be defaulted to 13 knots for sea transport") —
    https://docs.searates.com/reference/distance/v2/distance-and-transit-time-calculator
  - 14.0 knots is the 2024 average of the world container fleet
    (Clarksons Research).
Pick one and state it: the resulting times differ by about 8%. Either way
this is pure sailing time — no port calls, waiting or canal transit — so it
understates real door-to-door transit on any route that transships.

Library: https://github.com/genthalili/searoute-py

Input: a CSV with at least the columns `name,lon,lat` listing the ports;
any other columns (e.g. `country,iso3,locode` as written by main_ports.py)
are carried over to the output in the same order. The origin is selected by
name with --origin.

Usage:
  python3 scripts/sea_routes.py --ports data/ports.csv --origin "Santos" \
      --speed 16 --out data/sea_routes.json

Output: a summary printed to the terminal; with --out, a CSV (one row per
port: nm, km, hours, days at the given speed) and, if the path ends in .json,
also a JSON keyed by port name.
"""
import argparse
import csv
import json

NM_TO_KM = 1.852


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Distance and transit time from one origin port to every other port\n"
            "in a CSV. Distances follow the real shipping lanes (Marnet network,\n"
            "Eurostat, via the searoute library), so routes bend around continents\n"
            "and through passages such as Suez, Panama and the Cape of Good Hope.\n"
            "Time is distance divided by speed: pure sailing time, with no port\n"
            "calls, waiting or canal transit."),
        epilog=(
            "examples:\n"
            "  # ports.csv as written by main_ports.py\n"
            "  %(prog)s --ports data/ports.csv --origin Santos --speed 14 --out data/sea_routes.csv\n"
            "\n"
            "  # a hand-made CSV works too; only name,lon,lat are required\n"
            "  printf 'name,lon,lat\\nSantos,-46.32,-23.93\\nRotterdam,4.5,51.92\\n' > /tmp/p.csv\n"
            "  %(prog)s --ports /tmp/p.csv --origin Santos\n"))
    ap.add_argument("--ports", required=True, metavar="FILE",
                    help="CSV of ports with at least name,lon,lat; extra columns "
                         "(country, iso3, locode) are carried to the output")
    ap.add_argument("--origin", required=True, metavar="NAME",
                    help="name of the departure port, exactly as in the CSV")
    ap.add_argument("--speed", type=float, default=16.0, metavar="KNOTS",
                    help="sailing speed in knots (default 16; the Searates calculator "
                         "defaults to 13, the 2024 container-fleet average is 14)")
    ap.add_argument("--out", default=None, metavar="FILE",
                    help="save the results: .csv, or .json to also get a JSON; "
                         "without this flag the results are only printed")
    a = ap.parse_args()

    with open(a.ports, newline="") as f:
        rows = list(csv.DictReader(f))
    ports = {r["name"]: (float(r["lon"]), float(r["lat"])) for r in rows}
    extra = {r["name"]: {k: v for k, v in r.items() if k not in ("name", "lon", "lat")} for r in rows}
    if a.origin not in ports:
        raise SystemExit(f"origin '{a.origin}' not found in {a.ports}")
    origin = ports[a.origin]

    # imported here so that --help works without the dependency installed
    import searoute as sr

    out = {}
    for name, coord in ports.items():
        if name == a.origin:
            continue
        # NB: searoute's unit code for nautical miles is "naut" ("nm" is silently
        # misread); ask for km and derive nautical miles ourselves.
        route = sr.searoute(origin, coord, units="km")
        km = route["properties"]["length"]
        nm = km / NM_TO_KM
        hours = nm / a.speed
        out[name] = {**extra.get(name, {}), "nm": round(nm), "km": round(km),
                     "hours": round(hours), "days": round(hours / 24, 1)}
        print(f"{name:<28} {nm:>8,.0f} nm  {km:>9,.0f} km  ~{hours/24:>5.1f} days")

    if not a.out:
        return
    if a.out.lower().endswith(".json"):
        with open(a.out, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    out_csv = a.out.rsplit(".", 1)[0] + ".csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        # keep the input column order (minus lon/lat), then the computed values
        cols = [k for k in rows[0].keys() if k not in ("lon", "lat")]
        w.writerow(cols + ["nm", "km", "hours", "days"])
        for name, v in out.items():
            w.writerow([name if k == "name" else v.get(k, "") for k in cols]
                       + [v["nm"], v["km"], v["hours"], v["days"]])
    print(f"\nSaved to {out_csv}" + (f" and {a.out}" if a.out.lower().endswith(".json") else ""))


if __name__ == "__main__":
    main()
