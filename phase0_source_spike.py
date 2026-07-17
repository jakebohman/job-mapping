"""Phase 0 source spike — measure whether Adzuna + CareerOneStop can back the
counts-first design in PROJECT.md, for ONE metro, before any pipeline exists.

Exit criterion (from PROJECT.md): decide the Adzuna/CareerOneStop split for
counts vs sample text, WITH NUMBERS. This script produces those numbers.

Throwaway by design — output lands in spike_results/ (gitignored). Run it on
two different days to fill in the cross-day duplicate rate.

    pip install requests
    cp .env.example .env   # fill in keys
    python phase0_source_spike.py            # live run (needs keys)
    python phase0_source_spike.py --selftest # verify analysis logic, no keys

Measures:
  1. Adzuna posting volume for the metro (the `count` field).
  2. count-field stability across identical repeated queries.
  3. Description truncation length + ellipsis rate on pulled details.
  4. Remote-detectability from the (truncated) Adzuna text.
  5. Cross-day duplicate rate (compares against the previous run's ids).
  6. CareerOneStop text length vs Adzuna, and observed rate-limit behavior.
"""

import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

# ponytail: Columbus OH is the single spike metro from PROJECT.md Phase 0.
METRO = {"cbsa": "18140", "adzuna_where": "Columbus, Ohio",
         "cos_location": "Columbus, OH"}
SPIKE_DIR = Path(__file__).parent / "spike_results"
STABILITY_REPEATS = 5          # identical count queries to gauge jitter
DETAIL_SAMPLE = 50             # postings pulled for truncation/remote analysis
REMOTE_RE = re.compile(r"\b(remote|work from home|wfh|telecommut|telework)\b", re.I)


# ---- pure analysis (unit-testable without network) --------------------------

def count_stability(counts):
    """Given repeated identical-query counts, summarize jitter."""
    if not counts:
        return {"n": 0}
    lo, hi = min(counts), max(counts)
    mean = sum(counts) / len(counts)
    spread = (hi - lo) / mean if mean else 0.0
    return {"n": len(counts), "min": lo, "max": hi, "mean": round(mean, 1),
            "relative_spread": round(spread, 4), "values": counts}


def analyze_descriptions(texts):
    """Length distribution + truncation/remote signals over description texts."""
    lengths = sorted(len(t or "") for t in texts)
    n = len(lengths)
    if n == 0:
        return {"n": 0}
    ellipsis = sum(1 for t in texts if (t or "").rstrip().endswith(("…", "...")))
    remote = sum(1 for t in texts if REMOTE_RE.search(t or ""))
    return {
        "n": n,
        "len_min": lengths[0],
        "len_median": lengths[n // 2],
        "len_max": lengths[-1],
        "ellipsis_rate": round(ellipsis / n, 3),   # truncation smoking gun
        "remote_signal_rate": round(remote / n, 3),
    }


def duplicate_rate(today_ids, prior_ids):
    """Share of today's ids also seen in the prior run (cross-day churn)."""
    today, prior = set(today_ids), set(prior_ids)
    if not today or not prior:
        return {"today": len(today), "prior": len(prior), "overlap_rate": None}
    overlap = len(today & prior)
    return {"today": len(today), "prior": len(prior),
            "overlap": overlap, "overlap_rate": round(overlap / len(today), 3)}


# ---- network calls ----------------------------------------------------------

def _get(url, params=None, headers=None):
    import requests
    t0 = time.monotonic()
    r = requests.get(url, params=params, headers=headers, timeout=30)
    dt = time.monotonic() - t0
    return r.status_code, dt, r


def adzuna_count(app_id, app_key, where):
    url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    params = {"app_id": app_id, "app_key": app_key, "where": where,
              "results_per_page": 1}
    status, _, r = _get(url, params)
    if status != 200:
        raise RuntimeError(f"Adzuna count {status}: {r.text[:200]}")
    return r.json().get("count")


def adzuna_details(app_id, app_key, where, want):
    """Pull up to `want` postings' title/description/id/redirect flag."""
    url_tmpl = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"
    out, page = [], 1
    while len(out) < want and page <= 10:
        params = {"app_id": app_id, "app_key": app_key, "where": where,
                  "results_per_page": 50, "page": page}
        status, _, r = _get(url_tmpl.format(page=page), params)
        if status != 200:
            raise RuntimeError(f"Adzuna details {status}: {r.text[:200]}")
        results = r.json().get("results", [])
        if not results:
            break
        for j in results:
            out.append({"id": str(j.get("id")),
                        "title": j.get("title", ""),
                        "description": j.get("description", "")})
        page += 1
    return out[:want]


def careeronestop_sample(user_id, token, keyword, location, want):
    """CareerOneStop Job Search. Param order is verified BY this spike — if the
    call 404s, the printed URL tells us what to fix."""
    url = (f"https://api.careeronestop.org/v1/jobsearch/{user_id}/"
           f"{keyword}/{location}/25/0/0/0/{want}/10")
    headers = {"Authorization": f"Bearer {token}"}
    status, dt, r = _get(url, headers=headers)
    if status != 200:
        return {"status": status, "seconds": round(dt, 2),
                "note": r.text[:200], "url": url}
    jobs = r.json().get("Jobs", []) or []
    texts = [j.get("JobDescription", "") for j in jobs]
    return {"status": status, "seconds": round(dt, 2), "returned": len(jobs),
            "text": analyze_descriptions(texts)}


# ---- orchestration ----------------------------------------------------------

def _prior_ids():
    runs = sorted(SPIKE_DIR.glob("spike_*.json"))
    if not runs:
        return []
    try:
        return json.loads(runs[-1].read_text()).get("adzuna", {}).get("detail_ids", [])
    except Exception:
        return []


def run_live():
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    cos_user = os.environ.get("CAREERONESTOP_USERID")
    cos_token = os.environ.get("CAREERONESTOP_TOKEN")
    if not (app_id and app_key):
        sys.exit("Set ADZUNA_APP_ID and ADZUNA_APP_KEY (see .env.example).")

    prior = _prior_ids()
    report = {"metro": METRO, "run_at": datetime.now(timezone.utc).isoformat()}

    print(f"[adzuna] {STABILITY_REPEATS}x count for {METRO['adzuna_where']} ...")
    counts = []
    for _ in range(STABILITY_REPEATS):
        counts.append(adzuna_count(app_id, app_key, METRO["adzuna_where"]))
        time.sleep(1)
    report["adzuna_stability"] = count_stability(counts)

    print(f"[adzuna] pulling {DETAIL_SAMPLE} details ...")
    details = adzuna_details(app_id, app_key, METRO["adzuna_where"], DETAIL_SAMPLE)
    report["adzuna"] = {
        "descriptions": analyze_descriptions([d["description"] for d in details]),
        "detail_ids": [d["id"] for d in details],
    }
    report["cross_day"] = duplicate_rate([d["id"] for d in details], prior)

    if cos_user and cos_token:
        print("[careeronestop] sampling ...")
        report["careeronestop"] = careeronestop_sample(
            cos_user, cos_token, "software", METRO["cos_location"], DETAIL_SAMPLE)
    else:
        report["careeronestop"] = {"skipped": "no CAREERONESTOP_* keys"}

    SPIKE_DIR.mkdir(exist_ok=True)
    out = SPIKE_DIR / f"spike_{date.today().isoformat()}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out}\n")
    print(json.dumps({k: report[k] for k in
                      ("adzuna_stability", "cross_day") if k in report}, indent=2))
    print("adzuna descriptions:", json.dumps(report["adzuna"]["descriptions"]))
    print("careeronestop:", json.dumps(report["careeronestop"]))


def selftest():
    assert count_stability([100, 100, 100])["relative_spread"] == 0.0
    assert count_stability([90, 110])["relative_spread"] == 0.2
    assert count_stability([])["n"] == 0

    d = analyze_descriptions(["short", "a much longer body here", "ends here…"])
    assert d["n"] == 3 and d["len_min"] == 5
    assert d["ellipsis_rate"] == round(1 / 3, 3)

    r = analyze_descriptions(["Fully remote role", "onsite only", "WFH friendly"])
    assert r["remote_signal_rate"] == round(2 / 3, 3)

    dup = duplicate_rate(["a", "b", "c", "d"], ["c", "d", "e"])
    assert dup["overlap"] == 2 and dup["overlap_rate"] == 0.5
    assert duplicate_rate(["a"], [])["overlap_rate"] is None
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        run_live()
