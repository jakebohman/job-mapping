"""Build the national map's shading data: postings per 1,000 workers for every
metro. For each of the ~393 MSAs, one Adzuna call yields both the total count
(over the metro's search radius) and the fraction of the returned postings that
actually fall inside the CBSA (f_m) — so the radius count is corrected to CBSA
geography before dividing by the metro's BLS labor force. Without f_m, a small
metro's radius swallows a neighboring big metro's postings and reads as
impossibly hot (Columbus IN: 1,246/1,000 uncorrected).

Still uncalibrated for reposts (which inflate ~uniformly), so read the map for
relative intensity. Metros with fewer than 50 in-CBSA postings, or no labor
force, are drawn gray (CLAUDE.md's n>=50 rule).

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
MIN_COUNT = 50          # CLAUDE.md small-cell threshold (in-CBSA postings)
MIN_FM = 0.10           # the whole rate rests on f_m; below ~5 of the 50 sampled
                        # postings falling in-CBSA it is too noisy to trust (a
                        # huge radius count x a 1-posting f_m still clears
                        # MIN_COUNT), so gray out — this is radius bleed, not a
                        # measured metro (e.g. Columbus IN measuring Indianapolis)
CALL_INTERVAL = 2.6     # Adzuna free tier ~25/min
EXCLUDED_STATES = {"72"}   # Puerto Rico: Adzuna returns unreliable locations for
                           # PR searches (often Florida), so it isn't measurable


def _fetch(app_id, app_key, where, distance, tries=4):
    for attempt in range(tries):
        try:
            return ingest._get(app_id, app_key, 1, where, distance=distance, rpp=50)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def _metrics(js, code):
    """Adzuna response → {count, f_m, dedup_ratio} for CBSA `code`.
    f_m = share of the returned 50 postings whose reported county lies in this
    CBSA; dedup_ratio = distinct share of those in-CBSA postings after collapsing
    reposts by title+employer (reuses ingest.dedupe_semantic — the count field
    itself can't be de-duped, so this per-metro ratio calibrates it down)."""
    results = js.get("results", [])
    in_cbsa = [r for r in results if geo.cbsa_of(r) == code]
    distinct = ingest.dedupe_semantic(in_cbsa)
    return {
        "count": js.get("count", 0),
        "f_m": round(len(in_cbsa) / len(results), 3) if results else 0.0,
        "dedup_ratio": round(len(distinct) / len(in_cbsa), 3) if in_cbsa else 1.0,
    }


def _wrong_state(js, code):
    """True if the sample's modal state differs from the metro's Central-county
    state — the fingerprint of an ambiguous geocode (Adzuna picked the wrong
    same-named city), as opposed to radius bleed into a same-state neighbor
    (Columbus IN's radius measuring Indianapolis), which correctly stays gray."""
    states = {}
    for r in js.get("results", []):
        cc = geo.county_of(r)
        if cc:
            states[cc[0]] = states.get(cc[0], 0) + 1
    if not states:
        return False
    modal = max(states, key=states.get)
    expected = geo.CBSA_COUNTIES[code].get("central_state")
    return bool(expected) and modal != expected


SMALLER_RADII = (25, 15, 10)   # km, tried in turn to shed a big neighbor's radius bleed


def _measure(app_id, app_key, code):
    """One Adzuna call → {count, f_m, dedup_ratio}. A metro that would otherwise
    gray on f_m gets second-chance measurements, tried in order and the best f_m
    kept (stopping once one clears the floor):
      - if the base geocode returned postings but f_m is low (radius bleed), tighter
        radii shed a bigger neighbor's postings (e.g. Allentown next to Philadelphia);
      - if the base geocode returned nothing (a place Adzuna can't resolve, like
        "Coeur d'Alene") or the sample landed in the wrong state (an ambiguous name,
        like "Corvallis, OR" resolving to Corvallis, MT), re-anchor on a Central
        county — at the full radius and tighter.
    A genuinely small metro (few postings but a *working* geocode) is left to gray;
    only a failed/ambiguous geocode or radius bleed triggers the extra calls."""
    d = geo.CBSA_COUNTIES[code]
    where, radius = d["adzuna_where"], d["radius_km"]
    county, state = d.get("central_county"), d.get("central_state")
    js = _fetch(app_id, app_key, where, radius)
    m = _metrics(js, code)
    if m["f_m"] >= MIN_FM:
        return m                                        # measured fine
    if m["count"] < MIN_COUNT and js.get("results"):
        return m                                        # geocode worked; genuinely small -> gray
    retries = []
    if js.get("results"):                               # geocode worked -> tighten to shed a neighbor
        retries += [(where, r) for r in SMALLER_RADII if r < radius]
    if county and state and (not js.get("results") or _wrong_state(js, code)):
        retries += [(f"{county}, {state}", r) for r in (radius, *SMALLER_RADII)]  # fix a bad geocode
    for alt_where, alt_radius in retries:
        alt = _metrics(_fetch(app_id, app_key, alt_where, alt_radius), code)
        if alt["f_m"] > m["f_m"]:
            m = alt
        if m["f_m"] >= MIN_FM:
            break
    return m


def _percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, int(round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def build_report(measures, labor, names):
    """Pure: {code:{count,f_m,dedup_ratio}}, {code:{labor_force}}, {code:name} ->
    report. effective in-CBSA postings = count*f_m*dedup_ratio (dedup_ratio
    corrects for reposts; a pre-calibration entry lacking it is left uncorrected
    at 1.0); rate = 1000*effective/labor_force; below threshold if effective<50
    or no labor force."""
    metros, rates = [], []
    for code, mz in measures.items():
        if geo.CBSA_COUNTIES.get(code, {}).get("state_fips") in EXCLUDED_STATES:
            continue                              # excluded (PR): unreliable source
        count, f_m = mz["count"], mz["f_m"]
        dedup = mz.get("dedup_ratio", 1.0)      # pre-calibration entries: no correction
        effective = round(count * f_m * dedup)
        lf = (labor.get(code) or {}).get("labor_force")
        below = effective < MIN_COUNT or not lf or f_m < MIN_FM
        rate = None if below else round(1000 * effective / lf, 2)
        if rate is not None:
            rates.append(rate)
        metros.append({"cbsa": code, "name": names.get(code, code),
                       "count": count, "f_m": f_m, "dedup_ratio": dedup,
                       "effective": effective, "labor_force": lf, "rate": rate,
                       "below_threshold": below})
    metros.sort(key=lambda m: (m["rate"] is None, -(m["rate"] or 0)))
    rates.sort()
    return {
        "metric": "Postings per 1,000 workers",
        "method": ("Live job postings from Adzuna, corrected to each metro's real "
                   "boundary and divided by its local workforce — hiring intensity, "
                   "not raw size; it measures posting demand, not hires. "
                   "Full method in METHODOLOGY.md."),
        "caveats": [
            "Job-posting demand, not employment.",
            "Repost-corrected via the in-sample distinct fraction; a lower bound "
            "on distinct demand (multi-site openings can collapse together).",
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

    codes = [c for c in sorted(geo.CBSA_COUNTIES)
             if geo.CBSA_COUNTIES[c]["state_fips"] not in EXCLUDED_STATES]
    measures = {c: m for c, m in measures.items() if c in set(codes)}   # drop excluded
    for n, code in enumerate(codes):
        if code in measures and "dedup_ratio" in measures[code]:
            continue      # backfill entries measured before repost calibration
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

    # _metrics: f_m = in-CBSA share; dedup_ratio = distinct share of in-CBSA.
    fr = {"location": {"area": ["US", "Ohio", "Franklin County", "X"]},
          "title": "Nurse", "company": {"display_name": "Acme"}}
    repost = dict(fr)                                   # same title+employer -> repost
    out = {"location": {"area": ["US", "Indiana", "Marion County", "Y"]}}  # not 18140
    m = _metrics({"count": 900, "results": [fr, repost, out]}, "18140")
    assert m["count"] == 900 and m["f_m"] == round(2 / 3, 3) and m["dedup_ratio"] == 0.5

    # _wrong_state: modal state != the metro's Central-county state (ambiguous
    # geocode) is True; same-state radius bleed is False.
    ind = {"location": {"area": ["US", "Indiana", "Marion County", "Y"]}}
    oh = {"location": {"area": ["US", "Ohio", "Franklin County", "X"]}}
    assert _wrong_state({"results": [ind, ind, oh]}, "18140") is True
    assert _wrong_state({"results": [oh, oh, ind]}, "18140") is False

    # build_report: effective = count * f_m * dedup_ratio.
    # A: 1000 x 1.0 x 0.5 = 500 eff / 100k LF -> 5.0
    # B: 1000 x 0.02 x 0.5 = 10 eff -> below threshold (radius mostly outside CBSA)
    # C: 500 x 1.0, no dedup_ratio (pre-calibration entry -> 1.0) -> 500 / 200k -> 2.5
    # D: 5000 x 0.04 = 200 eff (clears MIN_COUNT) but f_m 0.04 < MIN_FM -> gray
    #    (the 1-posting-f_m case: a huge radius count can't rescue a thin sample)
    measures = {"A": {"count": 1000, "f_m": 1.0, "dedup_ratio": 0.5},
                "B": {"count": 1000, "f_m": 0.02, "dedup_ratio": 0.5},
                "C": {"count": 500, "f_m": 1.0},
                "D": {"count": 5000, "f_m": 0.04, "dedup_ratio": 1.0}}
    labor = {"A": {"labor_force": 100000}, "B": {"labor_force": 50000},
             "C": {"labor_force": 200000}, "D": {"labor_force": 100000}}
    rep = build_report(measures, labor, {"A": "A", "B": "B", "C": "C", "D": "D"})
    by = {m["cbsa"]: m for m in rep["metros"]}
    assert by["A"]["rate"] == 5.0 and by["C"]["rate"] == 2.5   # C exercises dedup default 1.0
    assert by["B"]["below_threshold"] and by["B"]["rate"] is None   # f_m corrects the bleed
    assert by["D"]["effective"] == 200 and by["D"]["below_threshold"]  # MIN_FM floor
    assert rep["metros"][0]["cbsa"] == "A"                       # highest rate first

    # _measure tighter-radius recovery: a same-state metro swamped at the default
    # radius (low f_m) recovers at a smaller radius. Stub _fetch by radius.
    global _fetch
    saved_fetch, saved_r = _fetch, geo.CBSA_COUNTIES["18140"]["radius_km"]
    inn = {"location": {"area": ["US", "Ohio", "Franklin County", "X"]},
           "title": "T", "company": {"display_name": "C"}}
    oh_out = {"location": {"area": ["US", "Ohio", "Knox County", "Y"]}}   # Ohio, no MSA
    geo.CBSA_COUNTIES["18140"]["radius_km"] = 50
    _fetch = lambda ai, ak, where, r, tries=4: {          # noqa: E731 (test stub)
        "count": 5000,
        "results": ([inn] * 2 + [oh_out] * 48) if r >= 50 else ([inn] * 40 + [oh_out] * 10)}
    rec = _measure("x", "x", "18140")
    _fetch, geo.CBSA_COUNTIES["18140"]["radius_km"] = saved_fetch, saved_r
    assert rec["f_m"] >= MIN_FM and rec["f_m"] == 0.8   # tighter radius (25km) recovered it

    # cross-border recovery: sample lands in the wrong state (wrong_state True) but
    # the county re-anchor also fails, so it must fall back to a tighter radius.
    saved2 = _fetch
    oh = {"location": {"area": ["US", "Ohio", "Franklin County", "X"]},
          "title": "T", "company": {"display_name": "C"}}
    ind = {"location": {"area": ["US", "Indiana", "Marion County", "Y"]}}   # wrong state, not 18140
    def _stub(ai, ak, w, r, tries=4):                    # noqa: E306 (test stub)
        if r < 50:                                       # tighter radius -> mostly in-CBSA
            return {"count": 800, "results": [oh] * 40 + [ind] * 10}
        if "County" in w:                                # county re-anchor at full radius -> fails
            return {"count": 5000, "results": [oh] * 2 + [ind] * 48}
        return {"count": 5000, "results": [oh] * 1 + [ind] * 49}   # base -> wrong state, f_m 0.02
    _fetch = _stub
    rec2 = _measure("x", "x", "18140")
    _fetch = saved2
    assert rec2["f_m"] == 0.8   # re-anchor failed; the tighter-radius fallback recovered it

    # geocode failure: the city name returns NO results (e.g. "Coeur d'Alene"), so
    # tighter radii can't help — recovery must fall back to the Central-county anchor.
    saved3 = _fetch
    inca = {"location": {"area": ["US", "Ohio", "Franklin County", "X"]},
            "title": "T", "company": {"display_name": "C"}}
    def _stub3(ai, ak, w, r, tries=4):                   # noqa: E306 (test stub)
        if "County" in w:                                # county anchor resolves -> mostly in-CBSA
            return {"count": 800, "results": [inca] * 45
                    + [{"location": {"area": ["US", "Ohio", "Knox County", "Y"]}}] * 5}
        return {"count": 0, "results": []}               # city geocode fails outright
    _fetch = _stub3
    rec3 = _measure("x", "x", "18140")
    _fetch = saved3
    assert rec3["f_m"] >= MIN_FM   # a failed city geocode is recovered via the county anchor
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        run()
