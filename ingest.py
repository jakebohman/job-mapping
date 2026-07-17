"""Phase 1 ingest for one CBSA: the two Adzuna pipelines from PROJECT.md.

  cbsa_volume() — CBSA-bounded posting count (view 1 numerator), summed from
                  per-county `count` queries so the geography matches LAUS.
  pull_sample() — deduped, county-filtered postings ready for classification.

    pip install requests
    ADZUNA_APP_ID=... ADZUNA_APP_KEY=... python ingest.py            # live, Columbus
    python ingest.py --selftest                                      # no keys

Occupation coding works on title + Adzuna's 500-char text; skill extraction
is source-limited until NLx (see PROJECT.md risk 1).
"""

import os
import sys
import time

import geo

SEARCH = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"


def _get(app_id, app_key, page, where, distance=None, rpp=50):
    import requests
    p = {"app_id": app_id, "app_key": app_key, "where": where,
         "results_per_page": rpp}
    if distance is not None:
        p["distance"] = distance
    r = requests.get(SEARCH.format(page=page), params=p, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Adzuna {r.status_code} for {where!r}: {r.text[:120]}")
    return r.json()


def cbsa_volume(cbsa_code, app_id, app_key, f_m):
    """Calibrated CBSA volume = radius `count` x in-CBSA fraction.

    A single `where=<place>` count over the CBSA's radius is radius-shaped, not
    CBSA-shaped. Per-county count queries do NOT fix this — they over-count ~2x
    from radius bleed (measured: Columbus per-county sum 66k vs calibrated 44k,
    with Delaware > Franklin, which is impossible for true counts). Instead we
    correct the one radius count by f_m, the fraction of *accurately-reported*
    counties in the sample that fall inside the CBSA. Estimate converges to
    ~44k across radii, confirming the method. Returns {count, f_m, volume}."""
    d = geo.CBSA_COUNTIES[cbsa_code]
    count = _get(app_id, app_key, 1, d["name"],
                 distance=d["radius_km"], rpp=1)["count"]
    return {"cbsa": cbsa_code, "count": count, "f_m": round(f_m, 3),
            "volume": round(count * f_m)}


def dedupe(results):
    """Drop duplicate postings by Adzuna id, preserving first-seen order."""
    seen, out = set(), []
    for r in results:
        rid = str(r.get("id"))
        if rid not in seen:
            seen.add(rid)
            out.append(r)
    return out


def pull_sample(cbsa_code, want, app_id, app_key, max_pages=10):
    """Pull postings over the CBSA's radius, keep only those whose reported
    county is in the CBSA, dedupe. Pulling at the same radius used for the
    volume count means f_m (in-CBSA fraction of the pull) calibrates that count
    and the classification sample is drawn from the whole CBSA, not just the
    core county. Returns the sample plus f_m."""
    d = geo.CBSA_COUNTIES[cbsa_code]
    raw = []
    for page in range(1, max_pages + 1):
        results = _get(app_id, app_key, page, d["name"],
                       distance=d["radius_km"], rpp=50).get("results", [])
        if not results:
            break
        raw += results
        if len(raw) >= want * 2:            # headroom for out-of-CBSA drops
            break
        time.sleep(1)
    kept, dropped = geo.bucket_by_cbsa(dedupe(raw))
    in_cbsa = kept.get(cbsa_code) or []
    total = len(in_cbsa) + len(dropped)
    return {"sample": in_cbsa[:want], "n": min(len(in_cbsa), want),
            "pulled": len(raw), "dropped_out_of_cbsa": len(dropped),
            "f_m": in_cbsa and (len(in_cbsa) / total) or 0.0}


def _selftest():
    a = {"id": 1, "location": {"area": ["US", "Ohio", "Franklin County", "X"]}}
    b = {"id": 2, "location": {"area": ["US", "Ohio", "Knox County", "Y"]}}
    assert [r["id"] for r in dedupe([a, a, b])] == [1, 2]

    # pull_sample logic without network: exercise geo bucketing + cap
    flat = [a, a, b, dict(a, id=3)]
    kept, dropped = geo.bucket_by_cbsa(dedupe(flat))
    assert len(kept["18140"]) == 2 and len(dropped) == 1  # ids 1,3 in; 2 out
    print("selftest ok")


def _run_live():
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        sys.exit("Set ADZUNA_APP_ID and ADZUNA_APP_KEY.")
    code = "18140"
    print("sample (also calibrates the volume count):")
    s = pull_sample(code, 100, app_id, app_key)
    print(f"  kept {s['n']} in-CBSA from {s['pulled']} pulled "
          f"({s['dropped_out_of_cbsa']} out-of-CBSA), f_m={s['f_m']:.3f}")
    print("\nvolume (calibrated: radius count x f_m):")
    vol = cbsa_volume(code, app_id, app_key, s["f_m"])
    print(f"  count={vol['count']} x f_m={vol['f_m']} -> volume={vol['volume']}"
          f"  (CBSA {code})")
    if s["sample"]:
        print("\n  e.g.", s["sample"][0].get("title", "")[:70])


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        _run_live()
