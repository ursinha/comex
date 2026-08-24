#!/usr/bin/env python3
"""Main container port of each country (UNCTAD PLSCI) and official port
coordinates (UN/LOCODE), producing a ports CSV usable by sea_routes.py.

Sources:
  - UNCTADstat, Port Liner Shipping Connectivity Index (PLSCI), quarterly:
      https://unctadstat.unctad.org/datacentre/dataviewer/US.PLSCI
    The site offers no documented API: download the bulk file from the page
    (the "bulk download" button next to "CSV") and pass it with --plsci.
    Ports are identified by UN/LOCODE; the port with the highest PLSCI in a
    country is taken as its main port.
  - UN/LOCODE (UNECE), via the open mirror https://github.com/datasets/un-locode
    (downloaded automatically to <out-dir>/unlocode.csv when missing).
    Coordinates are given as "DDMM[N|S] DDDMM[E|W]" and converted to decimal.
  - Country codes (ISO3 -> ISO2): UN Comtrade partner reference list,
    cached in <out-dir>/comtrade_partners.json (see comtrade.py).

Usage:
  # main port per country from the PLSCI file, and a ports CSV for sea_routes.py
  python3 scripts/main_ports.py --plsci data/plsci.csv --countries CHN,USA,MEX \
      --origin BRSSZ --ports-out data/ports.csv
  # show the 3 best-connected ports of each country instead of only the first
  python3 scripts/main_ports.py --plsci data/plsci.csv --countries CHN,USA --top 3
  # only look up coordinates for a list of UN/LOCODEs (no PLSCI needed)
  python3 scripts/main_ports.py --locodes BRSSZ,CNSHG,USNYC --ports-out data/ports.csv
"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.request

LOCODE_URL = "https://raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv"
PARTNERS_URL = "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json"


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "comex-tools/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())


def parse_coords(s):
    """'2356S 04619W' -> (lon, lat) in decimal degrees; None if missing."""
    m = re.match(r"(\d{2})(\d{2})([NS])\s+(\d{3})(\d{2})([EW])", s or "")
    if not m:
        return None
    lat = int(m[1]) + int(m[2]) / 60
    lon = int(m[4]) + int(m[5]) / 60
    return (-lon if m[6] == "W" else lon, -lat if m[3] == "S" else lat)


def load_locodes(out_dir):
    path = os.path.join(out_dir, "unlocode.csv")
    if not os.path.exists(path):
        print("downloading UN/LOCODE list...", file=sys.stderr)
        download(LOCODE_URL, path)
    table = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            table[r["Country"] + r["Location"]] = r
    return table


def iso3_to_iso2(out_dir):
    path = os.path.join(out_dir, "comtrade_partners.json")
    if not os.path.exists(path):
        download(PARTNERS_URL, path)
    return {r["PartnerCodeIsoAlpha3"]: r["PartnerCodeIsoAlpha2"]
            for r in json.load(open(path))["results"] if r.get("PartnerCodeIsoAlpha3")}


def find_col(cols, *needles):
    for c in cols:
        if all(n.lower() in c.lower() for n in needles):
            return c
    return None


def read_plsci(path):
    """Return {locode: (port_label, value)} for the latest period in the file.
    Column names are located by keyword so that both the bulk and the
    'download CSV' layouts of UNCTADstat work; override with --col-* if needed."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    cols = rows[0].keys()
    c_port = find_col(cols, "port") if not find_col(cols, "port", "label") else find_col(cols, "port", "label")
    c_code = next((c for c in cols if c.lower() in ("port", "port_code", "locode")), None)
    c_time = find_col(cols, "quarter") or find_col(cols, "year") or find_col(cols, "period")
    c_val = find_col(cols, "value") or find_col(cols, "index")
    if not (c_code and c_time and c_val):
        sys.exit(f"could not identify columns in {path}: {list(cols)}")
    latest = max(r[c_time] for r in rows if r.get(c_val))
    out = {}
    for r in rows:
        if r[c_time] == latest and r.get(c_val):
            try:
                out[r[c_code].strip()] = (r.get(c_port, r[c_code]), float(r[c_val]))
            except ValueError:
                pass
    return out, latest


def main():
    ap = argparse.ArgumentParser(description="Main ports (UNCTAD PLSCI) and UN/LOCODE coordinates")
    ap.add_argument("--plsci", help="UNCTADstat PLSCI file (bulk or CSV download)")
    ap.add_argument("--countries", help="comma-separated ISO3 codes (with --plsci)")
    ap.add_argument("--top", type=int, default=1, help="ports to show per country (default 1)")
    ap.add_argument("--locodes", help="comma-separated UN/LOCODEs to look up (no PLSCI needed)")
    ap.add_argument("--origin", help="UN/LOCODE of the origin port to add to the ports CSV")
    ap.add_argument("--ports-out", help="write a name,lon,lat CSV for sea_routes.py")
    ap.add_argument("--out-dir", default="data")
    a = ap.parse_args()
    if not a.plsci and not a.locodes:
        ap.error("give --plsci with --countries, or --locodes")

    os.makedirs(a.out_dir, exist_ok=True)
    locodes = load_locodes(a.out_dir)
    chosen = []   # (country, locode, name, plsci or None)

    if a.plsci:
        if not a.countries:
            ap.error("--countries is required with --plsci")
        iso2 = iso3_to_iso2(a.out_dir)
        plsci, period = read_plsci(a.plsci)
        print(f"PLSCI period used: {period}\n")
        for c3 in [c.strip().upper() for c in a.countries.split(",") if c.strip()]:
            c2 = iso2.get(c3)
            if not c2:
                print(f"{c3}: unknown ISO3", file=sys.stderr)
                continue
            ports = sorted(((v, k, lbl) for k, (lbl, v) in plsci.items() if k.startswith(c2)),
                           reverse=True)
            if not ports:
                print(f"{c3}: no port in PLSCI file", file=sys.stderr)
                continue
            for i, (v, k, lbl) in enumerate(ports[: a.top]):
                if i == 0:
                    chosen.append((c3, k, lbl, v))
                print(f"{c3 if i == 0 else '':<5}{k:<8}{lbl:<36}PLSCI {v:8.2f}")

    if a.locodes:
        for k in [c.strip().upper() for c in a.locodes.split(",") if c.strip()]:
            r = locodes.get(k)
            chosen.append((k[:2], k, r["Name"] if r else k, None))

    if a.origin:
        r = locodes.get(a.origin.upper())
        chosen.insert(0, (a.origin[:2].upper(), a.origin.upper(), r["Name"] if r else a.origin, None))

    print(f"\n{'country':<8}{'locode':<8}{'port':<36}{'lon':>10}{'lat':>9}")
    rows_out = []
    for c, k, name, v in chosen:
        r = locodes.get(k)
        coords = parse_coords(r["Coordinates"]) if r else None
        if coords:
            rows_out.append((name, coords[0], coords[1]))
            print(f"{c:<8}{k:<8}{name[:34]:<36}{coords[0]:>10.3f}{coords[1]:>9.3f}")
        else:
            print(f"{c:<8}{k:<8}{name[:34]:<36}{'no coordinates in UN/LOCODE':>19}")

    if a.ports_out:
        with open(a.ports_out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name", "lon", "lat"])
            w.writerows(rows_out)
        print(f"\nSaved {len(rows_out)} ports to {a.ports_out}")


if __name__ == "__main__":
    main()
