# Metro Labor Market Map

Interactive choropleth analysis of US metro (CBSA) labor demand, built from
job postings classified into O*NET occupations and skills by an LLM.
The product is insight, not listings: every view is a rate, a share, or a
deviation, and there is deliberately no path from the map to a job posting.

## Goals

- Show where labor demand deviates from expectation across ~387 metro CBSAs.
- Five views: demand rate, occupation-mix deviation, skill premium, remote
  share, three-month change.
- An outliers panel that does the looking for the user: rank metro×occupation
  cells by deviation from expectation, have an LLM write one sentence on each
  of the top ~10. This panel is the point of the project; the map is context.
- A disclosed, measured classification error rate. Not optional.
- $0 infrastructure: GitHub Actions (schedule), GitHub Pages (hosting),
  free API tiers (data + LLM), static frontend.

## Non-goals

- Not a job board. No apply links, no redirect URLs in published output, no
  posting text republished anywhere.
- No worker-side geography (where remote workers live — we only see where
  employers post).
- No wage estimation from posting text, no forecasting, no sub-metro
  geography, no real-time freshness (weekly cadence is the product).
- No detailed-occupation map views until measured accuracy at that level
  justifies them (see Validation).

## Data sources and their known limits

| Source | Used for | Known limits |
|---|---|---|
| Adzuna API (free tier) | Posting **counts** per metro/filter (views 1, 4-approx, 5); sampled posting details | ~250 calls/day / 2,500/month (verify at signup — limits are per-account and change). Descriptions truncated (~500 chars). Aggregator coverage bias (scrapes boards; direct-employer postings underrepresented). Location strings need geocoding to CBSA. ToS: do not store/republish posting content. |
| CareerOneStop API (DOL, free w/ registration) | Fuller posting text for the classification sample; second-source sanity check on counts | Backed by NLx (state job banks + direct employers) — different coverage bias than Adzuna. Rate limits generous but undocumented; verify in Phase 0. |
| BLS LAUS | Labor force per CBSA (view 1 denominator) | Monthly, ~2-month lag, model-based for small areas. Use not-seasonally-adjusted metro series; pin one vintage per release. |
| BLS OEWS | Metro occupation employment shares (validation baseline; view 2 context) | Annual (May reference), 6-digit SOC by MSA. Employment mix ≠ posting mix — postings overweight high-churn occupations. It's a sanity check, not ground truth. |
| O*NET database | O*NET-SOC 2019 taxonomy; technology-skills list seeds the skill vocabulary | Taxonomy vintage must match the SOC vintage used in OEWS joins. |
| Census cartographic boundary files (`cb_*_us_cbsa_5m`) | CBSA geometry, simplified to TopoJSON (<1 MB target) | Must match the OMB delineation vintage used everywhere else. |
| NIOSH NIOCCS autocoder (free API) | Independent second opinion on SOC coding for validation | Title/industry-text based; coarse on ambiguous titles. Used for agreement measurement only, not production coding. |
| Groq / Gemini free tier (primary), Ollama (local dev) | Classification + outlier sentences | Free-tier rate limits cap sample size (~1–2k postings/day sustainable). Provider-neutral prompts so the backend is swappable. |

**Pinned vintage rule:** one OMB CBSA delineation (July 2023 bulletin) governs
geometry, LAUS joins, OEWS joins, and the metro dimension table. Mixing
vintages breaks joins silently; this is a stated invariant, checked in CI.

### The counts-first design (why the free tier survives contact with reality)

Free-tier volume (~10–90k pulled postings/month) is a *sample* of national
posting flow, not a census. Two pipelines with different guarantees:

1. **Counts pipeline** — Adzuna's search response includes a total-match
   `count` for any filter combo. One call per metro per week (`where=` metro,
   results_per_page=1) yields near-census posting volumes for views 1 and 5
   at ~387 calls/week, well inside budget. Counts are cheap; details are not.
2. **Sample pipeline** — full posting details pulled for a classification
   sample: allocation proportional to metro volume with a per-metro floor of
   ~30 and cap of ~500 per period. Occupation shares, skill shares, and remote
   flags are estimates from this sample, with per-cell sample sizes disclosed.

## Schema sketch (DuckDB over committed Parquet)

Parquet partitions are the committed source of truth (append-only, weekly);
the `.duckdb` file is rebuilt in CI and never committed (see Flagged risks).

    dim_cbsa            cbsa_code PK, name, states, delineation_vintage
    counts_weekly       week, cbsa_code, query_key ('total'|'remote_kw'|...), source, count
    postings            posting_id PK (source:source_id), source, first_seen_week,
                        cbsa_code, title, employer_hash, description_hash
                        -- no posting text at rest in the repo; text lives only
                        -- in the transient classification step and a local
                        -- labeling cache (ToS + repo-size)
    classifications     posting_id, onet_soc (detailed), soc_major (2-digit),
                        skills LIST<skill_id>, is_remote BOOL,
                        model, prompt_version, classified_at
    skill_vocab         skill_id, label, aliases LIST, source ('onet-tech'|'curated')
    bls_labor_force     cbsa_code, month, labor_force
    bls_oews_shares     cbsa_code, soc_major, emp_share, ref_year
    validation_labels   posting_id, human_soc_major, human_onet_soc?, labeled_at
    outlier_sentences   week, cbsa_code, soc_major, z, sentence, model

Frontend consumes **precomputed static JSON** (one file per view per period,
plus the outliers file), generated by the aggregation step. No DB in the
browser.

## View definitions

Let `m` = metro, `o` = SOC major group, `k` = skill, `t` = ISO week.
`C_m(t)` = counted postings (counts pipeline); `n_m(t)` = classified sample
size; `LF_m` = LAUS labor force (latest available month).

1. **Postings per 1,000 workers** (default)
   `rate_m = 1000 · C_m(t) / LF_m`
2. **Occupation-mix deviation** (per selected `o`)
   `dev_{m,o} = ŝ_{m,o} − ŝ_{nat,o}` in percentage points, where
   `ŝ_{m,o} = n_{m,o}/n_m` from the classified sample and the national share
   is pooled across all metros. Diverging color scale centered at 0.
3. **Skill premium** (per selected `k`)
   `prem_{m,k} = log2( (n_{m,k}/n_m) / (n_{nat,k}/n_nat) )` — symmetric
   around 0; +1 means twice the national mention rate.
4. **Remote share** — `rem_m = n_{m,remote}/n_m` from the LLM remote flag.
   Displayed caveat: this is *employer posting location*; fully-remote
   postings often carry an HQ or arbitrary metro. The view measures "where
   remote-friendly employers post," not where remote workers are.
5. **Three-month change** — `Δ_m = (C_m(t) − C_m(t−13)) / C_m(t−13)` from the
   counts pipeline. Unlocks after 13 weeks of snapshots exist.

### Small-cell threshold (the deliberate version)

Treat cell counts as Poisson: the coefficient of variation of a rate estimate
is `1/√n`. Requiring CV ≤ 15% gives **n ≥ 45, rounded to n ≥ 50**.

- Count-based views (1, 5): gray out metros with `C_m < 50` in the period.
- Sample-based views (2, 3, 4): gray out cells whose *denominator*
  `n_m < 50` classified postings; skill cells additionally need `n_{m,k} ≥ 10`
  numerator mentions.
- The rule and the formula are disclosed verbatim on the page. Expect skill
  views to gray out most metros; that is honest, not a bug.

### Outliers panel

For each metro×occupation cell above threshold:
`z_{m,o} = (ŝ_{m,o} − ŝ_{nat,o}) / sqrt( ŝ_{nat,o}(1−ŝ_{nat,o}) / n_m )`
Rank by `|z|`, take the top ~10, and have the LLM write one sentence per cell.
The prompt receives only the numbers (metro, occupation, shares, z, sample
size) and is instructed to describe the deviation and hedge causal claims —
one sentence, no invented facts. Sentences are generated weekly in CI and
cached in `outlier_sentences`; the frontend never calls an LLM.

## Validation plan

The disclosed error rate is a release gate, not documentation.

1. **Hand-labeled sample** — 300 postings, stratified by predicted SOC major
   and metro size tercile. Label SOC major (detailed O*NET-SOC where
   confident). Report: accuracy at major-group level with Wilson 95% CI,
   plus per-class recall for the 8 largest groups. This number goes in the
   page footer.
2. **Independent coder agreement** — run NIOCCS on title (+ employer text)
   for the same sample; report LLM↔NIOCCS agreement at major-group level.
   Disagreements feed the labeling queue first (cheap targeted labels).
3. **Aggregate sanity vs OEWS** — for metros with ≥500 classified postings,
   correlate classified SOC-major shares against OEWS employment shares.
   Expected, documented divergences: postings overweight high-turnover
   occupations (food service, transport, healthcare support). A metro whose
   divergence pattern differs wildly from other metros' is a red flag.
4. **Drift guard** — a 50-posting golden set with human labels reruns on
   every prompt or model change; CI fails if major-group accuracy drops more
   than 5 points below the measured baseline.
5. **Detailed-level gate** — detailed O*NET-SOC views stay unshipped until a
   detailed-level error rate is measured on its own labeled sample.

## Build phases

- **Phase 0 — source spike (days, throwaway code).** Get Adzuna and
  CareerOneStop keys. For one mid-size metro (e.g. Columbus OH, CBSA 18140),
  measure: daily posting volume, `count`-field stability across identical
  queries, description truncation length, cross-day duplicate rate,
  remote-detectability from truncated text, CareerOneStop text quality and
  effective rate limits. **Exit criterion:** decide the Adzuna/CareerOneStop
  split for counts vs sample text, with numbers. This is the riskiest
  assumption in the project; it gets tested before any real code.
- **Phase 1 — one metro, end to end.** Weekly GitHub Action: ingest Columbus
  → classify (Groq or Gemini, prompt v1, closed skill vocab) → Parquet →
  aggregate JSON → React + d3-geo page on GitHub Pages rendering one shaded
  CBSA polygon with view 1. Ugly is fine; the pipe is the deliverable.
- **Phase 2 — validation harness.** Labeling flow (a local CLI is enough),
  300 labels, NIOCCS agreement run, golden set wired into CI, error rate
  rendered on the page. No scaling until this exists.
- **Phase 3 — national counts.** Counts pipeline for all ~387 CBSAs, full
  TopoJSON, thresholds + gray-out, views 1 live nationally. Sample-allocation
  logic for classification across metros.
- **Phase 4 — sample views + the panel.** Views 2, 3, 4; outliers panel with
  cached LLM sentences.
- **Phase 5 — trends.** After 13 weekly snapshots: view 5 and trend context
  in the outliers panel.

## Flagged risks and changed calls

1. **Adzuna truncates descriptions (~500 chars).** This is the biggest
   threat to skill extraction and the reason the design is counts-first:
   Adzuna is excellent as a *counting* instrument and mediocre as a *text*
   source. Mitigation: CareerOneStop/NLx supplies fuller text for the
   classification sample (Phase 0 verifies). Upgrade path if this project
   gets serious: apply to the NLx Research Hub for bulk posting data.
2. **Changed call: don't commit the `.duckdb` file.** A binary that churns
   100% every weekly run bloats git history and merge-conflicts by design.
   Committed source of truth = append-only weekly Parquet partitions;
   DuckDB is rebuilt in CI as the query engine; frontend reads static JSON.
   Same zero-cost guarantee, none of the churn.
3. **Changed call: Ollama is dev-only, not the pipeline.** GitHub Actions
   runners are 2-core CPU boxes; a weekly batch of even 2k postings through a
   local model is hours of flaky runtime against a 6-hour job cap. Groq or
   Gemini free tiers handle the same batch in minutes. Prompts stay
   provider-neutral; Ollama remains the local dev/debug loop.
4. **Remote share measures employer posting location, by construction.**
   Kept as specified, but the caveat is rendered on the view itself, because
   every reader will misread it otherwise.
5. **Vintage mismatch is the silent killer of CBSA joins.** One OMB
   delineation vintage pinned across geometry, LAUS, OEWS, and dims; CI
   asserts every cbsa_code in every table exists in `dim_cbsa`.
6. **"Free" binds at API call budgets, not compute or hosting.** The
   counts-first split is shaped entirely around Adzuna's ~250 calls/day.
   If limits tighten, counts cadence degrades to biweekly before anything
   else gives.
