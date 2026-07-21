# Job Maps - A US Labor Market Intelligence Tool

Job Maps shows which US metro areas are hiring most and least relative to their size.
There are additional tools breaking down job openings by sector, as well as in-depth analysis of each metro.

**Live site: https://jakebohman.github.io/job-mapping/**

The site is a set of static pages that read pre-built data files. There's no
server and no database to run. The data doesn't update live; instead a scheduled
GitHub Action rebuilds it, commits the fresh numbers, and redeploys, so the live
site and any new clone stay current on their own.

## What you can look at

- **The US map** (`site/index.html`) shades every metro by hiring intensity. Flip
  it to a raw-count view, re-color it by any sector (IT, healthcare, hospitality),
  and hover a metro for its numbers and when it was last updated.
- **The sector index** (`site/sectors.html`) ranks the metros whose hiring mix
  leans furthest from the national average, both over and under: San Francisco
  heavy on tech, Miami on hospitality, Chicago on logistics.
- **Metro detail** (`site/map.html`) pick one metro to see its rate, national rank,
  shape on the map, and the sectors it over- and under-indexes on.

## See it

Just open the live site: **https://jakebohman.github.io/job-mapping/**. Nothing to
install.

To run it locally instead (for development), you need only Python (3.9 or newer).
The repo ships with the generated data, so it works offline with no API keys:

```sh
cd site && python -m http.server 8000    # then open http://localhost:8000
```

## Rebuild it with fresh data

To regenerate the data yourself you'll need two free API keys: **Adzuna** for the
job postings and **BLS** for the workforce numbers. Sign-up links are in
`.env.example`.

```sh
pip install -r requirements.txt      # the only dependency is `requests`
cp .env.example .env                 # then paste your keys into .env

python pipeline/build_all.py         # fetches the data and builds every page
cd site && python -m http.server 8000
```

`build_all.py` runs the whole pipeline in order and prints its progress so you can
watch the map fill in. The free API tiers are slow and capped, so a full rebuild
takes a few days: each run does as much as the daily budget allows, caches what it
fetched, and stops cleanly. Just run it again to pick up where it left off (or
pass `--loop` to let it retry on its own). The committed data keeps the site
working the whole time; only newly collected sector data is pending until the fill
reaches each metro.

If you'd rather run the steps yourself:

```sh
python pipeline/build_geometry.py    # one-time: the map shapes
python pipeline/build_national.py    # the national intensity map
python pipeline/panel.py             # sector data (run repeatedly to fill it in)
```

Each module also checks itself with no network or keys, e.g.
`python pipeline/geo.py --selftest`.

## Automatic updates

Once deployed, the site keeps itself current. A scheduled GitHub Action
(`.github/workflows/rebuild.yml`) runs the same pipeline on GitHub's servers using
the API keys stored as repository secrets, commits the regenerated data, and
redeploys the page. It stays within the free API limits, so the refresh is gradual
rather than instant: sector coverage advances each day, the national counts cycle
over roughly a month, and the workforce figures refresh monthly.

To host your own copy, enable Pages (Settings → Pages → Source: **GitHub Actions**)
and add `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, and `BLS_API_KEY` as repository secrets.

## How it works, briefly

The Python scripts in `pipeline/` pull from three free public sources: job
postings from Adzuna, the workforce of each metro from the Bureau of Labor
Statistics, and the map shapes from the US Census Bureau. They do the math and
write plain JSON and GeoJSON into `site/data/`, which the pages read in the
browser. Turning a rough count of postings into an honest rate takes a couple of
corrections along the way; [METHODOLOGY.md](METHODOLOGY.md) explains all of it in
plain language, including what the map can and can't tell you.

## Project layout

```
job-mapping/
├── README.md          you are here
├── METHODOLOGY.md     where the numbers come from and how they're calculated
├── ROADMAP.md         what's planned next
├── pipeline/          the Python that fetches data and builds the site
│   ├── build_all.py       one command to run everything
│   ├── build_national.py  the US map
│   ├── panel.py           the sector data
│   ├── build_geometry.py  the map shapes (run once)
│   ├── ingest.py          Adzuna requests and repost handling
│   ├── geo.py             matches a posting to its metro
│   └── bls.py             workforce numbers
└── site/              the website (static; nothing to build)
    ├── index.html         the US map
    ├── sectors.html       the sector index
    ├── map.html           single-metro detail
    └── data/              the JSON the pages read
```
