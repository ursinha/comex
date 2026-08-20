# comex-tools

Small command-line tools for collecting international trade data from public
sources. Each script is self-contained (Python 3 standard library, except
`sea_routes.py`), parameterized via command-line arguments, and documents its
data source in the module docstring.

| Script | What it does | Source |
|---|---|---|
| `scripts/comtrade.py` | Annual trade of a product (HS6) by partner country, for any reporter country, year and flow (exports/imports) | [UN Comtrade](https://comtradeplus.un.org) public API |
| `scripts/comexstat.py` | Brazilian trade of a product (NCM) broken down by state or partner country | [Comex Stat / MDIC](https://comexstat.mdic.gov.br) API |
| `scripts/worldbank.py` | Any World Bank indicator (GDP by default) for a set of countries and years | [World Bank Indicators API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392) |
| `scripts/sea_routes.py` | Sea-route distance and transit time from an origin port to a list of ports | [searoute](https://github.com/genthalili/searoute-py) (Marnet shipping lanes) |
| `scripts/unga_votes.py` | Voting similarity between a base country and others in the UN General Assembly for a given year, with optional highlighted resolutions | [UN Digital Library](https://digitallibrary.un.org/record/4060887) voting dataset |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install searoute   # only needed by sea_routes.py
```

## Examples

```bash
# Exports of HS 100590 (maize) reported by Brazil in 2025, top 20 partners
python3 scripts/comtrade.py --hs 100590 --year 2025 --country BRA --flow X --top 20

# Brazilian exports of an NCM product by state of origin
python3 scripts/comexstat.py --ncm 10059010 --year 2025 --flow export --by state

# GDP (current US$) for a few countries, 2020-2025
python3 scripts/worldbank.py --countries ARG,CHL,URY --years 2020:2025

# Sea routes from a port listed in ports.csv (columns: name,lon,lat), 16 knots
.venv/bin/python scripts/sea_routes.py --ports data/ports.csv --origin Santos --speed 16

# UNGA voting similarity in 2025 between Brazil and three other countries
# (download the CSV from the UN Digital Library record first)
python3 scripts/unga_votes.py --csv data/un_ga_voting.csv --year 2025 \
    --base BRA --countries ARG,CHL,URY --resolutions A/RES/ES-11/7
python3 scripts/unga_votes.py --csv data/un_ga_voting.csv --year 2025 --base BRA --countries ARG --list
```

Every script accepts `-h` for the full list of options. Outputs go to `data/`
by default (raw API responses and CSVs), which is not versioned here.
