"""Build the national map's shading data: postings per 1,000 workers for every
metro. For each of the ~393 MSAs, one Adzuna call yields both the total count
(over the metro's search radius) and the fraction of the returned postings that
actually fall inside the CBSA (f_m) — so the radius count is corrected to CBSA
geography before dividing by the metro's BLS labor force. Without f_m, a small
metro's radius swallows a neighboring big metro's postings and reads as
impossibly hot (Columbus IN: 1,246/1,000 uncorrected).

Still uncalibrated for reposts (which inflate ~uniformly), so read the map for
relative intensity. Metros with fewer than 50 in-CBSA postings, or no labor
force, are drawn gray (PROJECT.md's n>=50 rule).

    ADZUNA_APP_ID=... ADZUNA_APP_KEY=... python pipeline/build_national.py

Resumable: each metro is cached as fetched (site/data/_national_cache.json),
throttled to Adzuna's ~25/min, so a run that hits the daily cap just resumes.
Writes site/data/national.json.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import bls
import geo
import ingest

OUT = Path(__file__).parent.parent / "site" / "data"
MIN_COUNT = 50          # PROJECT.md small-cell threshold (in-CBSA postings)
CALL_INTERVAL = 2.6     # Adzuna free tier ~25/min


def _measure(app_id, app_key, code, tries=4):
    """One Adzuna call → {count, f_m}: total match count plus the share of the
    returned 50 postings whose reported county lies in this CBSA."""
    d = geo.CBSA_COUNTIES[code]
    for attempt in range(tries):
        try:
            js = ingest._get(app_id, app_key, 1, d["adzuna_where"],
                             distance=d["radius_km"], rpp=50)
            break
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)
    results = js.get("results", [])
    in_cbsa = sum(1 for r in results if geo.cbsa_of(r) == code)
    return {"count": js.get("count", 0),
            "f_m": round(in_cbsa / len(results), 3) if results else 0.0}


def _percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, int(round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def build_report(measures, labor, names):
    """Pure: {code:{count,f_m}}, {code:{labor_force}}, {code:name} -> report.
    effective in-CBSA postings = count*f_m; rate = 1000*effective/labor_force;
    below threshold if effective<50 or no labor force."""
    metros, rates = [], []
    for code, mz in measures.items():
        count, f_m = mz["count"], mz["f_m"]
        effective = round(count * f_m)
        lf = (labor.get(code) or {}).get("labor_force")
        below = effective < MIN_COUNT or not lf
        rate = None if below else round(1000 * effective / lf, 2)
        if rate is not None:
            rates.append(rate)
        metros.append({"cbsa": code, "name": names.get(code, code),
                       "count": count, "f_m": f_m, "effective": effective,
                       "labor_force": lf, "rate": rate, "below_threshold": below})
    metros.sort(key=lambda m: (m["rate"] is None, -(m["rate"] or 0)))
    rates.sort()
    return {
        "metric": "Postings per 1,000 workers",
        "method": ("One Adzuna count per metro, corrected to CBSA geography by "
                   "the in-sample in-CBSA fraction (f_m), divided by the metro's "
                   "BLS LAUS labor force, x1000. Not repost-corrected, so read "
                   "the map for relative intensity — absolute values run high. "
                   "Metros with fewer than 50 in-CBSA postings or no labor force "
                   "are shown gray."),
        "caveats": [
            "Job-posting demand, not employment.",
            "Not repost-corrected; relative shading is the signal, not the number.",
            f"{sum(m['below_threshold'] for m in metros)} of {len(metros)} "
            "measured metros are below threshold (gray).",
        ],
        # robust color domain (5th-95th pct) so one extreme metro can't wash it out
        "domain": [_percentile(rates, 5), _percentile(rates, 95)],
        "rate_range": [rates[0], rates[-1]] if rates else [None, None],
        "metros": metros,
    }


def run():
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        sys.exit("Set ADZUNA_APP_ID and ADZUNA_APP_KEY.")
    OUT.mkdir(parents=True, exist_ok=True)
    cache_path = OUT / "_national_cache.json"
    measures = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    codes = sorted(geo.CBSA_COUNTIES)
    for n, code in enumerate(codes):
        if code in measures:
            continue
        try:
            measures[code] = _measure(app_id, app_key, code)
        except Exception as e:
            print(f"  stopped at {code} ({e}); have {len(measures)}/{len(codes)} — re-run to resume")
            break
        cache_path.write_text(json.dumps(measures))
        if n % 25 == 0:
            print(f"  {len(measures)}/{len(codes)} metros measured ...")
        time.sleep(CALL_INTERVAL)

    # Labor force is stable month-to-month and its keyless quota is tiny, so
    # cache it and only fetch metros we don't have yet — the cache fills across
    # runs (and survives the BLS daily cap).
    lf_path = OUT / "_lf_cache.json"
    labor = json.loads(lf_path.read_text()) if lf_path.exists() else {}
    missing = [c for c in measures if not (labor.get(c) or {}).get("labor_force")]
    if missing:
        print(f"[bls] labor force: {len(labor)} cached, fetching {len(missing)} ...")
        labor.update(bls.labor_force_batch(missing, datetime.now().year - 1,
                                           datetime.now().year))
        lf_path.write_text(json.dumps(labor))
    else:
        print(f"[bls] labor force: all {len(labor)} cached")
    names = {c: geo.CBSA_COUNTIES[c]["name"] for c in measures}
    report = build_report(measures, labor, names)
    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["metros_covered"] = len(measures)
    report["metros_total"] = len(codes)
    (OUT / "national.json").write_text(json.dumps(report))

    shaded = [m for m in report["metros"] if not m["below_threshold"]]
    print(f"\nWrote {OUT/'national.json'} — {len(measures)}/{len(codes)} metros, "
          f"{len(shaded)} shaded, domain {report['domain']} per 1,000")
    for m in shaded[:6]:
        print(f"  {m['rate']:6.1f}  (f_m {m['f_m']})  {m['name']}")


def _selftest():
    assert _percentile([1, 2, 3, 4, 5], 0) == 1 and _percentile([1, 2, 3, 4, 5], 100) == 5
    # A: 1000 count x f_m 1.0 = 1000 eff / 100k LF -> 10.0
    # B: 1000 x 0.02 = 20 eff -> below threshold (radius mostly outside CBSA)
    # C: 500 x 1.0 = 500 eff / 200k -> 2.5
    measures = {"A": {"count": 1000, "f_m": 1.0}, "B": {"count": 1000, "f_m": 0.02},
                "C": {"count": 500, "f_m": 1.0}}
    labor = {"A": {"labor_force": 100000}, "B": {"labor_force": 50000},
             "C": {"labor_force": 200000}}
    rep = build_report(measures, labor, {"A": "A", "B": "B", "C": "C"})
    by = {m["cbsa"]: m for m in rep["metros"]}
    assert by["A"]["rate"] == 10.0 and by["C"]["rate"] == 2.5
    assert by["B"]["below_threshold"] and by["B"]["rate"] is None   # f_m corrects the bleed
    assert rep["metros"][0]["cbsa"] == "A" and rep["metros"][-1]["cbsa"] == "B"
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        run()
