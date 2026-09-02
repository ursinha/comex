#!/usr/bin/env python3
"""Main container port of each country (UNCTAD PLSCI) and official port
coordinates (UN/LOCODE), producing a ports CSV usable by sea_routes.py.

Sources:
  - UNCTADstat, Port Liner Shipping Connectivity Index (PLSCI), quarterly:
      https://unctadstat.unctad.org/datacentre/dataviewer/US.PLSCI
    The site offers no documented API: download the bulk file from the page
    (the "bulk download" button next to "CSV"; it comes as a .7z containing
    US_PLSCI.csv) and pass it with --plsci (.7z, .zip or the extracted .csv;
    .7z needs the `7z` command-line tool).
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
  # override the choice for a country (e.g. the main port on the Atlantic coast)
  python3 scripts/main_ports.py --plsci data/plsci.7z --countries MEX,USA --choose MEX=MXVER
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


def partners(out_dir):
    path = os.path.join(out_dir, "comtrade_partners.json")
    if not os.path.exists(path):
        download(PARTNERS_URL, path)
    return [r for r in json.load(open(path))["results"]
            if r.get("PartnerCodeIsoAlpha3") and r.get("PartnerCodeIsoAlpha2")]


def iso3_to_iso2(out_dir):
    return {r["PartnerCodeIsoAlpha3"]: r["PartnerCodeIsoAlpha2"] for r in partners(out_dir)}


def iso3_to_name(out_dir):
    return {r["PartnerCodeIsoAlpha3"]: r["PartnerDesc"] for r in partners(out_dir)}


def find_col(cols, *needles):
    for c in cols:
        if all(n.lower() in c.lower() for n in needles):
            return c
    return None


def open_plsci(path):
    """Return a text stream for the PLSCI CSV, extracting .7z/.zip bulk files."""
    import io, subprocess, zipfile
    if path.lower().endswith(".zip"):
        z = zipfile.ZipFile(path)
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        return io.TextIOWrapper(z.open(name), encoding="utf-8-sig", newline="")
    if path.lower().endswith(".7z"):
        out = subprocess.run(["7z", "e", "-so", path], capture_output=True, check=True).stdout
        return io.StringIO(out.decode("utf-8-sig"))
    return open(path, newline="", encoding="utf-8-sig")


def read_plsci(path):
    """Return {locode: (port_label, value)} for the latest period in the file.
    Column names are located by keyword so that both the bulk and the
    'download CSV' layouts of UNCTADstat work; override with --col-* if needed."""
    with open_plsci(path) as f:
        rows = list(csv.DictReader(f))
    cols = rows[0].keys()
    c_port = find_col(cols, "port") if not find_col(cols, "port", "label") else find_col(cols, "port", "label")
    c_code = next((c for c in cols if c.lower() in ("port", "port_code", "locode")), None)
    c_time = find_col(cols, "quarter") or find_col(cols, "year") or find_col(cols, "period")
    c_val = next((c for c in cols if ("index" in c.lower() or "value" in c.lower())
                  and not any(x in c.lower() for x in ("footnote", "missing", "label"))), None)
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
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Decide which port represents each country and write a ports CSV\n"
            "(country,iso3,name,locode,lon,lat) ready for sea_routes.py.\n"
            "\n"
            "For every country in --dest-countries, the port with the highest PLSCI\n"
            "(UNCTAD's port connectivity index) in the latest quarter is chosen;\n"
            "coordinates come from the official UN/LOCODE table (fetched\n"
            "automatically). The PLSCI bulk file is the one manual download:\n"
            "https://unctadstat.unctad.org/datacentre/dataviewer/US.PLSCI\n"
            "(bulk button; a .7z containing US_PLSCI.csv)."),
        epilog=(
            "examples:\n"
            "  # the three best-connected ports of each country, to inspect first\n"
            "  %(prog)s --plsci data/plsci.7z --dest-countries ARG,CHL,URY --top 3\n"
            "\n"
            "  # ports CSV with Santos as origin (picked as Brazil's best port)\n"
            "  %(prog)s --plsci data/plsci.7z --dest-countries ARG,CHL,URY \\\n"
            "      --origin BRA --ports-out data/ports.csv\n"
            "\n"
            "  # override one country's pick and one port's coordinates\n"
            "  %(prog)s --plsci data/plsci.7z --dest-countries MEX,USA --choose MEX=MXVER \\\n"
            "      --set PHMNL=120.95,14.60 --origin BRSSZ --ports-out data/ports.csv\n"
            "\n"
            "  # already know which ports you want? skip the PLSCI file entirely:\n"
            "  # this only fetches their coordinates and writes the ports CSV\n"
            "  %(prog)s --dest-locodes CNSHA,NLRTM,USNYC --origin BRSSZ --ports-out data/ports.csv\n"))
    ap.add_argument("--plsci", metavar="FILE",
                    help="PLSCI file from UNCTADstat: the bulk .7z, a .zip or the extracted .csv")
    ap.add_argument("--dest-countries", "--countries", dest="countries", metavar="ISO3,ISO3,...",
                    help="destination countries; each gets its highest-PLSCI port (requires --plsci)")
    ap.add_argument("--top", type=int, default=1, metavar="N",
                    help="show the N best-connected ports of each country instead of only the pick")
    ap.add_argument("--dest-locodes", "--locodes", dest="locodes", metavar="LOCODE,LOCODE,...",
                    help="destination ports given directly by UN/LOCODE: skips the PLSCI choice "
                         "and only looks up their coordinates")
    ap.add_argument("--origin", help="origin port to add to the ports CSV: a UN/LOCODE (BRSSZ) "
                    "or, with --plsci, an ISO3 country code (BRA) to pick its highest-PLSCI port")
    ap.add_argument("--ports-out", metavar="FILE",
                    help="write the resulting ports CSV here (the file sea_routes.py takes as --ports)")
    ap.add_argument("--choose", action="append", default=[], metavar="ISO3=LOCODE",
                    help="override the PLSCI choice for a country with a specific port, e.g. "
                         "MEX=MXVER (its PLSCI rank in the country is shown)")
    ap.add_argument("--set", action="append", default=[], metavar="LOCODE=lon,lat",
                    help="manual coordinates for a LOCODE (repeatable), e.g. PHMNL=120.95,14.60")
    ap.add_argument("--out-dir", default="data", metavar="DIR",
                    help="where reference tables (UN/LOCODE, country codes) are cached (default data/)")
    a = ap.parse_args()
    chosen_ports = {}
    for item in a.choose:
        c3, k = item.split("=", 1)
        chosen_ports[c3.upper()] = k.upper()
    overrides = {}
    for item in a.set:
        k, v = item.split("=", 1)
        lon, lat = (float(x) for x in v.split(","))
        overrides[k.upper()] = (lon, lat)
    if not a.plsci and not a.locodes:
        ap.error("give --plsci with --dest-countries, or --dest-locodes")

    os.makedirs(a.out_dir, exist_ok=True)
    locodes = load_locodes(a.out_dir)
    chosen = []   # (country, locode, name, plsci or None)

    if a.plsci:
        if not a.countries:
            ap.error("--dest-countries is required with --plsci")
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
                print(f"{c3 if i == 0 else '':<5}{k:<8}{lbl:<36}PLSCI {v:8.2f}")
            if c3 in chosen_ports:
                want = chosen_ports[c3]
                rank = next((i + 1 for i, (_, k, _) in enumerate(ports) if k == want), None)
                if rank is None:
                    print(f"{c3}: chosen port {want} not in PLSCI file, using it anyway", file=sys.stderr)
                    chosen.append((c3, want, want, None))
                else:
                    v, k, lbl = ports[rank - 1]
                    print(f"     -> chosen {k} {lbl} (rank {rank} of {len(ports)} in country, PLSCI {v:.2f})")
                    chosen.append((c3, k, lbl, v))
            else:
                v, k, lbl = ports[0]
                chosen.append((c3, k, lbl, v))

    iso2_to_iso3 = {v: k for k, v in iso3_to_iso2(a.out_dir).items()}
    names = iso3_to_name(a.out_dir)
    if a.locodes:
        for k in [c.strip().upper() for c in a.locodes.split(",") if c.strip()]:
            r = locodes.get(k)
            chosen.append((iso2_to_iso3.get(k[:2], k[:2]), k, r["Name"] if r else k, None))

    if a.origin:
        k = a.origin.upper()
        if len(k) == 3 and a.plsci:
            # ISO3 given: pick the country's highest-PLSCI port as origin
            c2 = iso3_to_iso2(a.out_dir).get(k)
            ports_o = sorted(((v, k2, lbl) for k2, (lbl, v) in plsci.items()
                              if c2 and k2.startswith(c2)), reverse=True)
            if not ports_o:
                sys.exit(f"origin '{a.origin}': no port found in the PLSCI file")
            v, k, lbl = ports_o[0]
            print(f"origin {a.origin}: {k} {lbl} (highest PLSCI, {v:.2f})")
        r = locodes.get(k)
        chosen.insert(0, (iso2_to_iso3.get(k[:2], k[:2]), k, r["Name"] if r else k, None))

    print(f"\n{'country':<8}{'locode':<8}{'port':<36}{'lon':>10}{'lat':>9}  source")
    rows_out = []
    for c, k, name, v in chosen:
        r = locodes.get(k)
        coords, src = None, ""
        if k in overrides:
            coords, src = overrides[k], "manual (--set)"
        elif r and parse_coords(r["Coordinates"]):
            coords, src = parse_coords(r["Coordinates"]), "UN/LOCODE"
        else:
            # Fallback: another UN/LOCODE entry of the same country whose name
            # contains the port's name and that has coordinates (e.g. CNSHG
            # "Shanghai Pt" when CNSHA has none)
            # The PLSCI label ("Country, Port") is a better search key than the
            # LOCODE entry's own name (CNSHA is Hongqiao airport in UN/LOCODE).
            base = name.split(",")[-1].split("(")[0].strip().lower()
            cands = [(k2, r2) for k2, r2 in locodes.items()
                     if k2[:2] == k[:2] and base in r2["Name"].lower()
                     and parse_coords(r2["Coordinates"])]
            # prefer entries flagged as ports (function 1), then exact names, then short names
            cands.sort(key=lambda kr: (not kr[1]["Function"].startswith("1"),
                                       kr[1]["Name"].lower() != base, len(kr[1]["Name"])))
            if cands:
                k2, r2 = cands[0]
                coords, src = parse_coords(r2["Coordinates"]), f"UN/LOCODE {k2} ({r2['Name']})"
        short = name.split(",")[-1].strip() if "," in name else name
        if coords:
            rows_out.append((names.get(c, c), c, short, k, round(coords[0], 3), round(coords[1], 3)))
            print(f"{c:<8}{k:<8}{short[:34]:<36}{coords[0]:>10.3f}{coords[1]:>9.3f}  {src}")
        else:
            print(f"{c:<8}{k:<8}{short[:34]:<36}{'NO COORDINATES — use --set':>19}")

    if a.ports_out:
        with open(a.ports_out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["country", "iso3", "name", "locode", "lon", "lat"])
            w.writerows(rows_out)
        print(f"\nSaved {len(rows_out)} ports to {a.ports_out}")


if __name__ == "__main__":
    main()
