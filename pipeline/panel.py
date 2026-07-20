"""The outliers panel — the point of the project. For each metro, get Adzuna's
posting COUNT per category (a census, not a ranked sample), turn it into a
category mix, pool a national baseline, and rank metro x category cells by how
far the metro's mix deviates from national. Template one sentence per top cell.

Why counts, not classified samples: Adzuna's unkeyworded search is ranked by a
few high-volume advertisers, so sampling+classifying gives a biased mix (one
Dallas hospital network made it read 94% healthcare). Category *counts* are
totals, immune to that ranking bias, and a category share (cat/total at the
same radius) cancels the CBSA radius imprecision too. Tradeoff: Adzuna's ~30
categories are not O*NET SOC — the SOC path returns when we have a
representative text source (NLx). This is the Phase 0 lesson applied: Adzuna is
a counting instrument, not a sampling one.

    ADZUNA_APP_ID=... ADZUNA_APP_KEY=... python pipeline/panel.py
    python pipeline/panel.py --selftest   # pooling + ranking logic, no network

Writes site/data/outliers.json.
"""

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import geo

# Fallback seed set (diverse large metros) if national.json isn't built yet.
METROS = ["35620", "31080", "16980", "19100", "26420", "12060", "41860",
          "42660", "19740", "33100"]
PER_RUN = 40            # metros to (re)collect per run; rolls across the country
                        # over ~ceil(universe/PER_RUN) runs. ~31 calls each, so
                        # this is the daily Adzuna budget knob (override: argv[1])
MIN_NAT_SHARE = 0.03    # focus on substantial sectors (>=3% of national postings)
MIN_CAT_COUNT = 50      # metro must have >=50 postings in the category
TOP_N = 12
PER_METRO_CAP = 2       # diversify the ranked list so it isn't one metro/category
PER_CATEGORY_CAP = 2
CALL_INTERVAL = 2.6     # seconds between calls: Adzuna free tier is ~25/min
SEARCH = "https://api.adzuna.com/v1/api/jobs/us/search/1"
CATS_URL = "https://api.adzuna.com/v1/api/jobs/us/categories"


def _count(app_id, app_key, where, distance, tag=None, tries=4):
    import requests
    p = {"app_id": app_id, "app_key": app_key, "where": where,
         "results_per_page": 1, "distance": distance}
    if tag:
        p["category"] = tag
    for attempt in range(tries):
        try:
            r = requests.get(SEARCH, params=p, timeout=30)
            if r.status_code in (429, 500, 502, 503, 504):  # transient
                raise requests.HTTPError(f"{r.status_code}")
            r.raise_for_status()
            return r.json().get("count", 0)
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)   # 1, 2, 4s backoff


def metro_mix(app_id, app_key, cbsa_code, categories):
    """{category_label: count} for one metro, over its CBSA radius."""
    d = geo.CBSA_COUNTIES[cbsa_code]
    where, dist = d["adzuna_where"], d["radius_km"]
    mix = {}
    for c in categories:
        mix[c["label"]] = _count(app_id, app_key, where, dist, c["tag"])
        time.sleep(CALL_INTERVAL)
    return mix


def pool_national(per_metro):
    """National category share = summed counts across metros / grand total.
    per_metro: {code: {'name':.., 'mix': {label: count}}}."""
    totals = {}
    for m in per_metro.values():
        for label, n in m["mix"].items():
            totals[label] = totals.get(label, 0) + n
    grand = sum(totals.values()) or 1
    return {label: n / grand for label, n in totals.items()}


def rank_outliers(per_metro, national_share):
    """Cells ranked by |log2(share_metro / share_national)| — a symmetric effect
    size ('2x national'). Counts are near-census, so a significance z would be
    astronomically large and meaningless; effect size is the right ranking."""
    cells = []
    for code, m in per_metro.items():
        mix = m["mix"]
        total = sum(mix.values())
        if total < MIN_CAT_COUNT * 4:
            continue
        for label, n in mix.items():
            share_nat = national_share.get(label, 0)
            if n < MIN_CAT_COUNT or share_nat < MIN_NAT_SHARE:
                continue
            share_m = n / total
            lr = math.log2(share_m / share_nat) if share_m > 0 else 0.0
            ratio = share_m / share_nat
            word = "over-represented" if ratio >= 1 else "under-represented"
            cells.append({
                "cbsa": code, "metro": m["name"], "category": label,
                "share_metro": round(share_m, 4), "share_national": round(share_nat, 4),
                "log2_ratio": round(lr, 2), "ratio": round(ratio, 2), "n": n,
                "sentence": (f"In {m['name']}, {label} is {share_m*100:.0f}% of "
                             f"postings vs {share_nat*100:.0f}% nationally — "
                             f"{ratio:.1f}x national, {word}."),
            })
    cells.sort(key=lambda c: -abs(c["log2_ratio"]))
    return cells


def per_metro_outliers(cells, top_n=4):
    """Group ranked cells by metro → {cbsa: {name, total, over, under}}, each
    metro's top-N over- and under-represented sectors (by |log2_ratio|). Feeds
    the national map's click-through side panel; reuses the cell dicts as-is.
    `cells` must be sorted by |log2_ratio| descending (as rank_outliers returns),
    so the first over/under per metro are already its strongest."""
    by = {}
    for c in cells:
        m = by.setdefault(c["cbsa"], {"name": c["metro"], "over": [], "under": []})
        side = "over" if c["ratio"] >= 1 else "under"
        if len(m[side]) < top_n:
            m[side].append(c)
    return by


def diversify(cells, per_metro=PER_METRO_CAP, per_category=PER_CATEGORY_CAP,
              top_n=TOP_N):
    """Greedily take the strongest deviations while capping how many cells any
    one metro or category contributes, so the list reads as distinct insights
    instead of e.g. seven Travel Jobs rows. cells must be sorted by |log2|."""
    picked, seen_m, seen_c = [], {}, {}
    for c in cells:
        if seen_m.get(c["cbsa"], 0) >= per_metro:
            continue
        if seen_c.get(c["category"], 0) >= per_category:
            continue
        picked.append(c)
        seen_m[c["cbsa"]] = seen_m.get(c["cbsa"], 0) + 1
        seen_c[c["category"]] = seen_c.get(c["category"], 0) + 1
        if len(picked) >= top_n:
            break
    return picked


def shaded_universe(fallback=METROS):
    """All measurable (shaded) metros from national.json — the coverage target
    for the rolling sector collection. Gray metros are radius-swamped by a
    neighbor, so their category *shares* would be the neighbor's; excluding them
    keeps each metro's mix its own. Falls back to the seed set (minus Puerto
    Rico) if national.json isn't built yet."""
    nat_path = Path(__file__).parent.parent / "site" / "data" / "national.json"
    if not nat_path.exists():
        return fallback
    return [m["cbsa"] for m in json.loads(nat_path.read_text())["metros"]
            if not m["below_threshold"]]


def stale_metros(cache, per_run=PER_RUN):
    """The per_run metros with the stalest sector data, so a run rolls coverage
    across the whole country within the Adzuna budget. Never-collected metros go
    first (highest priority); already-cached metros lacking a timestamp (pre-
    rolling data) go last so they aren't needlessly re-fetched."""
    def age(c):
        e = cache.get(c)
        if e is None:
            return ""                    # never collected -> first
        return e.get("fetched_at") or "9999"   # cached, no timestamp -> last
    return sorted(shaded_universe(), key=age)[:per_run]


def build_panel_report(per_metro):
    """Pure: {code:{name,mix,...}} -> the outliers.json report. Produces the
    national baseline, the two global diversified rankings (over/under, for
    sectors.html's two charts), and per-metro over/under (the map + metro
    detail). No network."""
    national = pool_national(per_metro)
    ranked = rank_outliers(per_metro, national)
    over = diversify([c for c in ranked if c["ratio"] >= 1])
    under = diversify([c for c in ranked if c["ratio"] < 1])
    # Lead = sharpest over-representation, for the page's hero reading.
    lead = over[0] if over else (ranked[0] if ranked else None)
    by_metro = per_metro_outliers(ranked)
    for code, m in by_metro.items():
        m["total"] = sum(per_metro[code]["mix"].values())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metros_sampled": len(per_metro),
        "national_total": sum(sum(m["mix"].values()) for m in per_metro.values()),
        "lead": lead,
        "basis": "Adzuna category posting counts (census per category)",
        "method": ("Category share = category count / metro total (same radius, "
                   "so CBSA-radius imprecision cancels). Ranked by "
                   "log2(metro share / national share) — effect size, since "
                   "near-census counts make a significance test meaningless. "
                   "Sentences templated from the numbers."),
        "national_share": [
            {"category": l, "share": round(s, 4)}
            for l, s in sorted(national.items(), key=lambda kv: -kv[1])],
        "by_metro": by_metro,
        "over_index": over,
        "under_index": under,
    }


def run():
    # metro names and templated sentences carry non-ASCII (em dash, accents);
    # Windows' cp1252 console/redirect would crash printing them.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        sys.exit("Set ADZUNA_APP_ID and ADZUNA_APP_KEY.")
    import requests
    for attempt in range(4):
        resp = requests.get(CATS_URL, params={"app_id": app_id, "app_key": app_key},
                            timeout=30)
        if resp.ok and resp.text.strip().startswith("{"):
            break
        if attempt == 3:
            sys.exit(f"Adzuna categories unavailable (HTTP {resp.status_code}); "
                     "likely the daily rate limit — retry after reset.")
        time.sleep(2 ** attempt)
    categories = resp.json()["results"]

    # Resumable cache: each metro's mix is saved as fetched, so a flaky API or an
    # exhausted daily budget doesn't lose completed metros — re-run to continue.
    OUT = Path(__file__).parent.parent / "site" / "data"
    OUT.mkdir(parents=True, exist_ok=True)
    cache_path = OUT / "_mix_cache.json"
    per_metro = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    per_run = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else PER_RUN
    targets = stale_metros(per_metro, per_run)
    for code in targets:
        if code not in geo.CBSA_COUNTIES:
            print(f"  skip {code}: not in crosswalk"); continue
        name = geo.CBSA_COUNTIES[code]["name"]
        try:
            mix = metro_mix(app_id, app_key, code, categories)
        except Exception as e:
            print(f"  {code} failed ({e}); writing panel from {len(per_metro)} metros")
            break
        per_metro[code] = {"name": name, "mix": mix,
                           "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        cache_path.write_text(json.dumps(per_metro))
        print(f"  {code} {name[:26]:26} total={sum(mix.values())}")

    # Report from the full accumulated cache (all metros collected so far), not
    # just this run's targets — coverage grows run over run.
    per_metro = {c: v for c, v in per_metro.items() if v.get("mix")}
    if len(per_metro) < 3:
        sys.exit(f"Only {len(per_metro)} metros — need >=3 for a national baseline.")
    report = build_panel_report(per_metro)
    (OUT / "outliers.json").write_text(json.dumps(report, indent=2))
    covered, universe = len(per_metro), len(shaded_universe())
    print(f"\nWrote {OUT/'outliers.json'} — {covered}/{universe} shaded metros covered, "
          f"{len(report['over_index'])} over + {len(report['under_index'])} under:")
    for c in report["over_index"][:5]:
        print("  over>", c["sentence"])


def _selftest():
    # Metro A skews tech, V skews hospitality; national is the pool.
    per_metro = {
        "A": {"name": "Metro A", "mix": {"IT Jobs": 300,
              "Healthcare & Nursing Jobs": 100, "Retail Jobs": 100}},
        "V": {"name": "Metro V", "mix": {"IT Jobs": 50,
              "Healthcare & Nursing Jobs": 100, "Hospitality & Catering Jobs": 350}},
    }
    nat = pool_national(per_metro)
    # grand total 1000; IT national = 350/1000
    assert abs(nat["IT Jobs"] - 350 / 1000) < 1e-9
    cells = rank_outliers(per_metro, nat)
    # ranked by |log2_ratio| descending
    mags = [abs(c["log2_ratio"]) for c in cells]
    assert mags == sorted(mags, reverse=True)
    # A's IT (0.60 vs 0.35) is over-represented; V's IT (0.10 vs 0.35) is under
    a_it = next(c for c in cells if c["cbsa"] == "A" and c["category"] == "IT Jobs")
    v_it = next(c for c in cells if c["cbsa"] == "V" and c["category"] == "IT Jobs")
    assert a_it["ratio"] > 1 and "over-represented" in a_it["sentence"]
    assert v_it["ratio"] < 1 and "under-represented" in v_it["sentence"]
    # floors respected
    assert all(c["n"] >= MIN_CAT_COUNT and c["share_national"] >= MIN_NAT_SHARE
               for c in cells)

    # diversify caps per-metro and per-category contributions
    fake = [{"cbsa": "M", "category": "C", "log2_ratio": 9},
            {"cbsa": "M", "category": "D", "log2_ratio": 8},
            {"cbsa": "M", "category": "E", "log2_ratio": 7},   # 3rd M -> dropped
            {"cbsa": "N", "category": "C", "log2_ratio": 6}]
    picked = diversify(fake, per_metro=2, per_category=2, top_n=10)
    assert [c["cbsa"] for c in picked] == ["M", "M", "N"]      # M capped at 2

    # per_metro_outliers: group cells into each metro's top over/under sectors
    by = per_metro_outliers(cells, top_n=2)
    assert "IT Jobs" in [c["category"] for c in by["A"]["over"]]    # A over-indexes IT
    assert "IT Jobs" in [c["category"] for c in by["V"]["under"]]   # V under-indexes IT
    assert all(len(m["over"]) <= 2 and len(m["under"]) <= 2 for m in by.values())

    # build_panel_report splits into two global indexes (the sectors.html charts)
    rep = build_panel_report(per_metro)
    assert {"over_index", "under_index", "by_metro"} <= rep.keys()
    assert all(c["ratio"] >= 1 for c in rep["over_index"])
    assert all(c["ratio"] < 1 for c in rep["under_index"])
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        run()
