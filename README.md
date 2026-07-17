# job-mapping

Interactive choropleth analysis of US metro (CBSA) labor demand from
LLM-classified job postings. Insight, not a job board — see [PROJECT.md](PROJECT.md)
for the full design, view formulas, validation plan, and build phases.

## Where things stand

**Phase 0 — source spike.** De-risking the posting sources before any pipeline
code, per PROJECT.md. Run against one metro (Columbus OH) to get real numbers on
Adzuna volume, count-field stability, description truncation, and CareerOneStop
text quality.

```sh
pip install -r requirements.txt
cp .env.example .env          # add free Adzuna + CareerOneStop keys
python phase0_source_spike.py            # live measurement run
python phase0_source_spike.py --selftest # verify analysis logic, no keys needed
```

Output lands in `spike_results/` (gitignored). Run on two separate days to
capture the cross-day duplicate rate. **Exit criterion:** decide the
Adzuna/CareerOneStop split for counts vs sample text, with numbers.
