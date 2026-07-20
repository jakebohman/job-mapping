"""Adzuna request helpers for the national build (see CLAUDE.md for the
calibration ideas).

  _get()            — one Adzuna search request, raw JSON.
  dedupe_semantic() — collapse near-identical reposts by (title, employer).

`build_national.py` uses both to turn a metro's radius search into a
repost-corrected in-CBSA count.

    python pipeline/ingest.py --selftest   # no network
"""

import re
import sys

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


def _norm_title(t):
    t = re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())
    t = re.sub(r"\b(now hiring|hiring|urgent|apply now|immediately)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def dedupe_semantic(results):
    """Collapse near-identical reposts by (normalized title, employer). Adzuna
    (an aggregator) is flooded with bulk reposts that carry distinct ids, so
    id-dedup alone leaves ~60% duplicates (measured, Columbus). ponytail: same
    title+employer is treated as one posting — this can merge genuine
    multi-site openings, so it is a lower bound on distinct demand; the raw
    count is the upper bound. Truth is between; NLx's cleaner feed narrows it."""
    seen, out = set(), []
    for r in results:
        key = (_norm_title(r.get("title")),
               (r.get("company") or {}).get("display_name", ""))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _selftest():
    assert _norm_title("Nurse!! (Now Hiring)") == "nurse"   # punctuation + filler stripped
    # same normalized title + employer collapses; a different employer stays.
    a = {"id": 1, "title": "CDL A Driver - Now Hiring", "company": {"display_name": "Acme"}}
    a2 = {"id": 9, "title": "CDL A Driver", "company": {"display_name": "Acme"}}
    a3 = {"id": 10, "title": "CDL A Driver", "company": {"display_name": "Other Co"}}
    assert len(dedupe_semantic([a, a2, a3])) == 2
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        sys.exit("ingest.py has no live entrypoint; run via the pipeline.")
