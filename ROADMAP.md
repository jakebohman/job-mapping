# ROADMAP

Next steps for Job Maps, ordered and sized so each task fits **one working
session**. A fresh context can pick up any task cold: read `CLAUDE.md` first
(architecture, commands, gotchas), then the task entry here.

**Status:** the national map (repost-calibrated, gray-recovered — **387/387
measurable metros shaded**, i.e. every non-PR metro), the two-chart sector index,
and the generic any-metro Metro Detail page all work. The front-page map has a
**per-capita↔total toggle**, a **category filter** (shade by any Adzuna category
per 1,000 workers), a **fixed color scale**, and per-metro **"Last updated"**.
Sector data covers **147/387 shaded metros** and fills as `panel.py` runs. The
**one-command reproducible build (`pipeline/build_all.py`) is done** (task 1).
Still open: the site is **not deployed** (task 2), and the occupation/skills path
is parked.

**Keys are secrets.** `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `BLS_API_KEY`, and
`GEMINI_API_KEY` live in GitHub Actions repository secrets and local env vars
only — never in the repo. `.env` is gitignored; `.env.example` lists names.

Each entry: **Goal · Scope · Done when · Depends on**.

---

## 1. One-command reproducible build — `pipeline/build_all.py`  *(✅ DONE)*
- Shipped: checks the three required keys, runs `build_geometry` (if absent) →
  `build_national` (resumable) → `panel.py` looped until every shaded metro has
  sector data or the Adzuna cap stops it, then prints a coverage summary +
  "re-run to continue". `--loop` (sleep + retry across days) and `--serve` flags.
  README's "Run it" now leads with it. See the Done section for the shipped notes.

## 2. Deploy the static site to GitHub Pages  *(ship it — now the priority)*
- **Goal:** the current `site/` is live at a public URL.
- **Scope:** add `.github/workflows/pages.yml` using `actions/upload-pages-artifact`
  (path: `site/`) + `actions/deploy-pages`; enable Pages in repo settings. It
  publishes the already-committed `site/data/*`, so the map works on first deploy.
- **Done when:** the Pages URL renders the map (metros shaded, hover works,
  category filter works); the vendored `site/vendor/d3-geo`, `site/fonts.css`, and
  the `{cache:'no-store'}` data fetches all load over Pages (all same-origin).
- **Depends on:** nothing.

## 3. Weekly auto-rebuild GitHub Action  *(completes "ship it live"; needs task 1 & 2)*
- **Goal:** data refreshes on a schedule and redeploys automatically — this is
  also the **scheduler** for the rolling sector fill (see Done §e).
- **Scope:** `.github/workflows/rebuild.yml` on a cron (+ `workflow_dispatch`) that
  runs the orchestrator from task 1 (or `build_national.py` + `panel.py` directly)
  with repo secrets, commits the regenerated `site/data`, and triggers the Pages
  deploy. Persist `site/data/_*_cache.json` across runs via `actions/cache`
  (labor force especially — stable, saves BLS quota; the mix cache lets the rolling
  fill advance run-over-run instead of restarting). If a run hits Adzuna's daily
  cap, commit partial data and let the next run continue.
- **Done when:** a manual `workflow_dispatch` run updates `site/data` and the live
  map reflects the change; consecutive scheduled runs visibly grow sector coverage.
- **Depends on:** tasks 1 and 2.

## 4. Occupations & skills (Gemini) + validation harness  *(PARKED — deprioritized)*
- **Context:** the original-design centerpiece, but the user redirected away from
  it toward the counts-based map (category filter, gray recovery). The counts path
  is bias-immune; occupation classification reintroduces Adzuna's advertiser-ranking
  bias and needs a hand-labeled error rate. Revisit only if there's appetite.
- **Scope (if resumed):** a Gemini coder (title + 500-char description → SOC
  major/detailed + skills) with the NIOSH NIOCCS autocoder as an independent
  validator; then a local CLI to hand-label ~300 postings and report a
  Wilson-95%-CI major-group accuracy + LLM↔NIOCCS agreement on the site footer.
  `GEMINI_API_KEY` is available. The old interim scaffold (`classify.py` NIOCCS
  coder + `metro_map.py` single-metro occupation build) was **removed** once the
  project committed to the counts map — recover it from git history (last present
  at commit `8977548`) as a starting point.
- **Depends on:** nothing hard; the error rate is human-gated (someone labels 300).

## 5. Later views + storage  *(park until earlier work lands / time passes)*
- **Remote-share view** — a counts-based "remote postings ÷ total" per metro if
  Adzuna exposes a usable remote signal (verify first); fits the map's category
  filter naturally.
- **Three-month trend** — needs ~13 weekly snapshots from task 3, so gated on time.
- **Parquet/DuckDB storage** — only if data volume outgrows the current static JSON.

---

## Done (this and prior sessions)
- **Every measurable metro now shades (387/387).** Un-froze the last 18 grays: the
  gray-recovery worked but `build_national` never re-measured metros already carrying
  a `dedup_ratio`, so bleed cases sat frozen — clearing their cache entries and
  re-measuring shaded ~11. Plus geocode fixes: strip New England "… Town"
  (`principal_place`), a "Saint"↔"St." county alias (`_saint_alias`, recovered
  Slidell), `_measure` now recovers a *failed* geocode via the county anchor, an
  added 10 km recovery radius, and **CT town-level matching** (`CT_TOWN_CBSA`) for
  Waterbury, whose Naugatuck Valley region spans three old counties.
- **Map polish** — per-capita↔total toggle, per-metro "Last updated", one-sentence
  method copy, higher map/background contrast, roman (not italic) heading emphasis.
- **One-command reproducible build** (`pipeline/build_all.py`) — stdlib
  orchestrator, subprocesses the existing resumable/self-caching scripts. Verifies
  `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`/`BLS_API_KEY` (names any missing), runs
  `build_geometry` only if its outputs are absent, `build_national` once
  (resumable), then loops `panel.py` (PER_RUN stalest metros/pass) until sector
  coverage == shaded universe or a pass stalls (non-zero exit or no new metros =
  Adzuna cap) → prints `X/Y` + "re-run to continue". `--loop` retries across days;
  `--serve` launches `http.server` in `site/` when done. Selftest covers the
  key-check + coverage logic (no network).
- **Repost calibration** — `effective = count × f_m × dedup_ratio`; the small-cell
  gray-out also floors `f_m ≥ 0.10` (see CLAUDE.md).
- **Gray-metro recovery** — `build_national._measure` retries a would-gray metro
  with a Central-county re-anchor (ambiguous geocode) **and/or** a tighter radius
  (25/15/10 km, sheds a big neighbor's bleed), keeping the best f_m. Recovered
  308→369 of 387 shaded. Also: CT planning-region join, LA parish / AK-HI
  non-contiguous naming, multi-state LAUS series, Puerto Rico excluded.
- **Two-chart sector index** (`sectors.html`) — over- and under-represented charts,
  `?metro=` spotlight.
- **Metro Detail** (`map.html`) — generic, selectable to any metro (`?metro=<cbsa>`
  + picker), from existing data; the US map clicks through to it.
- **Front-page category filter + color scale** (`site/index.html`) — shade by any
  Adzuna category per 1,000 (`total_rate × category_share`, from `panel.py`'s
  `category_shares`); robust color domain + retuned palette.
- **Rolling sector collection** (`panel.py` `stale_metros`/`PER_RUN`/`fetched_at`) —
  covers all shaded metros over successive runs (147/387 so far).
- **`methodology.html`** — a static, on-site plain-language method summary
  (mirrors `METHODOLOGY.md`), linked from the index and `sectors` footers.
- **Copy + layout polish** — public-facing text de-em-dashed (`/humanizer`);
  unified footer stamp across the three data pages (`Job postings from X of Y ·
  Sector data from Z of Y · Updated …`), which is why `sectors.html` now also
  fetches `national.json`; index legend/controls tidy-up + default sector "All job
  sectors"; sectors chart adds a 4× tick, parallel over/under blurbs, `log₂`
  method line; Metro Detail moves the sector breakdown to the left column.
- **Pipeline field cleanup** — dropped unused display fields the pages stopped
  reading (`build_national`: `method`/`metric`/`caveats`/`domain`/`rate_range`
  + the now-dead `_percentile`; `panel`: `method`/`basis`). Pages carry static
  copy instead. Selftests pass; committed JSON keeps the old fields until rebuilt.
- Docs: `METHODOLOGY.md` (plain-language method), `CLAUDE.md` gotchas.
