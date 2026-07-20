# ROADMAP

Next steps for Job Maps, ordered and sized so each task fits **one working
session**. A fresh context can pick up any task cold: read `CLAUDE.md` first
(architecture, commands, gotchas), then the task entry here.

**Status:** the national map, sector index, and single-metro page work and are
committed on `main`. The national rate is now **repost-calibrated** (task 2) and
**mis-geocoded/CT metros are recovered** (task 3, see CLAUDE.md gotchas). Still
open: the site is **not deployed**, and occupation coding is the interim NIOCCS.

**Keys are secrets.** `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `BLS_API_KEY`, and
`GEMINI_API_KEY` live in GitHub Actions repository secrets and local env vars
only — never in the repo. `.env` is gitignored; `.env.example` lists names.

Each entry: **Goal · Scope · Done when · Depends on**. Order is a recommendation;
tasks 2–3 are independent quick wins and can move around 1 and 4.

---

## 1. Deploy the static site to GitHub Pages  *(ship it — do first)*
- **Goal:** the current `site/` is live at a public URL.
- **Scope:** add `.github/workflows/pages.yml` using `actions/upload-pages-artifact`
  (path: `site/`) + `actions/deploy-pages`; enable Pages in repo settings. It
  publishes the already-committed `site/data/*`, so the map works on first deploy.
- **Done when:** the Pages URL renders the map (metros shaded, hover works);
  confirm the vendored `site/vendor/d3-geo`, `site/fonts.css`, and the pages'
  `{cache:'no-store'}` data fetches all load over Pages (all same-origin — should
  just work).
- **Depends on:** nothing.

## 2. Repost-calibrate the national rate  ✅ DONE
- **Goal:** absolute rates read realistically instead of inflated by reposts.
- **Scope:** in `pipeline/build_national.py` `_measure`, dedupe the 50 postings
  already fetched (reuse `ingest.dedupe_semantic` + `ingest.cap_per_employer`)
  to a per-metro dedup ratio and fold it into `effective`
  (`count × f_m × dedup`). Update the `method`/`caveats` strings; rebuild
  `national.json` (`python pipeline/build_national.py` — counts are cached, so
  this is cheap).
- **Done when:** shaded rates land roughly 15–40/1,000, the color domain looks
  sane, and the map still renders.
- **Depends on:** nothing.

## 3. Recover mis-geocoded metros  ✅ DONE
- **Goal:** metros graying because their name is ambiguous on Adzuna
  (e.g. "Albany, OR" → Albany NY, so `f_m ≈ 0`) show correctly.
- **Scope:** detect high-`count`/near-zero-`f_m` metros and retry `ingest._get`
  with a disambiguating `where` — append a central county name, or project the
  CBSA centroid from `site/data/us_metros.geojson` and use Adzuna's lat/long +
  small distance. Reuse `geo`.
- **Done when:** the gray count drops; spot-check that Albany OR and a few other
  ambiguous metros now shade.
- **Depends on:** nothing (same `_measure` path as task 2 — consider doing them
  together).

## 4. Weekly auto-rebuild GitHub Action  *(completes "ship it live")*
- **Goal:** data refreshes weekly and redeploys automatically.
- **Scope:** `.github/workflows/rebuild.yml` on a weekly cron (+ `workflow_dispatch`):
  run `pipeline/build_national.py` and `pipeline/panel.py` with the repo secrets,
  commit the regenerated `site/data`, and trigger the Pages deploy. Persist
  `site/data/_lf_cache.json` across runs via `actions/cache` (labor force is
  stable — saves BLS quota); let Adzuna counts refresh fresh each week. If the
  run hits Adzuna's daily cap partway, commit partial data (the rest grays) and
  let the next run continue.
- **Done when:** a manual `workflow_dispatch` run updates `site/data` and the
  live map reflects the change.
- **Depends on:** task 1; best after 2–3 so it ships calibrated data.

## 5. LLM occupation classification (Gemini)  *(key available)*
- **Goal:** replace NIOCCS's title-only coding with title + 500-char description
  → SOC major (+ detailed) + extracted skills.
- **Scope:** add a Gemini backend behind a provider-neutral function mirroring
  `classify.code_title`; reuse `classify_sample`'s title cache and
  `SOC_MAJOR_TITLES`. Make the LLM the primary coder and keep NIOCCS as the
  independent validator. Reads `GEMINI_API_KEY` from the env.
- **Done when:** a Columbus sample codes with skills; LLM↔NIOCCS agreement is
  reported; the uncoded rate drops well below NIOCCS's ~21%.
- **Depends on:** nothing hard; pairs with task 6.

## 6. Validation harness + disclosed error rate  *(design hard-requirement)*
- **Goal:** a measured classification accuracy, shown on the site.
- **Scope:** a small local CLI to hand-label ~300 postings (stratified by SOC
  major and metro-size tercile); compute major-group accuracy with a Wilson 95%
  CI and LLM↔NIOCCS agreement; render the number in the page footer; keep a
  ~50-item golden set for regression. Reuse `classify.py`.
- **Done when:** the labeling flow runs, the accuracy + CI compute, and the
  figure appears on the site.
- **Depends on:** task 5.

## 7. Scale the sector index + map↔sector integration
- **Goal:** more metros in the sector index, and clicking a metro on the US map
  shows its sector deviations.
- **Scope:** extend `pipeline/panel.py` to ~40–50 metros (write per-metro sector
  data); in `site/index.html`, on metro click, show that metro's over/under
  sectors from the panel output, cross-linked with `sectors.html`. Budget:
  ~31 Adzuna category-count calls per metro (resumable via the mix cache).
- **Done when:** clicking a metro opens its sector panel; the index covers the
  expanded set.
- **Depends on:** task 4 for budget/cadence; benefits from task 5 if switching
  to SOC occupations instead of Adzuna categories.

## 8. Later views + storage  *(park until earlier work lands / time passes)*
- **Remote-share view** — an LLM or keyword remote flag per posting.
- **Three-month trend** — needs ~13 weekly snapshots from task 4, so gated on
  time.
- **Parquet/DuckDB storage** — only if data volume outgrows the current static
  JSON.
