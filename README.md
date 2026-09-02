# comex-tools

Small command-line tools for collecting international trade data from public
sources. Each script is self-contained (Python 3 standard library, except
`sea_routes.py`), parameterized via command-line arguments, and documents its
data source in the module docstring.

| Script | What it does | Source |
|---|---|---|
| `scripts/comtrade.py` | Annual trade of a product (HS6) by partner country, for any reporter country, year and flow (exports/imports); optional mode-of-transport breakdown per partner | [UN Comtrade](https://comtradeplus.un.org) public API |
| `scripts/top_products.py` | Top N traded products (HS6) of any country, year and flow — single query with an API key, pruned drill-down over the HS hierarchy without one | [UN Comtrade](https://comtradeplus.un.org) |
| `scripts/comexstat.py` | Brazilian trade broken down by state, partner country, product (NCM or HS6), customs unit (port) or transport mode | [Comex Stat / MDIC](https://comexstat.mdic.gov.br) API |
| `scripts/worldbank.py` | Any World Bank indicator (GDP by default) for a set of countries and years | [World Bank Indicators API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392) |
| `scripts/sea_routes.py` | Sea-route distance and transit time from an origin port to a list of ports | [searoute](https://github.com/genthalili/searoute-py) (Marnet shipping lanes) |
| `scripts/main_ports.py` | Main container port of each country (highest UNCTAD PLSCI) and official port coordinates (UN/LOCODE), writing the ports CSV used by `sea_routes.py` | [UNCTADstat PLSCI](https://unctadstat.unctad.org/datacentre/dataviewer/US.PLSCI) (manual bulk download), [UN/LOCODE mirror](https://github.com/datasets/un-locode) |
| `scripts/unga_votes.py` | Voting similarity between a base country and others in the UN General Assembly for a given year, with optional highlighted resolutions | [UN Digital Library](https://digitallibrary.un.org/record/4060887) voting dataset |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install searoute   # only needed by sea_routes.py
```

UN Comtrade works without a key (public preview endpoint: 500 unsorted rows
per query, rate-limited; the scripts retry on HTTP 429 and `top_products.py`
works around the row cap). Subscription keys are currently issued only to
premium (paid/institutional) subscribers; if you have one, pass it with
`--key`, the `COMTRADE_API_KEY` environment variable, or a `.comtrade_key`
file in the working directory (git-ignored) and the full endpoint is used.

## Sea distances step by step

`main_ports.py` and `sea_routes.py` work as a pipeline: the first decides
which port represents each country and writes a ports CSV; the second
computes distance and transit time from an origin to every port in that CSV.

1. Download the UNCTAD PLSCI bulk file (the only manual step):
   open https://unctadstat.unctad.org/datacentre/dataviewer/US.PLSCI and use
   the bulk download button next to the CSV one. You get a `.7z` archive
   containing `US_PLSCI.csv`; save it as `data/plsci.7z` (extracting the .7z
   requires the `7z` command-line tool, or extract it yourself and pass the
   .csv). The PLSCI scores ~900 container ports each quarter; the script
   picks, for each requested country, the port with the highest score in the
   latest quarter.

2. Build the ports CSV:

   ```bash
   python3 scripts/main_ports.py --plsci data/plsci.7z \
       --dest-countries ARG,CHL,URY --origin BRSSZ --ports-out data/ports.csv
   ```

   `--origin` takes the UN/LOCODE of the departure port (BRSSZ = Santos).
   Coordinates come from the UN/LOCODE table (downloaded automatically from
   the open mirror at https://github.com/datasets/un-locode); when a port has
   no coordinates there, the script falls back to another entry of the same
   city and says so in the output. Useful flags: `--top 3` shows the three
   best-connected ports per country before you commit to one; `--choose
   ISO3=LOCODE` overrides the pick for a country (e.g. a port on a specific
   coast); `--set LOCODE=lon,lat` forces coordinates manually.

3. Compute distances and times:

   ```bash
   .venv/bin/python scripts/sea_routes.py --ports data/ports.csv \
       --origin Santos --speed 14 --out data/sea_routes.csv
   ```

   Distances are shortest paths over the Marnet shipping-lane network
   (Eurostat) via the `searoute` library, so they follow real corridors and
   passages (Suez, Panama, Cape of Good Hope). Time is distance divided by
   the given speed: it is pure sailing time, with no port calls, waiting or
   canal transit. 14 knots matches the default of the Searates calculator
   and the observed container-fleet average for 2024 (Clarksons Research);
   pass another `--speed` to taste.

## Examples

```bash
# Exports of HS 100590 (maize) reported by Brazil in 2025, top 20 partners
python3 scripts/comtrade.py --hs 100590 --year 2025 --country BRA --flow X --top 20

# Same, with the mode of transport (sea/road/rail/air) of each top partner,
# or for a single partner
python3 scripts/comtrade.py --hs 100590 --year 2025 --country BRA --flow X --top 10 --mode
python3 scripts/comtrade.py --hs 100590 --year 2025 --country BRA --flow X --partner ARG --mode

# The world's exporters of a product (every reporting country vs the world)
python3 scripts/comtrade.py --hs 090111 --year 2024 --country ALL --flow X --top 15

# Top 10 export products of Argentina in 2024 (any country works)
python3 scripts/top_products.py --country ARG --year 2024 --flow X --top 10

# Brazilian exports of an NCM product by state of origin
python3 scripts/comexstat.py --ncm 10059010 --year 2025 --flow export --by state

# Top 10 Brazilian export products in 2025, NCM lines aggregated to 6-digit HS
python3 scripts/comexstat.py --year 2025 --flow export --by hs6 --top 10

# GDP (current US$) for a few countries, 2020-2025
python3 scripts/worldbank.py --countries ARG,CHL,URY --years 2020:2025

# Main port of each country = highest UNCTAD PLSCI (bulk .7z downloaded from
# the UNCTADstat page), with official UN/LOCODE coordinates, as a ports CSV
python3 scripts/main_ports.py --plsci data/plsci.7z --dest-countries ARG,CHL,URY --origin BRSSZ --ports-out data/ports.csv
# or just look up coordinates for known UN/LOCODEs
python3 scripts/main_ports.py --dest-locodes CNSHA,NLRTM,USNYC --origin BRSSZ --ports-out data/ports.csv

# Sea routes from a port listed in ports.csv (columns: name,lon,lat), 16 knots
.venv/bin/python scripts/sea_routes.py --ports data/ports.csv --origin Santos --speed 16 --out data/sea_routes.csv

# UNGA voting similarity in 2025 between Brazil and three other countries
# (the ~360 MB voting CSV is downloaded from the UN Digital Library on first run)
python3 scripts/unga_votes.py --year 2025 --base BRA --countries ARG,CHL,URY --resolutions A/RES/ES-11/7
python3 scripts/unga_votes.py --year 2022:2025 --list --filter Ukraine   # find resolution symbols
```

Every script accepts `-h` for the full list of options.

By default the scripts only print their result; pass `--out somefile.csv` to
also save it. The two Comtrade scripts (`comtrade.py`, `top_products.py`) are
the exception: they always save the raw API response plus a result CSV into
`--out-dir` (default `data/`), because each query is rate-limited and the raw
response documents where the numbers came from. Reference tables downloaded
on first use (country codes, HS codes, UN/LOCODE) are cached in the same
directory. Nothing in `data/` is committed to this repository.
