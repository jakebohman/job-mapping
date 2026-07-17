"""County -> CBSA geography. Resolves PROJECT.md risk 7: Adzuna is radius-based,
but every result carries its county and a CBSA is a set of counties, so county
is the exact join key between postings and BLS/LAUS metro series.

Phase 1 hardcodes the one metro (Columbus). National rollout replaces
CBSA_COUNTIES with the OMB delineation crosswalk (a free CSV):
  https://www.census.gov/geographies/reference-files/time-series/demo/metro-micro/delineation-files.html
Load it into the same {cbsa_code: (name, {counties})} shape and nothing
downstream changes.

    python geo.py --selftest
"""

import sys

# CBSA 18140, Columbus OH MSA, 2023 OMB delineation (10 counties).
CBSA_COUNTIES = {
    "18140": {
        "name": "Columbus, OH",
        "state": "Ohio",
        "counties": {
            "Delaware County", "Fairfield County", "Franklin County",
            "Hocking County", "Licking County", "Madison County",
            "Morrow County", "Perry County", "Pickaway County", "Union County",
        },
    },
}

# Reverse index: (state, county) -> cbsa_code. Built once at import.
_COUNTY_TO_CBSA = {
    (d["state"], county): code
    for code, d in CBSA_COUNTIES.items()
    for county in d["counties"]
}


def county_of(adzuna_result):
    """Extract (state, county) from an Adzuna result's location.area hierarchy.
    area looks like [US, Ohio, Franklin County, Hilliard]; state is index 1,
    county is the entry ending in 'County'. Returns (state, county) or None."""
    area = (adzuna_result.get("location") or {}).get("area") or []
    if len(area) < 3:
        return None
    state = area[1]
    county = next((a for a in area if a.endswith("County")), None)
    return (state, county) if county else None


def cbsa_of(adzuna_result):
    """CBSA code for a posting, or None if its county is in no target CBSA."""
    key = county_of(adzuna_result)
    return _COUNTY_TO_CBSA.get(key) if key else None


def bucket_by_cbsa(results):
    """Split Adzuna results into {cbsa_code: [results]} plus a dropped list for
    postings outside every target CBSA (the geography filter)."""
    kept, dropped = {}, []
    for r in results:
        code = cbsa_of(r)
        if code is None:
            dropped.append(r)
        else:
            kept.setdefault(code, []).append(r)
    return kept, dropped


def _selftest():
    def res(*area):
        return {"location": {"area": list(area)}}

    franklin = res("US", "Ohio", "Franklin County", "Hilliard")
    knox = res("US", "Ohio", "Knox County", "Mount Vernon")  # outside CBSA
    assert county_of(franklin) == ("Ohio", "Franklin County")
    assert cbsa_of(franklin) == "18140"
    assert cbsa_of(knox) is None
    assert county_of(res("US", "Ohio")) is None            # too short
    assert county_of(res("US", "Ohio", "Columbus")) is None  # no 'County' entry

    kept, dropped = bucket_by_cbsa([franklin, knox, franklin])
    assert len(kept["18140"]) == 2 and len(dropped) == 1
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(f"{len(CBSA_COUNTIES)} CBSA(s) loaded; "
              f"{len(_COUNTY_TO_CBSA)} counties indexed.")
