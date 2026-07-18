# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Job Maps** analyzes US metro labor markets from job postings. It is an
*analysis* tool, **not a job board** — there is deliberately no path from the
site to an application. The guiding principle: **raw posting counts are a
population map and teach nothing; every view is a rate, a share, or a
deviation.** Everything runs on free tiers and deploys as a static site to
GitHub Pages.

Three deliverables (a static page ← a Python build script ← generated JSON):

| Page (`site/`) | Built by (`pipeline/`) | Shows |
|---|---|---|
| `index.html` (landing) | `build_national.py` | US choropleth: postings per 1,000 workers across ~390 metros |
| `sectors.html` | `panel.py` | Ranked list of where a metro's sector *mix* deviates from national |
| `map.html` | `metro_map.py` | Single-metro detail (Columbus): calibrated rate + occupation mix |

## Commands

Run everything from the repo root. There is no framework/lint/CI yet.

```sh
pip install -r requirements.txt          # one dependency: requests
# Keys: put them in a gitignored .env at the repo root (copy .env.example) — it's
# auto-loaded by pipeline/geo.py, so builds run without passing keys. Or export
# them. Needed: ADZUNA_APP_ID, ADZUNA_APP_KEY (all builds), BLS_API_KEY (national
# map), GEMINI_API_KEY (ROADMAP task 5). This repo already has a local .env.

# Build the site data (writes JSON/GeoJSON into site/data/):
python pipeline/build_geometry.py    # one-time: metro/state shapes + vendored d3-geo (no key)
python pipeline/build_national.py    # national map data (~390 Adzuna calls; resumable)
python pipeline/panel.py             # sector index (~10 metros; resumable)
python pipeline/metro_map.py [CBSA]  # single-metro detail JSON (default 18140 = Columbus)
python pipeline/build_crosswalk.py   # rebuild pipeline/cbsa_counties.csv from Census (rare)

# Serve locally:
cd site && python -m http.server 8000     # open http://localhost:8000

# Tests: every module self-tests with no network and no keys. This is the whole
# test suite — run one module's checks with:
python pipeline/geo.py --selftest         # also: ingest, classify, bls, panel, build_national
```

**Verifying the site renders** is hard here: the screenshot tool tends to hang.
Serve it and use the in-app browser's `javascript_tool`/`get_page_text` (check
`document.fonts.check`, per-path `getBBox`, computed fills, simulated hover) —
that's how the map's rendering bugs were caught. Bump the port when re-serving;
old `http.server` processes linger.

## Architecture

**Two-stage, no runtime backend.** Python scripts in `pipeline/` fetch external
data (Adzuna, BLS, Census/TIGERweb), do all the computation, and write **static
JSON + GeoJSON into `site/data/`**. The pages in `site/` are plain HTML/CSS/JS
that `fetch()` those files and render in the browser. No server, no database in
the browser, no build toolchain (no npm/React). Deploys to GitHub Pages as-is.

**`pipeline/geo.py` is the spine.** It loads `cbsa_counties.csv` (the OMB 2023
county↔CBSA crosswalk) into `CBSA_COUNTIES`: a dict of **393 metros (MSAs)**,
each with `name`, `counties` (set), `radius_km`, `adzuna_where` (a geocodable
"City, ST"), `laus_lf_series` (BLS series id), and `state_fips`. Every build
script iterates this dict. `geo.cbsa_of(adzuna_result)` maps a posting to its
CBSA via the county its `location.area` reports — this is the exact join key
between Adzuna postings, BLS series, and Census geometry.

**Two calibration ideas make the free data trustworthy — understand these
before touching the pipeline:**

1. **Counts, not sampled+classified postings.** Adzuna's unkeyworded search is
   *ranked by a few high-volume advertisers*, so a *sample* is biased (one
   hospital network made Dallas read 94% healthcare). A *count* is a census and
   immune to ranking. So the sector index (`panel.py`) uses Adzuna **category
   counts** and their shares, not O*NET-classified samples. This is why
   `sectors.html` shows Adzuna's ~30 categories, not O*NET occupations.

2. **`f_m` (in-CBSA fraction) fixes Adzuna's geography.** Adzuna `where=` is a
   radius around a place, *not* a CBSA boundary, so a small metro's radius
   swallows a big neighbor's postings. `build_national.py` makes one call per
   metro at `results_per_page=50`: the response gives both the total `count`
   **and** 50 postings whose counties reveal the fraction actually in the CBSA
   (`f_m`). `effective = count × f_m` corrects the count to CBSA geography.
   Without this, Columbus IN read 1,246 postings/1,000 workers (it was measuring
   Indianapolis); with it, it correctly grays out (`f_m ≈ 0`).

**Resumable caches.** The Adzuna and BLS builds cache each item as fetched to
`site/data/_*_cache.json` (gitignored: `_national_cache`, `_lf_cache`,
`_mix_cache`) and throttle to the free-tier rate. A run that hits a daily cap
resumes on the next run instead of re-spending calls. Labor force is cached
separately because it's stable month-to-month and its keyless quota is tiny.

**Shared frontend.** All three pages use one design system: `site/fonts.css`
(Fraunces + IBM Plex, embedded woff2 — no CDN), CSS custom-property tokens with
light/dark variants, and a mono cross-nav. `d3-geo` is vendored in
`site/vendor/` (not a CDN). Pages `fetch(..., {cache:'no-store'})` so a data
rebuild is never served stale.

## Non-obvious decisions and invariants

- **CBSA (metro) is the primary key everywhere.** County↔CBSA comes only from
  `cbsa_counties.csv` (OMB July 2023). Don't introduce fuzzy name matching.
- **Small-cell threshold: n ≥ 50.** Metros with fewer than 50 in-CBSA postings
  (or no labor force) gray out — disclosed on the page. (Poisson CV ≤ 15%.)
- **Interim substitutions**, each with an isolated swap-in point:
  - Occupation coding uses the free, keyless **NIOSH NIOCCS autocoder**
    (`classify.py`) in place of an LLM (no LLM key yet). NIOCCS leaves ~21%
    uncoded and is title-only; an LLM reading the description will replace it.
  - Outlier sentences are **templated** from the numbers, not LLM-written.
  - Storage is **JSON**, not the Parquet/DuckDB the long-term design calls for.
- **The rate is uncalibrated for reposts.** Adzuna is repost-saturated (~58% of
  a raw sample were near-duplicates). `ingest.dedupe_semantic` and
  `cap_per_employer` handle the sample path, but the national `count` field
  can't be de-duped — so the map is honest only about *relative* intensity;
  absolute numbers run high and this is disclosed.

## Gotchas that will bite

- **d3-geo winding.** TIGERweb GeoJSON is RFC-7946 wound (CCW exterior); d3-geo
  wants the opposite (CW exterior) or **every polygon fills the whole map**
  (hover shows one metro everywhere). `build_geometry.py` rewinds rings — don't
  remove that step.
- **BLS keyless cap is 25 requests/day.** National labor force (393 metros)
  needs `BLS_API_KEY` (v2: 500/day, 50 series/query); `bls.py` auto-switches.
- **Adzuna limits: ~25 calls/min and a daily cap.** Builds throttle (~2.6 s/call)
  and are resumable; expect a national run to span two days on the free tier.
- **`pkill -f` does NOT kill Python background processes on Windows/git-bash.**
  Use PowerShell: `Get-CimInstance Win32_Process | Where CommandLine -match ... | Stop-Process`.
  (Two build processes once raced and corrupted a cache because `pkill` missed them.)
- **Ambiguous metro names geocode wrong on Adzuna** ("Albany, OR" → Albany NY).
  These self-gray via `f_m ≈ 0`, so they're wrong-but-not-shown, not silently bad.

## Data sources and their limits

| Source | Used for | Key limits |
|---|---|---|
| Adzuna API (free) | Posting counts + category counts; sampled details | ~25/min + daily cap. Descriptions hard-truncated at 500 chars. `where` is radius, not CBSA (→ `f_m`). Advertiser-ranked. Don't republish posting text. |
| BLS LAUS | Labor force per CBSA (view-1 denominator) | Monthly, ~2-month lag. Keyless 25/day → needs `BLS_API_KEY`. |
| NIOSH NIOCCS | Interim occupation (SOC) coding | Keyless. Title-only, ~21% uncoded. Meant as validator, used as interim coder. |
| Census TIGERweb | MSA + state polygons (server-simplified) | Esri/RFC-7946 winding → must rewind for d3. |
| CareerOneStop Jobs API | (intended fuller text) — **not accessible** | Self-serve token is 401 on `jobsearch`; gated. Points to NLx. |
| NLx Research Hub | Intended real text source for skills | Requires a data-request application; not available day one. |

## Status and roadmap

**`ROADMAP.md` has the ordered, one-session-each next steps** — start there.

**Working now:** national intensity map (view 1), sector deviation index (a
category-based realization of view 2), single-metro detail. Committed on `main`;
push only when the user asks (they push themselves).

**Not built yet:** LLM occupation classification + skill extraction (needs a
Groq/Gemini key and, for skills, NLx's fuller text); the validation harness
(300 hand labels, NIOCCS-agreement, a disclosed error rate — a hard requirement
in the original design); repost calibration of the national rate; three-month
trend and remote-share views; Parquet/DuckDB storage; a GitHub Action to rebuild
weekly and deploy to Pages.

**Original design intent (aspirational, for context):** five views (postings
per 1,000; occupation-mix deviation; skill premium; remote share; 3-month
change) over O*NET-SOC classifications, with an LLM-written outliers panel as
the centerpiece and a disclosed classification error rate as a release gate.
The current build reaches this via interim substitutions where free data or
keys fall short; each is labeled on the page and in the module docstrings.
