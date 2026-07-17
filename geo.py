"""County <-> CBSA geography, loaded from the national OMB 2023 crosswalk
(cbsa_counties.csv, built by build_crosswalk.py). County is the exact join key:
Adzuna results report their county, a CBSA is a set of counties, and BLS series
key on the same. Keying by (state, county) disambiguates same-named counties
(Ohio's Knox County is in no MSA; Tennessee's is in Knoxville).

    python geo.py --selftest
"""

import csv
import sys
from pathlib import Path

CROSSWALK = Path(__file__).parent / "cbsa_counties.csv"
DEFAULT_RADIUS_KM = 50   # calibrated volume self-corrects, so one default is fine


def _load(path=CROSSWALK):
    """{cbsa_code: {name, state_fips, counties:{...}, radius_km, laus_lf_series}}
    plus a (state_name, county_name) -> cbsa_code reverse index."""
    if not path.exists():
        sys.exit(f"{path.name} missing — run: python build_crosswalk.py")
    cbsas, index = {}, {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            code = r["cbsa_code"]
            c = cbsas.setdefault(code, {
                "name": r["cbsa_title"], "state_fips": r["state_fips"],
                "counties": set(), "radius_km": DEFAULT_RADIUS_KM})
            c["counties"].add(r["county_name"])
            # primary state for the LAUS series = a Central county's state
            if r["central_outlying"] == "Central":
                c["state_fips"] = r["state_fips"]
            index[(r["state_name"], r["county_name"])] = code
    for code, c in cbsas.items():
        # LAUS labor-force series: LAUMT + state(2) + cbsa(5) + 00000006
        c["laus_lf_series"] = f"LAUMT{c['state_fips']}{code}00000006"
    return cbsas, index


CBSA_COUNTIES, _COUNTY_TO_CBSA = _load()


def county_of(adzuna_result):
    """(state, county) from an Adzuna result's location.area, or None.
    area looks like [US, Ohio, Franklin County, Hilliard]."""
    area = (adzuna_result.get("location") or {}).get("area") or []
    if len(area) < 3:
        return None
    county = next((a for a in area if a.endswith("County")), None)
    return (area[1], county) if county else None


def cbsa_of(adzuna_result):
    """CBSA code for a posting, or None if its county is in no MSA."""
    key = county_of(adzuna_result)
    return _COUNTY_TO_CBSA.get(key) if key else None


def bucket_by_cbsa(results):
    """{cbsa_code: [results]} plus a dropped list for postings outside every
    MSA (the geography filter)."""
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

    assert county_of(res("US", "Ohio", "Franklin County", "Hilliard")) == \
        ("Ohio", "Franklin County")
    assert cbsa_of(res("US", "Ohio", "Franklin County", "X")) == "18140"
    assert CBSA_COUNTIES["18140"]["name"] == "Columbus, OH"
    assert len(CBSA_COUNTIES["18140"]["counties"]) == 10
    assert CBSA_COUNTIES["18140"]["laus_lf_series"] == "LAUMT391814000000006"
    # Ohio's Knox County is in no MSA; same-named counties elsewhere are
    assert cbsa_of(res("US", "Ohio", "Knox County", "Mount Vernon")) is None
    assert cbsa_of(res("US", "Tennessee", "Knox County", "Knoxville")) is not None
    assert county_of(res("US", "Ohio")) is None
    print(f"selftest ok ({len(CBSA_COUNTIES)} MSAs loaded)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(f"{len(CBSA_COUNTIES)} MSAs, "
              f"{len(_COUNTY_TO_CBSA)} counties indexed.")
