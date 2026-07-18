# job-mapping

Interactive choropleth analysis of US metro (CBSA) labor demand from
LLM-classified job postings. Insight, not a job board — see [PROJECT.md](PROJECT.md)
for the full design, view formulas, validation plan, and build phases.

## Where things stand

**The demo is the outliers panel** — where each metro's hiring mix deviates
from national, ranked, with a templated sentence each. Built on Adzuna category
**counts** (a census, immune to advertiser ranking), not classified samples.
See PROJECT.md for why (the pivot and its findings).

```sh
pip install -r requirements.txt
export ADZUNA_APP_ID=... ADZUNA_APP_KEY=...   # free key from developer.adzuna.com

python panel.py               # ~25 calls/min, resumable -> site/data/outliers.json
cd site && python -m http.server 8000         # open http://localhost:8000
```

`site/index.html` is the ranked panel; `site/map.html` is the earlier
single-metro choropleth (view 1) kept as context, fed by `python pipeline.py`.

### Modules
- `panel.py` — **the demo**: metro category-count mix vs national, ranked by deviation
- `ingest.py` — Adzuna sample + calibrated CBSA volume (county-bucketed, repost-deduped)
- `classify.py` — occupation coding via **NIOCCS** (keyless, interim; used by the map)
- `bls.py` — LAUS labor force (keyless), the view-1 denominator
- `geo.py` — county ↔ CBSA from the national OMB crosswalk (393 MSAs)
- `build_crosswalk.py` — one-time: builds `cbsa_counties.csv` from the Census delineation
- `pipeline.py` — single-metro map pipeline -> static JSON + geometry

Each module self-tests: `python <module>.py --selftest`.

### Cut corners (deliberate, reversible — see PROJECT.md)
Categories not O*NET SOC (sampling is advertiser-biased until NLx); templated
sentences not LLM; JSON not Parquet; ranked list not national choropleth.

### Not yet done
LLM sentences/classifier (needs a Groq/Gemini key), skills (blocked on NLx),
GitHub Action + Pages deploy, cross-day duplicate rate (second-day spike run).
