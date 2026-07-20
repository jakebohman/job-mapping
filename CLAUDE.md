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
| `index.html` (landing) | `build_national.py` | US choropleth: postings per 1,000 workers across ~390 metros. **Click a metro → `map.html?metro=<cbsa>`** (Metro Detail). Paths carry `data-cbsa`. |
| `map.html` (Metro Detail) | `build_national.py` + `panel.py` | **Any** metro (a `<select>` picker + `?metro=<cbsa>`): rate + rank, CBSA shape (from `us_metros.geojson`), and its over/under-indexed sectors (`outliers.json` `by_metro`). Purely client-side over existing data — no per-metro build. |
| `sectors.html` | `panel.py` | **Two** charts — the sharpest over- and under-represented sector×metro cells (`over_index`/`under_index`); `?metro=<cbsa>` spotlights one metro. |

`panel.py` collects sector data **rolling**: `stale_metros` picks the `PER_RUN`
(default 40, override via argv) stalest metros across all *shaded* metros
(`shaded_universe`, from `national.json` — so build `build_national.py` first),
stamps each with `fetched_at`, and the report accumulates every metro collected
so far. Run it repeatedly (e.g. a daily cron) to fill the country within the
Adzuna budget. `metro_map.py` (the old Columbus-only occupation-mix detail) is
now unused by the site — kept for the eventual LLM occupation path.

## Commands

Run everything from the repo root. There is no framework/lint/CI yet.

```sh
pip install -r requirements.txt          # one dependency: requests
# Keys: put them in a gitignored .env at the repo root (copy .env.example) — it's
# auto-loaded by pipeline/geo.py, so builds run without passing keys. Or export
# them. Needed: ADZUNA_APP_ID, ADZUNA_APP_KEY (all builds), BLS_API_KEY (national
# map), GEMINI_API_KEY (ROADMAP task 5). This repo already has a local .env.

# Build the site data (writes JSON/GeoJSON into site/data/). Order matters:
# geometry, then national (panel reads national.json to pick which metros to fill).
python pipeline/build_geometry.py    # one-time: metro/state shapes + vendored d3-geo (no key)
python pipeline/build_national.py    # national map data (~387 Adzuna calls; resumable, gray-recovery)
python pipeline/panel.py [N]         # sector data — rolling: refreshes the N stalest shaded metros
                                     #   (default PER_RUN=40). Re-run until coverage is full.
python pipeline/build_crosswalk.py   # rebuild pipeline/cbsa_counties.csv from Census (rare)
# python pipeline/metro_map.py [CBSA]  # legacy Columbus occupation build — UNUSED by the site now

# ROADMAP task 1 (the priority) is a one-command orchestrator, pipeline/build_all.py,
# that runs geometry -> national -> panel(loop) with a key check — the intended
# "clone, set .env, run one thing, watch the map fill" path. Not written yet.

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
- **Small-cell threshold: n ≥ 50 effective postings AND f_m ≥ 0.10.** Metros
  with fewer than 50 effective in-CBSA postings, no labor force, or an in-CBSA
  sample fraction below 10% gray out — disclosed on the page. (Poisson CV ≤ 15%.)
  The f_m floor matters because `effective = count × f_m × dedup_ratio` and a
  huge radius `count` can clear 50 on a ~1-posting f_m (Columbus IN read a rate
  off a single in-sample posting until this floor was added); below 10% the
  measurement is radius bleed, not the metro.
- **Interim substitutions**, each with an isolated swap-in point:
  - Occupation coding uses the free, keyless **NIOSH NIOCCS autocoder**
    (`classify.py`) in place of an LLM (no LLM key yet). NIOCCS leaves ~21%
    uncoded and is title-only; an LLM reading the description will replace it.
  - Outlier sentences are **templated** from the numbers, not LLM-written.
  - Storage is **JSON**, not the Parquet/DuckDB the long-term design calls for.
- **The national rate is repost-calibrated, per metro.** Adzuna is
  repost-saturated (~58% of a raw sample were near-duplicates). The national
  `count` field can't itself be de-duped, so `build_national._measure` derives a
  per-metro `dedup_ratio` from the 50 sampled postings (`ingest.dedupe_semantic`
  over the in-CBSA subset) and folds it into `effective = count × f_m ×
  dedup_ratio`. It's a *lower* bound on distinct demand (dedup can merge genuine
  multi-site openings), and disclosed as such.

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
  These self-gray via `f_m ≈ 0`. `build_national._measure` retries such metros
  (high `count`, `f_m < 0.05`, and the sample's modal state ≠ the CBSA's) with a
  `where` anchored on a Central county ("Jackson County, Oregon") and keeps it
  only if f_m improves — this recovers e.g. Medford OR. Same-state radius bleed
  (Columbus IN → Indianapolis) fails the wrong-state test and correctly stays gray.
- **Connecticut uses planning regions; Adzuna uses old counties.** The OMB 2023
  crosswalk keys the 5 CT CBSAs on "…Planning Region" names, but Adzuna reports
  old CT county names ("Fairfield County", …), so every CT posting failed the
  county→CBSA join and all CT metros read f_m=0 (all gray). `geo.CT_COUNTY_CBSA`
  aliases the old counties to their dominant CBSA. County granularity: old New
  Haven County splits between the New Haven and Waterbury CBSAs, so it maps to
  New Haven and Waterbury stays gray until a town-level split is worth it.
- **Multi-state metros' LAUS series lives under ONE state.** BLS files a
  multi-state MSA's total labor-force series under the principal (first-in-title)
  state, so `geo` derives the series' state prefix from the title via
  `STATE_ABBR_FIPS` ("Chicago-…, IL-IN" → IL), not from an arbitrary constituent
  county — otherwise the series 404s and the metro grays for want of a
  denominator (this had silently grayed DC, Chicago, Philadelphia, Boston,
  Portland). A few metros BLS files under the *second* state (Davenport IA-IL →
  IL); `geo` keeps `laus_lf_series_alts` and `bls.labor_force_batch` retries them.
- **Adzuna's county-equivalent naming is inconsistent.** Louisiana reports
  *parishes*, Alaska *boroughs/census areas/municipalities*, and non-contiguous
  places (HI, AK) drop the suffix entirely ("Honolulu" not "Honolulu County").
  `geo.county_of` matches `COUNTY_SUFFIXES` and falls back to the `area[2]` slot;
  `geo._bare_county` adds suffix-stripped aliases to the reverse index (the plain
  "County" strip is limited to Hawaii to avoid the VA "Richmond city" vs
  "Richmond County" collision). Also "Urban Honolulu" won't geocode — stripped to
  "Honolulu" in `principal_place`. These recovered New Orleans, Honolulu,
  Anchorage, etc. Puerto Rico is excluded entirely
  (`build_national.EXCLUDED_STATES = {"72"}`): Adzuna returns unreliable (often
  Florida) locations for PR searches, so those 6 metros aren't measurable.
- **The map's color scale is linear on a robust domain, recomputed per metric.**
  `index.html`'s `computeDomain` sets `[min, 95th-pct]` for the *currently selected
  metric* and shades linearly (lowest rate = lightest; the handful above P95 clamp
  darkest, legend shows a "+"). Palette: pale **blue** low end, kept distinct from
  the `--nodata` **gray** (a low-rate metro must not read as no-data). `rate_range`
  and the pipeline's `domain` field are no longer used by the page.
- **The front-page map has a category filter.** A `<select>` re-shades by any
  Adzuna category's jobs-per-1,000 = `metro rate × category share`, where the
  shares come from `outliers.json`'s `category_shares` (`panel.py`). Metros without
  sector data yet render gray for a category. `metric===null` is the "Total" mode.

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

**Working now:** national intensity map (369/387 shaded, calibrated + gray-
recovered) **with a category filter**; two-chart sector deviation index; generic
any-metro Metro Detail (the map clicks through to it). Sector data covers 147/308
shaded metros and fills as `panel.py` runs. Push only when the user asks (they
push themselves). **At last handover the Phase C changes were uncommitted** —
check `git status` / `ROADMAP.md`'s uncommitted note before assuming they're in.

**The immediate priority is ROADMAP task 1:** `pipeline/build_all.py`, a
one-command orchestrator so anyone can clone, set `.env`, run it, and watch the
map fill (reproducibility). Not written yet.

**Not built yet:** the reproducible build (task 1); GitHub Pages deploy + a
scheduled rebuild Action; LLM occupation/skill classification + the validation
harness (parked — the user redirected to the counts-based map); three-month trend
and remote-share views; Parquet/DuckDB storage.

**Original design intent (aspirational, for context):** five views (postings
per 1,000; occupation-mix deviation; skill premium; remote share; 3-month
change) over O*NET-SOC classifications, with an LLM-written outliers panel as
the centerpiece and a disclosed classification error rate as a release gate.
The current build reaches this via interim substitutions where free data or
keys fall short; each is labeled on the page and in the module docstrings.
