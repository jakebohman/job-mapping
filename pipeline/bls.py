"""BLS LAUS labor force (view 1 denominator). Keyless v1 API — fine for one
metro; national rollout registers a key (v2, 500 series/query) and pins one
release vintage per PROJECT.md.

    python pipeline/bls.py --selftest
"""

import sys

import geo

API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"


def latest_value(series_data):
    """First data point with a real value ('-' = not yet published). BLS returns
    newest first. Returns (value:int, label:str) or (None, None)."""
    for d in series_data:
        if d.get("value") not in (None, "-", ""):
            return int(d["value"]), f"{d['periodName']} {d['year']}"
    return None, None


def labor_force(cbsa_code, start_year, end_year):
    """Latest published LAUS labor force for the CBSA. Network."""
    import requests
    sid = geo.CBSA_COUNTIES[cbsa_code]["laus_lf_series"]
    r = requests.post(API, json={"seriesid": [sid], "startyear": str(start_year),
                                 "endyear": str(end_year)},
                      headers={"Content-Type": "application/json"}, timeout=30)
    r.raise_for_status()
    js = r.json()
    if js.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS: {js.get('status')} {js.get('message')}")
    series = js["Results"]["series"]
    value, label = latest_value(series[0]["data"] if series else [])
    return {"labor_force": value, "as_of": label, "series": sid}


def _selftest():
    data = [{"year": "2025", "periodName": "December", "value": "-"},
            {"year": "2025", "periodName": "November", "value": "1181407"},
            {"year": "2025", "periodName": "October", "value": "1179000"}]
    assert latest_value(data) == (1181407, "November 2025")   # skips the '-'
    assert latest_value([]) == (None, None)
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(labor_force("18140", 2024, 2025))
