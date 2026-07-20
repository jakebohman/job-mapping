# ROADMAP

Next steps for Job Maps, ordered and sized so each task fits **one working
session**. A fresh context can pick up any task cold: read `CLAUDE.md` first
(architecture, commands, gotchas), then the task entry here.

**Status:** the national map (repost-calibrated, gray-recovered — **369/387
metros shaded**), the two-chart sector index, and the generic any-metro Metro
Detail page all work. The front-page map now has a **category filter** (shade by
any Adzuna category per 1,000 workers) and a **fixed color scale**. Sector data
covers **147/308 shaded metros** and fills as `panel.py` runs. Still open: there
is **no one-command reproducible build** (task 1 — the current priority), the
site is **not deployed**, and the occupation/skills path is parked.

> **⚠ Uncommitted at handover:** the Phase C changes — category filter + color
> scale (`site/index.html`), `category_shares` (`pipeline/panel.py`), and the
> gray-recovery + recovery-unify fix (`pipeline/build_national.py`), plus the
> regenerated `site/data/national.json` (369 shaded) and `outliers.json` — are in
> the working tree, **not yet committed**. Selftests pass. Commit these first.

**Keys are secrets.** `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `BLS_API_KEY`, and
`GEMINI_API_KEY` live in GitHub Actions repository secrets and local env vars
only — never in the repo. `.env` is gitignored; `.env.example` lists names.

Each entry: **Goal · Scope · Done when · Depends on**.

---

## 1. One-command reproducible build — `pipeline/build_all.py`  *(THE priority)*
- **Goal:** anyone can **clone the repo, put keys in `.env`, run one command, and
  watch the map fill with fresh data.** Reproducibility is the whole point.
- **Scope:** a stdlib Python orchestrator (`pipeline/build_all.py`; cross-platform,
  the repo runs on Windows) that:
  1. verifies the required keys are set (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`,
     `BLS_API_KEY`) and exits with a clear message naming any missing one;
  2. runs `build_geometry.py` if the geometry outputs are absent (one-time, keyless);
  3. runs `build_national.py` (resumable) — the national map;
  4. runs `panel.py` repeatedly until every shaded metro has sector data, **or**
     until the Adzuna daily cap / a network error stops it (`stale_metros` rolls
     coverage forward each pass);
  5. prints a coverage summary (`X/Y shaded`, `N/M metros with sector data`) and,
     if incomplete, a "re-run to continue" line.
  Subprocess the existing scripts (each already caches to `site/data/_*_cache.json`
  and resumes, so the orchestrator stays thin and re-runs are cheap/idempotent).
  Optional: a `--loop` flag (sleep + retry across days) for unattended runs, and a
  `--serve` convenience that launches `python -m http.server` in `site/` when done.
- **Reality to encode in output + docs:** on the Adzuna free tier a full populate
  spans **a few days** (national ~387 calls; sector ~308 metros × 31 ≈ 9,500
  calls). One run does a budget's worth and stops gracefully; the committed
  `site/data/*.json` renders immediately in the meantime. Caches are gitignored,
  so a fresh clone re-fetches from scratch (that is what makes the data *fresh*).
- **Done when:** from a fresh clone with keys, running the script (re-run until it
  reports complete) yields `site/` rendering the fully-shaded map + sector/category
  data; a second run with warm caches is a fast no-op refresh. Update `README.md`
  to make this the primary "Run it" path.
- **Depends on:** nothing. (Commit the uncommitted Phase C changes first.)

## 2. Deploy the static site to GitHub Pages  *(ship it)*
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
- **Scope (if resumed):** a Gemini coder behind `classify.code_title`'s swap point
  (title + 500-char description → SOC major/detailed + skills), NIOCCS kept as the
  independent validator; then a local CLI to hand-label ~300 postings and report a
  Wilson-95%-CI major-group accuracy + LLM↔NIOCCS agreement on the site footer.
  `GEMINI_API_KEY` is available. `pipeline/metro_map.py` (the old Columbus-only
  occupation build, now unused by the site) is the starting point.
- **Depends on:** nothing hard; the error rate is human-gated (someone labels 300).

## 5. Later views + storage  *(park until earlier work lands / time passes)*
- **Remote-share view** — a counts-based "remote postings ÷ total" per metro if
  Adzuna exposes a usable remote signal (verify first); fits the map's category
  filter naturally.
- **Three-month trend** — needs ~13 weekly snapshots from task 3, so gated on time.
- **Parquet/DuckDB storage** — only if data volume outgrows the current static JSON.

---

## Done (this and prior sessions)
- **Repost calibration** — `effective = count × f_m × dedup_ratio`; the small-cell
  gray-out also floors `f_m ≥ 0.10` (see CLAUDE.md).
- **Gray-metro recovery** — `build_national._measure` retries a would-gray metro
  with a Central-county re-anchor (ambiguous geocode) **and/or** a tighter radius
  (25/15 km, sheds a big neighbor's bleed), keeping the best f_m. Recovered
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
  covers all shaded metros over successive runs (147/308 so far).
- Docs: `METHODOLOGY.md` (plain-language method), `CLAUDE.md` gotchas.
