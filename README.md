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

## Examples

```bash
# Exports of HS 100590 (maize) reported by Brazil in 2025, top 20 partners
python3 scripts/comtrade.py --hs 100590 --year 2025 --country BRA --flow X --top 20

# Same, with the mode of transport (sea/road/rail/air) of each top partner,
# or for a single partner
python3 scripts/comtrade.py --hs 100590 --year 2025 --country BRA --flow X --top 10 --mode
python3 scripts/comtrade.py --hs 100590 --year 2025 --country BRA --flow X --partner ARG --mode

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
python3 scripts/main_ports.py --plsci data/plsci.7z --countries ARG,CHL,URY --origin BRSSZ --ports-out data/ports.csv
# or just look up coordinates for known UN/LOCODEs
python3 scripts/main_ports.py --locodes CNSHA,NLRTM,USNYC --origin BRSSZ --ports-out data/ports.csv

# Sea routes from a port listed in ports.csv (columns: name,lon,lat), 16 knots
.venv/bin/python scripts/sea_routes.py --ports data/ports.csv --origin Santos --speed 16

# UNGA voting similarity in 2025 between Brazil and three other countries
# (the ~360 MB voting CSV is downloaded from the UN Digital Library on first run)
python3 scripts/unga_votes.py --year 2025 --base BRA --countries ARG,CHL,URY --resolutions A/RES/ES-11/7
python3 scripts/unga_votes.py --year 2022:2025 --list --filter Ukraine   # find resolution symbols
```

Every script accepts `-h` for the full list of options. Outputs go to `data/`
by default (raw API responses and CSVs), which is not versioned here.
