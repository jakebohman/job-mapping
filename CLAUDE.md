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
| `sectors.html` | `panel.py` (also `fetch()`es `national.json` at runtime for the footer coverage counts) | **Two** charts — the sharpest over- and under-represented sector×metro cells (`over_index`/`under_index`); `?metro=<cbsa>` spotlights one metro. |
| `methodology.html` | — (static, no build script) | Plain-language method summary; mirrors `METHODOLOGY.md`. Linked from the index and `sectors` footers ("See our full methodology →"). |

`panel.py` collects sector data **rolling**: `stale_metros` picks the `PER_RUN`
(default 40, override via argv) stalest metros across all *shaded* metros
(`shaded_universe`, from `national.json` — so build `build_national.py` first),
stamps each with `fetched_at`, and the report accumulates every metro collected
so far. Run it repeatedly (e.g. a daily cron) to fill the country within the
Adzuna budget.

## Commands

Run everything from the repo root. There is no framework/lint/CI yet.

```sh
pip install -r requirements.txt          # one dependency: requests
# Keys: put them in a gitignored .env at the repo root (copy .env.example) — it's
# auto-loaded by pipeline/geo.py, so builds run without passing keys. Or export
# them. Needed: ADZUNA_APP_ID, ADZUNA_APP_KEY (all builds), BLS_API_KEY (national
# map), GEMINI_API_KEY (ROADMAP task 5). This repo already has a local .env.

# One command (the intended path): checks keys, then geometry -> national ->
# panel(loop), printing coverage as it fills. Resumable; --loop / --serve flags.
python pipeline/build_all.py

# Or the same stages by hand (build_all just subprocesses these). Order matters:
# geometry, then national (panel reads national.json to pick which metros to fill).
python pipeline/build_geometry.py    # one-time: metro/state shapes + vendored d3-geo (no key)
python pipeline/build_national.py    # national map data (~387 Adzuna calls; resumable, gray-recovery)
python pipeline/panel.py [N]         # sector data — rolling: refreshes the N stalest shaded metros
                                     #   (default PER_RUN=40). Re-run until coverage is full.
python pipeline/build_crosswalk.py   # rebuild pipeline/cbsa_counties.csv from Census (rare)

# Serve locally:
cd site && python -m http.server 8000     # open http://localhost:8000

# Tests: every module self-tests with no network and no keys. This is the whole
# test suite — run one module's checks with:
python pipeline/geo.py --selftest         # also: ingest, bls, panel, build_national, build_all
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
(Fraunces + IBM Plex embedded woff2 — no CDN) also holds the **shared** CSS
custom-property tokens (light/dark); each page's inline `<style>` — loaded after
`fonts.css`, so it wins — adds only its page-specific tokens (`--over`/`--under`,
`--base`/`--metro-line`/`--nodata`). `d3-geo` is vendored in `site/vendor/` (not a
CDN). Pages `fetch(..., {cache:'no-store'})` so a data rebuild is never served stale.

**Prose lives in the HTML, not the JSON.** The builders used to emit display
strings (`build_national`: `method`/`metric`/`caveats`/`domain`/`rate_range`;
`panel`: `method`/`basis`) that the pages no longer read — they were dropped from
the pipeline and the pages now carry their own static method/footer copy. (The
*committed* `site/data/*.json` still contains these fields until the next rebuild;
they're ignored.) All public-facing copy is also intentionally em-dash-free (a
`/humanizer` pass) — keep it that way in the HTML. All three data pages share one
**unified footer stamp**: `Job postings from <covered> of <total> metros · Sector
data from <sampled> of <covered> metros · Updated <date>` — which is why
`sectors.html` now also fetches `national.json`.

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
  - Outlier sentences are **templated** from the numbers, not LLM-written.
  - Storage is **JSON**, not the Parquet/DuckDB the long-term design calls for.
  - Occupation coding (an LLM behind a NIOCCS validator) is **not built** — the
    interim NIOCCS scaffold (`classify.py`, `metro_map.py`) was removed when the
    project committed to the counts-based map; recover it from git if ROADMAP
    task 4 resumes.
- **The national rate is repost-calibrated, per metro.** Adzuna is
  repost-saturated (~58% of a raw sample were near-duplicates). The national
  `count` field can't itself be de-duped, so `build_national._measure` derives a
  per-metro `dedup_ratio` from the 50 sampled postings (`ingest.dedupe_semantic`
  over the in-CBSA subset) and folds it into `effective = count × f_m ×
  dedup_ratio`. It's a *lower* bound on distinct demand (dedup can merge genuine
  multi-site openings), and disclosed as such.
  - **Known limitation — the correction under-fires for small metros.** The ~58%
    figure is from a large raw sample; the *applied* per-metro `dedup_ratio`
    averages ~0.82 across shaded metros (only ~18% removed) and rises toward 1.0
    as f_m falls, because the in-CBSA subset then holds too few postings for two
    to collide on title+employer. So high-rate small metros (The Villages,
    Lebanon PA) are effectively un-deduplicated and read hotter than they are,
    but the effect is bounded and small: imputing the well-sampled median dedup
    (~0.82) to every metro moves the top rates only ~15-20% and leaves the ranking
    near-identical (top-20 overlap 16/20, The Villages stays #1). The ranked map
    is unaffected; only the extreme absolute values run modestly high. A future
    fix would floor `dedup_ratio` at the national median for thin samples, or
    dedup over a larger sample (needs a keyworded/paged Adzuna pull). Docs
    (`METHODOLOGY.md`, `methodology.html`) now disclose this rather than claim
    "roughly half are removed."

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
  aliases the old counties to their dominant CBSA. **Waterbury (47930) is the
  Naugatuck Valley Planning Region, carved from THREE old counties** (New Haven,
  Hartford, Litchfield), so no county alias can isolate it — `geo.CT_TOWN_CBSA`
  matches its 19 member towns by name (Adzuna reports the town in `area[3]`),
  checked ahead of the county fallback in `cbsa_of`. Villages Adzuna names instead
  of their parent town just fall through (slight undercount, never misattribution).
- **Adzuna spells "Saint" where the OMB crosswalk abbreviates "St.".** A posting's
  county then never joins — "Saint Tammany Parish" (Adzuna) vs "St. Tammany Parish"
  (crosswalk) grayed out all of Slidell LA, whose only county is that parish.
  `geo._saint_alias` indexes both spellings.
- **New England "… Town" place names don't geocode on Adzuna.** "Amherst Town, MA"
  returns nothing; `principal_place` strips the trailing " Town" (like the "Urban
  Honolulu" case) so Amherst/Barnstable resolve.
- **`build_national` skips any cached metro that already has `dedup_ratio`.** That
  makes re-runs cheap, but means an improvement to `_measure`'s gray-recovery does
  NOT reach already-cached metros — they stay frozen at their old measurement. To
  re-measure specific metros after improving recovery, clear their entries from
  `site/data/_national_cache.json` first (this is what un-froze the last 18 grays).
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
  the `--nodata` **gray** (a low-rate metro must not read as no-data).
- **The front-page map has a category filter.** A `<select>` re-shades by any
  Adzuna category's jobs-per-1,000 = `metro rate × category share`, where the
  shares come from `outliers.json`'s `category_shares` (`panel.py`). Metros without
  sector data yet render gray for a category. `metric===null` is the "Total" mode.

## Data sources and their limits

| Source | Used for | Key limits |
|---|---|---|
| Adzuna API (free) | Posting counts + category counts; sampled details | ~25/min + daily cap. Descriptions hard-truncated at 500 chars. `where` is radius, not CBSA (→ `f_m`). Advertiser-ranked. Don't republish posting text. |
| BLS LAUS | Labor force per CBSA (view-1 denominator) | Monthly, ~2-month lag. Keyless 25/day → needs `BLS_API_KEY`. |
| Census TIGERweb | MSA + state polygons (server-simplified) | Esri/RFC-7946 winding → must rewind for d3. |
| CareerOneStop Jobs API | (intended fuller text) — **not accessible** | Self-serve token is 401 on `jobsearch`; gated. Points to NLx. |
| NLx Research Hub | Intended real text source for skills | Requires a data-request application; not available day one. |

## Status and roadmap

**`ROADMAP.md` has the ordered, one-session-each next steps** — start there.

**Working now:** national intensity map (**387/387 measurable metros shaded** —
every non-PR metro; calibrated + gray-recovered) **with a category filter**;
two-chart sector deviation index; generic any-metro Metro Detail (the map clicks
through to it). Sector data covers 147/387 shaded metros and fills as `panel.py`
runs. Push only when the user asks (they push themselves).

**Reproducible build (was ROADMAP task 1) is done:** `pipeline/build_all.py` is
the one-command orchestrator — checks keys, then geometry → national →
panel(loop), printing coverage so you watch the map fill. Resumable; `--loop`
(retry across days) and `--serve` flags.

**Not built yet:** GitHub Pages deploy + a scheduled rebuild Action (ROADMAP
tasks 2–3); LLM occupation/skill classification + the validation harness (parked —
the user redirected to the counts-based map); three-month trend and remote-share
views; Parquet/DuckDB storage.

**Original design intent (aspirational, for context):** five views (postings
per 1,000; occupation-mix deviation; skill premium; remote share; 3-month
change) over O*NET-SOC classifications, with an LLM-written outliers panel as
the centerpiece and a disclosed classification error rate as a release gate.
The current build reaches this via interim substitutions where free data or
keys fall short; each is labeled on the page and in the module docstrings.
