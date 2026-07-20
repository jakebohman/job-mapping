"""One-command reproducible build: clone, put keys in .env, run this, watch the
map fill. Thin orchestrator over the existing (resumable, self-caching) scripts:

    check keys -> build_geometry (if absent) -> build_national -> panel (loop)

Each underlying script caches every item to site/data/_*_cache.json and throttles
to the Adzuna free tier, so this stays thin and every re-run is cheap/idempotent:
it resumes where the last one stopped. On the free tier a full populate spans a
few days (national ~387 calls; sector ~308 metros x 31 ~= 9,500 calls) — one run
does a budget's worth and stops gracefully; the committed site/data/*.json renders
in the meantime. Caches are gitignored, so a fresh clone re-fetches (that is what
makes the data fresh).

    python pipeline/build_all.py           # one budget's worth, then stop
    python pipeline/build_all.py --loop     # unattended: sleep + retry across days
    python pipeline/build_all.py --serve    # serve site/ on http://localhost:8000 when done
    python pipeline/build_all.py --selftest # coverage/keys logic, no network

.env is auto-loaded via `import geo`; subprocesses inherit os.environ.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import geo      # noqa: F401  (side effect: loads .env into os.environ)
import panel    # reuse shaded_universe() so "covered" matches what panel fills

import os

PIPELINE = Path(__file__).parent
SITE = PIPELINE.parent / "site"
DATA = SITE / "data"
REQUIRED_KEYS = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "BLS_API_KEY")
GEOMETRY_OUTPUTS = ("us_metros.geojson", "us_states.geojson")
GEOMETRY_VENDOR = ("d3-array.min.js", "d3-geo.min.js")
SLEEP_SECONDS = 3600    # ponytail: --loop retries hourly; the Adzuna daily cap
                        # resets once/day so most retries are a cheap no-op that
                        # resumes the moment the cap clears. Bump if you want to
                        # spend fewer wasted first-calls while capped.


def missing_keys(env):
    """Required keys that are unset or empty — named so the user can fix .env."""
    return [k for k in REQUIRED_KEYS if not env.get(k)]


def geometry_present():
    """True if build_geometry already produced its outputs (it's a one-time,
    keyless step; skip it when the shapes + vendored d3 are already there)."""
    return (all((DATA / f).exists() for f in GEOMETRY_OUTPUTS)
            and all((SITE / "vendor" / f).exists() for f in GEOMETRY_VENDOR))


def national_status():
    """(covered, total, complete) from national.json, or None if not built yet.
    complete = every non-excluded metro measured (build_national skips PR and
    caches each metro, so covered==total means the national pass is done)."""
    p = DATA / "national.json"
    if not p.exists():
        return None
    r = json.loads(p.read_text())
    covered, total = r.get("metros_covered", 0), r.get("metros_total", 0)
    shaded = sum(1 for m in r["metros"] if not m["below_threshold"])
    return covered, total, shaded, covered >= total > 0


def sector_covered(universe):
    """How many of the shaded `universe` metros have sector data collected. Reads
    panel's mix cache directly — the same source panel fills — so this tracks
    real progress even mid-fill."""
    p = DATA / "_mix_cache.json"
    cache = json.loads(p.read_text()) if p.exists() else {}
    return sum(1 for c in universe if cache.get(c, {}).get("mix"))


def run_step(script, *args):
    """Run one pipeline script as a subprocess, streaming its output live (so the
    user watches the map fill). Returns the exit code. cwd=repo root, same
    interpreter; the script's own dir goes on sys.path so its sibling imports
    resolve, exactly like `python pipeline/<script>` from the root."""
    cmd = [sys.executable, str(PIPELINE / script), *args]
    print(f"\n$ {' '.join(cmd[1:])}", flush=True)
    return subprocess.run(cmd, cwd=str(PIPELINE.parent)).returncode


def fill_sectors():
    """Run panel repeatedly until every shaded metro has sector data, or until a
    pass stops making progress (Adzuna daily cap / error). panel rolls the
    PER_RUN stalest metros each pass, so successive passes cover the country."""
    universe = panel.shaded_universe()
    if not universe:
        print("No shaded metros yet — build national first."); return
    target = len(universe)
    while True:
        before = sector_covered(universe)
        if before >= target:
            print(f"\nSector data complete: {before}/{target} shaded metros."); return
        rc = run_step("panel.py", str(panel.PER_RUN))
        after = sector_covered(universe)
        print(f"  sector coverage: {after}/{target} shaded metros", flush=True)
        if after >= target:
            print("Sector data complete."); return
        if rc != 0 or after == before:
            # non-zero exit or no new metros => Adzuna cap or a persistent error.
            print(f"\nStopped at {after}/{target} sector metros "
                  "(likely the Adzuna daily cap) — re-run to continue.")
            return


def cycle():
    """One full pass: geometry (if needed) -> national (resumable, one pass) ->
    panel loop. Returns True if everything is fully populated."""
    if not geometry_present():
        if run_step("build_geometry.py") != 0:
            sys.exit("build_geometry failed — cannot continue.")
    else:
        print("Geometry already built (skipping).")

    run_step("build_national.py")
    nat = national_status()
    if nat:
        covered, total, shaded, done = nat
        print(f"  national: {covered}/{total} metros measured, {shaded} shaded"
              + ("" if done else " (incomplete — re-run to continue)"))

    fill_sectors()

    nat = national_status()
    universe = panel.shaded_universe()
    return bool(nat and nat[3]) and sector_covered(universe) >= len(universe)


def run(argv):
    loop = "--loop" in argv
    serve = "--serve" in argv

    missing = missing_keys(os.environ)
    if missing:
        sys.exit("Missing required key(s): " + ", ".join(missing)
                 + ".\nSet them in a .env at the repo root (copy .env.example) "
                 "or export them, then re-run.")

    while True:
        complete = cycle()
        if complete:
            print("\nAll data populated. site/ renders the fully-shaded map.")
            break
        if not loop:
            print("\nDid a budget's worth. Re-run to continue "
                  "(caches resume where this stopped).")
            break
        print(f"\n--loop: sleeping {SLEEP_SECONDS//60} min, then continuing ...",
              flush=True)
        time.sleep(SLEEP_SECONDS)

    if serve:
        print("\nServing site/ at http://localhost:8000  (Ctrl-C to stop)")
        subprocess.run([sys.executable, "-m", "http.server", "8000"],
                       cwd=str(SITE))


def _selftest():
    # missing_keys names only unset/empty required keys.
    full = {"ADZUNA_APP_ID": "a", "ADZUNA_APP_KEY": "b", "BLS_API_KEY": "c"}
    assert missing_keys(full) == []
    assert missing_keys({"ADZUNA_APP_ID": "a", "ADZUNA_APP_KEY": ""}) == \
        ["ADZUNA_APP_KEY", "BLS_API_KEY"]
    assert missing_keys({}) == list(REQUIRED_KEYS)

    # sector_covered counts only shaded-universe metros that have a mix.
    global DATA
    import tempfile
    saved = DATA
    DATA = Path(tempfile.mkdtemp())
    (DATA / "_mix_cache.json").write_text(json.dumps({
        "A": {"mix": {"IT Jobs": 5}},      # shaded + has mix -> counts
        "B": {"mix": {}},                  # empty mix -> no
        "C": {"mix": {"X": 1}},            # has mix but not in universe -> no
    }))
    assert sector_covered(["A", "B", "D"]) == 1   # A only (B empty, D absent)
    assert sector_covered([]) == 0
    DATA = saved

    # national_status: None when the file is absent.
    DATA = Path(tempfile.mkdtemp())
    assert national_status() is None
    (DATA / "national.json").write_text(json.dumps({
        "metros_covered": 2, "metros_total": 2,
        "metros": [{"below_threshold": False}, {"below_threshold": True}]}))
    assert national_status() == (2, 2, 1, True)
    (DATA / "national.json").write_text(json.dumps({
        "metros_covered": 1, "metros_total": 2, "metros": []}))
    assert national_status() == (1, 2, 0, False)   # incomplete
    DATA = saved
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        run(sys.argv[1:])
