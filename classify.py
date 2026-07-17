"""Occupation classification.

INTERIM CODER: uses the NIOSH NIOCCS autocoder (free, keyless GET) to map a
posting title to a SOC 2018 code. In PROJECT.md NIOCCS is the independent
*validator*; here it stands in as the primary coder until an LLM key exists.
When the LLM lands it becomes primary and NIOCCS returns to validation (the
circularity the design warns about only bites once both roles are filled).
Skills are NOT extracted here — that needs fuller text than Adzuna's 500 chars
(see risk 1).

    python classify.py --selftest      # no network
"""

import sys
import time

NIOCCS = "https://wwwn.cdc.gov/nioccs/IOCode"

SOC_MAJOR_TITLES = {
    "11": "Management", "13": "Business & Financial", "15": "Computer & Math",
    "17": "Architecture & Engineering", "19": "Life, Physical & Social Science",
    "21": "Community & Social Service", "23": "Legal", "25": "Education",
    "27": "Arts, Design, Entertainment & Media", "29": "Healthcare Practitioners",
    "31": "Healthcare Support", "33": "Protective Service",
    "35": "Food Preparation & Serving", "37": "Building & Grounds Cleaning",
    "39": "Personal Care & Service", "41": "Sales", "43": "Office & Admin Support",
    "45": "Farming, Fishing & Forestry", "47": "Construction & Extraction",
    "49": "Installation, Maintenance & Repair", "51": "Production",
    "53": "Transportation & Material Moving", "55": "Military",
}


def soc_major(soc_detailed):
    """'29-1141' -> '29'. Returns None for unrecognised input."""
    if not soc_detailed or "-" not in soc_detailed:
        return None
    major = soc_detailed.split("-", 1)[0]
    return major if major in SOC_MAJOR_TITLES else None


def code_title(title):
    """Call NIOCCS for one title. Returns (soc_detailed, probability) or
    (None, 0.0). Network — not exercised by the self-test."""
    import requests
    r = requests.get(NIOCCS, params={"o": title, "c": "0", "n": "1", "t": "json"},
                     timeout=30)
    if r.status_code != 200:
        return None, 0.0
    occ = (r.json().get("Occupation") or [{}])[0]
    return occ.get("Code"), float(occ.get("Probability") or 0.0)


def classify_sample(postings, coder=code_title, pause=0.2):
    """Classify Adzuna postings. Caches by title so duplicate titles cost one
    call. Returns list of {posting_id, title, soc_detailed, soc_major, prob}."""
    cache, out = {}, []
    for p in postings:
        title = (p.get("title") or "").strip()
        if title not in cache:
            cache[title] = coder(title) if title else (None, 0.0)
            if pause:
                time.sleep(pause)
        detailed, prob = cache[title]
        out.append({
            "posting_id": f"adzuna:{p.get('id')}",
            "title": title,
            "soc_detailed": detailed,
            "soc_major": soc_major(detailed),
            "prob": round(prob, 3),
        })
    return out


def _selftest():
    assert soc_major("29-1141") == "29"
    assert soc_major("15-1252") == "15"
    assert soc_major("99-9999") is None      # not a real major group
    assert soc_major("") is None and soc_major(None) is None

    # classify_sample with a stub coder — no network, verifies caching + shape
    calls = []
    def stub(title):
        calls.append(title)
        return {"Registered Nurse": ("29-1141", 1.0)}.get(title, (None, 0.0))
    posts = [{"id": 1, "title": "Registered Nurse"},
             {"id": 2, "title": "Registered Nurse"},   # cache hit
             {"id": 3, "title": "Unknownish Role"}]
    res = classify_sample(posts, coder=stub, pause=0)
    assert calls == ["Registered Nurse", "Unknownish Role"]   # deduped
    assert res[0] == {"posting_id": "adzuna:1", "title": "Registered Nurse",
                      "soc_detailed": "29-1141", "soc_major": "29", "prob": 1.0}
    assert res[2]["soc_major"] is None
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        sys.exit("classify.py has no live entrypoint; run via the pipeline.")
