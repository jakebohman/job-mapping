"""Phase 1 end-to-end for one CBSA: ingest -> classify -> aggregate -> static
JSON + geometry, ready for the map. This is the pipe the design's Phase 1 asks
for; ugly is fine.

    ADZUNA_APP_ID=... ADZUNA_APP_KEY=... python pipeline.py

Writes site/data/<cbsa>.json and site/data/cbsa_<cbsa>.geojson.

Storage note: Phase 1 persists JSON (the frontend reads it directly). The
Parquet/DuckDB store from PROJECT.md arrives with national scale (Phase 3),
where query volume justifies the engine; ~150 rows for one metro does not.
"""

import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import bls
import classify
import geo
import ingest

SAMPLE_WANT = 150
MIN_CELL_N = 50   # PROJECT.md small-cell threshold (Poisson CV<=15% -> n>=50)
OUT = Path(__file__).parent / "site" / "data"
TIGERWEB = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
            "CBSA/MapServer/3/query")


def occupation_shares(classifications):
    """Share of the classified sample in each SOC major group (view 2 building
    block). Cells with n<MIN_CELL_N are flagged, not dropped, for one metro."""
    coded = [c for c in classifications if c["soc_major"]]
    n = len(coded)
    counts = Counter(c["soc_major"] for c in coded)
    rows = [{"soc_major": mj, "title": classify.SOC_MAJOR_TITLES[mj],
             "n": cnt, "share": round(cnt / n, 4) if n else 0.0}
            for mj, cnt in counts.most_common()]
    return n, rows


def fetch_geometry(cbsa_code):
    import requests
    r = requests.get(TIGERWEB, params={
        "where": f"GEOID='{cbsa_code}'", "outFields": "GEOID,NAME",
        "f": "geojson", "geometryPrecision": "4", "outSR": "4326"}, timeout=60)
    r.raise_for_status()
    js = r.json()
    if not js.get("features"):
        raise RuntimeError(f"No CBSA geometry for {cbsa_code}")
    return js


def run(cbsa_code="18140"):
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        sys.exit("Set ADZUNA_APP_ID and ADZUNA_APP_KEY.")
    d = geo.CBSA_COUNTIES[cbsa_code]

    print(f"[1/5] ingest sample for {d['name']} ...")
    s = ingest.pull_sample(cbsa_code, SAMPLE_WANT, app_id, app_key)
    print(f"      {s['n']} in-CBSA / {s['pulled']} pulled, f_m={s['f_m']:.3f}")

    print(f"[2/5] classify {s['n']} postings via NIOCCS (interim) ...")
    classifications = classify.classify_sample(s["sample"])
    n_coded, shares = occupation_shares(classifications)
    print(f"      {n_coded}/{s['n']} coded to a SOC major group")

    print("[3/5] calibrated volume ...")
    vol = ingest.cbsa_volume(cbsa_code, app_id, app_key, s["f_m"])
    # Adzuna's count field can't be de-duped; estimate distinct demand by the
    # sample's repost ratio. Raw = upper bound, distinct = lower bound.
    distinct_volume = round(vol["volume"] * s["dedup_ratio"])

    print("[4/5] BLS LAUS labor force ...")
    lf = bls.labor_force(cbsa_code, date.today().year - 1, date.today().year)

    def per_1k(v):
        return round(1000 * v / lf["labor_force"], 2) if lf["labor_force"] else None
    per_1000 = per_1k(distinct_volume)   # headline uses the distinct estimate

    print("[5/5] geometry + write ...")
    geometry = fetch_geometry(cbsa_code)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"cbsa_{cbsa_code}.geojson").write_text(json.dumps(geometry))

    report = {
        "cbsa": cbsa_code,
        "name": d["name"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "view1_postings_per_1000": per_1000,
        "view1_range_per_1000": {"distinct": per_1000,
                                 "raw_with_reposts": per_1k(vol["volume"])},
        "volume": {**vol, "distinct_estimate": distinct_volume,
                   "dedup_ratio": s["dedup_ratio"]},
        "labor_force": lf,
        "sample": {"n": s["n"], "n_coded": n_coded,
                   "dropped_out_of_cbsa": s["dropped_out_of_cbsa"],
                   "reposts_collapsed": s["reposts_collapsed"],
                   "f_m": round(s["f_m"], 3), "dedup_ratio": s["dedup_ratio"]},
        "occupation_shares": shares,
        "meta": {
            "coder": "NIOSH NIOCCS (interim; LLM to replace)",
            "min_cell_n": MIN_CELL_N,
            "threshold_note": ("Cells below n=50 are low-confidence "
                               "(Poisson CV<=15% requires n>=50)."),
            "below_threshold": s["n"] < MIN_CELL_N,
            "caveats": [
                "Volume is a calibrated estimate: radius count x in-CBSA "
                "fraction (f_m), not a census.",
                f"~{round((1 - s['dedup_ratio']) * 100)}% of the sample were "
                "near-duplicate reposts (same title+employer); headline uses "
                "the repost-collapsed estimate, raw count is the upper bound.",
                "Occupation shares are from a sample; skills not extracted "
                "(Adzuna text is 500-char capped).",
                f"{s['n'] - n_coded}/{s['n']} postings uncoded by NIOCCS "
                "(interim coder), concentrated in physician 'opportunity' ads.",
            ],
        },
    }
    out = OUT / f"{cbsa_code}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out}")
    print(f"  view 1: {per_1000} postings per 1,000 workers "
          f"(distinct est. {distinct_volume:,}, raw {vol['volume']:,} / "
          f"LF {lf['labor_force']:,} as of {lf['as_of']})")
    print(f"  sample {s['n']} distinct ({s['reposts_collapsed']} reposts collapsed)")
    print("  top occupations:",
          ", ".join(f"{r['title']} {r['share']:.0%}" for r in shares[:4]))


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "18140")
