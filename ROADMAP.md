# ROADMAP

**The core project is finished and deployed.** The national intensity map, the
two-chart sector index, and the any-metro detail page are live at
https://jakebohman.github.io/job-mapping/ and refresh on their own: a daily GitHub
Action (`.github/workflows/rebuild.yml`) rebuilds the data with the API keys stored
as repo secrets, commits it, and redeploys (`.github/workflows/pages.yml`). All 387
measurable metros shade; sector coverage fills and then re-refreshes on the rolling
schedule.

What remains is a short, optional list. Read `CLAUDE.md` first (architecture,
gotchas), then a task entry here.

**Keys are secrets.** `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `BLS_API_KEY`, and (for the
future task below) `GEMINI_API_KEY` live in GitHub Actions repository secrets and
local env vars only — never in the repo. `.env` is gitignored; `.env.example` lists
the names.

---

## 1. Mobile rendering  *(the one real gap before "done, done")*
- **Goal:** the three pages render and work well on phones, not just desktop.
- **Scope:** check `index.html`, `sectors.html`, `map.html` at mobile widths (the
  in-app browser can resize to 375px). The map SVG, the controls (mode toggle +
  category `<select>`), the hover/tap affordance (touch has no hover — the tooltip
  needs a tap path), the sector bar charts, and the footer stamp all need to reflow
  without horizontal scroll. Fix with CSS (the pages already use CSS custom-property
  tokens in `fonts.css`); no pipeline changes.
- **Done when:** all three pages are usable and readable at 375px wide with no
  sideways scroll, and a metro's figures are reachable by tap on touch devices.
- **Depends on:** nothing.

## 2. Gemini AI analysis per metro  *(future / optional)*
- **Goal:** a short written analysis on each metro's detail page — e.g. "Hiring here
  runs hot for its size, led by healthcare and logistics; tech is under-indexed."
- **Scope:** feed Gemini (`GEMINI_API_KEY`, already in `.env.example`) the metro's
  **already-computed** numbers (rate, national rank, top over/under-indexed sectors
  from `outliers.json`), and have it write 1–2 sentences. Cache per metro in the
  JSON the panel emits, regenerate on the rolling schedule. **Build it on the
  computed stats, not on raw postings** — classifying raw Adzuna postings reintro-
  duces the advertiser-ranking bias the whole design avoids, which is why the old
  occupation-coding path was dropped. This replaces the current templated outlier
  sentences with prose grounded in the same honest numbers.
- **Depends on:** nothing hard.

---

## Discarded (deliberately not doing)
- **Occupation / skill SOC classification + validation harness.** Reintroduces
  Adzuna's ranking bias and needs a hand-labeled error rate; the counts-based map
  is the committed direction. The interim NIOCCS scaffold (`classify.py`,
  `metro_map.py`) was removed; recoverable from git history if ever revisited.
- **Remote-share view**, **three-month trend view**, and **Parquet/DuckDB storage.**
  Not worth the added surface; static JSON is the permanent storage choice.

## Done
- **Deployed to GitHub Pages** with a daily auto-rebuild Action (data refresh +
  redeploy, keys as secrets, caches persisted across runs).
- **National cache ages out** (`build_national._work_list`, `measured_at` +
  `REFRESH_DAYS`) so scheduled runs refresh the counts and BLS denominator instead
  of freezing them; regression-free.
- **One-command reproducible build** (`pipeline/build_all.py`).
- **387/387 measurable metros shade** — repost-calibrated (`count × f_m ×
  dedup_ratio`), gray-recovered (Central-county re-anchor + tighter radii), with the
  CT planning-region / LA parish / AK-HI naming joins and multi-state LAUS series.
- **Front-page map**: per-1,000 ↔ total toggle, category filter, robust color scale,
  per-metro "Last updated".
- **Two-chart sector deviation index** (`sectors.html`) and generic **Metro Detail**
  (`map.html`).
- **Docs**: `METHODOLOGY.md` / `methodology.html` (plain-language method, corrected
  to match the measured dedup magnitude), `README.md`, `CLAUDE.md`.
