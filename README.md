# job-mapping

Interactive choropleth analysis of US metro (CBSA) labor demand from
LLM-classified job postings. Insight, not a job board — see [PROJECT.md](PROJECT.md)
for the full design, view formulas, validation plan, and build phases.

## Where things stand

**Phase 0 (source spike) and Phase 1 (one metro, end to end) are working** for
Columbus OH (CBSA 18140). See PROJECT.md for findings and the honest caveats.

```sh
pip install -r requirements.txt
export ADZUNA_APP_ID=... ADZUNA_APP_KEY=...   # free key from developer.adzuna.com

python pipeline.py            # ingest -> classify -> aggregate -> site/data/*.json
cd site && python -m http.server 8000         # open http://localhost:8000
```

The pipeline writes `site/data/<cbsa>.json` + geometry; `site/index.html`
renders the shaded CBSA polygon (view 1) with the occupation mix and caveats.

### Modules
- `ingest.py` — Adzuna sample + calibrated CBSA volume (county-bucketed, repost-deduped)
- `classify.py` — occupation coding via **NIOCCS** (keyless, interim; LLM to replace)
- `bls.py` — LAUS labor force (keyless), the view-1 denominator
- `geo.py` — county ↔ CBSA (Columbus hardcoded; national loads the OMB crosswalk)
- `pipeline.py` — orchestrates the above into static JSON
- `phase0_source_spike.py` — the throwaway measurement spike (`--selftest` needs no keys)

Each module self-tests: `python <module>.py --selftest`.

### Not yet done
LLM classifier (needs a Groq/Gemini key), skill extraction (blocked on NLx —
Adzuna text is 500-char capped), national rollout, GitHub Action + Pages
deploy, cross-day duplicate rate (needs a second-day spike run).
