"""BLS LAUS labor force (view 1 denominator). Uses the keyless v1 API (25
series/query, 25 queries/day) unless a free registration key is set in the
env var BLS_API_KEY, in which case it uses v2 (50 series/query, 500/day) —
national coverage (393 metros) needs the key. Get one at
https://data.bls.gov/registrationEngine/ .

    python pipeline/bls.py --selftest
"""

import os
import sys

import geo

API_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
API_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def latest_value(series_data):
    """First data point with a real value ('-' = not yet published). BLS returns
    newest first. Returns (value:int, label:str) or (None, None)."""
    for d in series_data:
        if d.get("value") not in (None, "-", ""):
            return int(d["value"]), f"{d['periodName']} {d['year']}"
    return None, None


def _cfg():
    """(endpoint, max series/query, extra payload) — v2 with the key, else v1."""
    key = os.environ.get("BLS_API_KEY")
    return (API_V2, 50, {"registrationkey": key}) if key else (API_V1, 25, {})


def labor_force(cbsa_code, start_year, end_year):
    """Latest published LAUS labor force for the CBSA. Network."""
    import requests
    url, _, extra = _cfg()
    sid = geo.CBSA_COUNTIES[cbsa_code]["laus_lf_series"]
    r = requests.post(url, json={"seriesid": [sid], "startyear": str(start_year),
                                 "endyear": str(end_year), **extra},
                      headers={"Content-Type": "application/json"}, timeout=30)
    r.raise_for_status()
    js = r.json()
    if js.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS: {js.get('status')} {js.get('message')}")
    series = js["Results"]["series"]
    value, label = latest_value(series[0]["data"] if series else [])
    return {"labor_force": value, "as_of": label, "series": sid}


def _parse_batch(resp_series, series_to_code):
    """Map a BLS batch response back to {cbsa_code: {labor_force, as_of, series}}."""
    out = {}
    for s in resp_series:
        code = series_to_code.get(s.get("seriesID"))
        if code:
            value, label = latest_value(s.get("data", []))
            out[code] = {"labor_force": value, "as_of": label,
                         "series": s.get("seriesID")}
    return out


def labor_force_batch(codes, start_year, end_year, pause=0.5):
    """Latest LAUS labor force for many CBSAs, batched to the endpoint's series
    limit. Set BLS_API_KEY for national coverage (v2: 50/query, 500/day);
    keyless v1 (25/query, 25/day) runs out well before 393 metros. Network."""
    import time

    import requests
    url, chunk, extra = _cfg()
    series_to_code = {geo.CBSA_COUNTIES[c]["laus_lf_series"]: c
                      for c in codes if c in geo.CBSA_COUNTIES}
    sids = list(series_to_code)
    out = {}
    for i in range(0, len(sids), chunk):
        batch = sids[i:i + chunk]
        for attempt in range(4):                       # retry transient BLS blips
            try:
                r = requests.post(url, json={"seriesid": batch,
                                             "startyear": str(start_year),
                                             "endyear": str(end_year), **extra},
                                  headers={"Content-Type": "application/json"},
                                  timeout=30)
                r.raise_for_status()
                js = r.json()
                if js.get("status") == "REQUEST_NOT_PROCESSED":   # daily cap
                    print("  BLS daily cap reached — set BLS_API_KEY "
                          "(data.bls.gov/registrationEngine) or retry after reset; "
                          f"keeping {len(out)} fetched this run.")
                    return out
                if js.get("status") != "REQUEST_SUCCEEDED":
                    raise RuntimeError(f"BLS: {js.get('status')} {js.get('message')}")
                out.update(_parse_batch(js["Results"]["series"], series_to_code))
                break
            except Exception as e:
                if attempt == 3:
                    print(f"  BLS chunk failed after retries ({e}); "
                          f"{len(batch)} metros will lack labor force")
                else:
                    time.sleep(2 ** attempt)
        if pause and i + chunk < len(sids):
            time.sleep(pause)
    return out


def _selftest():
    data = [{"year": "2025", "periodName": "December", "value": "-"},
            {"year": "2025", "periodName": "November", "value": "1181407"},
            {"year": "2025", "periodName": "October", "value": "1179000"}]
    assert latest_value(data) == (1181407, "November 2025")   # skips the '-'
    assert latest_value([]) == (None, None)

    # batch response maps back to the right CBSA and skips unknown series
    resp = [{"seriesID": "LAUMT391814000000006",
             "data": [{"year": "2025", "periodName": "November", "value": "1181407"}]},
            {"seriesID": "LAUMT_UNKNOWN", "data": []}]
    got = _parse_batch(resp, {"LAUMT391814000000006": "18140"})
    assert got == {"18140": {"labor_force": 1181407, "as_of": "November 2025",
                             "series": "LAUMT391814000000006"}}
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(labor_force("18140", 2024, 2025))
