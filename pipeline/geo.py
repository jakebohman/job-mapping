"""County <-> CBSA geography, loaded from the national OMB 2023 crosswalk
(cbsa_counties.csv, built by build_crosswalk.py). County is the exact join key:
Adzuna results report their county, a CBSA is a set of counties, and BLS series
key on the same. Keying by (state, county) disambiguates same-named counties
(Ohio's Knox County is in no MSA; Tennessee's is in Knoxville).

    python pipeline/geo.py --selftest
"""

import csv
import os
import re
import sys
from pathlib import Path


def _load_dotenv(path=None):
    """Load KEY=VALUE lines from the repo-root .env into os.environ (without
    overriding a real env var), so builds run without inline keys. .env is
    gitignored; kept dependency-free (no python-dotenv). Runs on `import geo`,
    which every key-using script does."""
    path = path or Path(__file__).parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip("'\""))


_load_dotenv()

CROSSWALK = Path(__file__).parent / "cbsa_counties.csv"
DEFAULT_RADIUS_KM = 50   # calibrated volume self-corrects, so one default is fine

# Connecticut replaced counties with planning regions in the 2022 OMB
# delineations, so the crosswalk keys CT on planning-region names — but Adzuna
# still reports the old county names, so a CT posting's county never matches and
# every CT metro reads f_m=0 (all gray). Alias the old counties to their
# dominant CBSA. ponytail: county granularity — old New Haven County splits
# between the New Haven and Waterbury CBSAs and is mapped to its dominant (New
# Haven), so Waterbury (47930) stays gray until a town-level split is worth it.
CT_COUNTY_CBSA = {
    "Fairfield County": "14860",    # Bridgeport-Stamford-Danbury
    "Hartford County": "25540",     # Hartford
    "Middlesex County": "25540",    # Hartford (Lower CT River Valley PR)
    "Tolland County": "25540",      # Hartford (Capitol PR)
    "New Haven County": "35300",    # New Haven (dominant; Waterbury towns split off below)
    "New London County": "35980",   # Norwich-New London
}

# The Waterbury-Shelton CBSA (47930) IS the Naugatuck Valley Planning Region, which
# is carved from THREE old counties (New Haven, Hartford, Litchfield), so no
# old-county alias can isolate it — it grayed out entirely. Adzuna reports the town
# in area[3], so match the region's 19 member municipalities by town instead, ahead
# of the old-county fallback. Source: US Census 2022 CT planning-region delineation
# (Naugatuck Valley Planning Region, FIPS 09110). Villages Adzuna names instead of
# their parent town (e.g. "Oakville" for Watertown) simply fall through — undercounts
# Waterbury slightly but never misattributes another metro's postings to it.
CT_TOWN_CBSA = {t: "47930" for t in (
    "Ansonia", "Bristol", "Derby", "Shelton", "Waterbury",        # cities
    "Beacon Falls", "Bethlehem", "Cheshire", "Middlebury", "Naugatuck",
    "Oxford", "Plymouth", "Prospect", "Seymour", "Southbury",
    "Thomaston", "Watertown", "Wolcott", "Woodbury",              # towns
)}

# BLS files a multi-state metro's total LAUS labor-force series under ONE state —
# the principal city's, i.e. the first state in the CBSA title ("Chicago-...,
# IL-IN" -> IL). Deriving the series' state prefix from an arbitrary constituent
# county 404s the series and the metro grays for want of a denominator. Map the
# title's leading state abbreviation to its FIPS.
STATE_ABBR_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56", "PR": "72",
}

# County-equivalents Adzuna/Census name with a non-"County" suffix: Louisiana
# parishes, Alaska boroughs/census areas/municipalities. Without these, every LA
# and AK posting fails the county->CBSA join and those metros read f_m=0 (gray).
COUNTY_SUFFIXES = ("County", "Parish", "Borough", "Census Area", "Municipality")


def _laus_series(state_fips, code):
    """LAUS labor-force series id: LAUMT + state(2) + cbsa(5) + 00000006."""
    return f"LAUMT{state_fips}{code}00000006"


def principal_place(cbsa_title):
    """A geocodable 'City, ST' Adzuna understands, from a CBSA title. Adzuna
    can't geocode compound titles like 'New York-Newark-Jersey City, NY-NJ' —
    take the first city and first state: -> 'New York, NY'."""
    city_part, _, state_part = cbsa_title.partition(",")
    city = re.split(r"[-/]", city_part)[0].strip()
    city = re.sub(r"^Urban\s+", "", city)   # "Urban Honolulu" -> "Honolulu" (won't geocode otherwise)
    city = re.sub(r"\s+Town$", "", city)    # New England "Amherst Town"/"Barnstable Town" -> bare city
    state = re.split(r"[-/]", state_part)[0].strip()
    return f"{city}, {state}" if state else city


def _saint_alias(county_name):
    """Adzuna spells out "Saint" where the OMB crosswalk abbreviates "St." (and
    vice versa), so a posting's county never joins ("St. Tammany Parish" in the
    crosswalk vs "Saint Tammany Parish" from Adzuna grayed out all of Slidell LA,
    whose only county is that parish). Return the opposite spelling to alias, or
    None."""
    if county_name.startswith("St. "):
        return "Saint " + county_name[4:]
    if county_name.startswith("Saint "):
        return "St. " + county_name[6:]
    return None


def _bare_county(county_name, state_name):
    """Adzuna reports some county-equivalents without their suffix ("Honolulu"
    not "Honolulu County", "Anchorage" not "Anchorage Municipality"). Return the
    bare form to alias, or None. The plain "County" strip is limited to Hawaii —
    stripping it nationwide would collide (e.g. Virginia's Richmond city vs
    Richmond County)."""
    for suf in (" Parish", " Borough", " Census Area", " Municipality", " Municipio"):
        if county_name.endswith(suf):
            return county_name[:-len(suf)]
    if state_name == "Hawaii" and county_name.endswith(" County"):
        return county_name[:-len(" County")]
    return None


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
                "counties": set(), "state_fips_all": set(),
                "radius_km": DEFAULT_RADIUS_KM,
                "central_county": None, "central_state": None})
            c["counties"].add(r["county_name"])
            c["state_fips_all"].add(r["state_fips"])
            # keep a representative Central county to disambiguate an ambiguous
            # Adzuna geocode (build_national's mis-geocode retry).
            if r["central_outlying"] == "Central" and c["central_county"] is None:
                c["central_county"] = r["county_name"]
                c["central_state"] = r["state_name"]
            index[(r["state_name"], r["county_name"])] = code
            bare = _bare_county(r["county_name"], r["state_name"])
            if bare:
                index[(r["state_name"], bare)] = code
            saint = _saint_alias(r["county_name"])   # "St." <-> "Saint" (Adzuna vs OMB)
            if saint:
                index[(r["state_name"], saint)] = code
    for code, c in cbsas.items():
        # LAUS series prefix = the principal (first-in-title) state; keep the
        # other constituent states as fallbacks (BLS occasionally files the total
        # under the second-named state, e.g. Davenport IA-IL -> IL).
        lead = re.split(r"[-/]", c["name"].split(",")[-1].strip())[0].strip()
        primary = STATE_ABBR_FIPS.get(lead, c["state_fips"])
        c["state_fips"] = primary
        c["laus_lf_series"] = _laus_series(primary, code)
        c["laus_lf_series_alts"] = [_laus_series(sf, code)
                                    for sf in sorted(c["state_fips_all"])
                                    if sf != primary]
        c["adzuna_where"] = principal_place(c["name"])
    for county, code in CT_COUNTY_CBSA.items():
        index[("Connecticut", county)] = code
    return cbsas, index


CBSA_COUNTIES, _COUNTY_TO_CBSA = _load()


def county_of(adzuna_result):
    """(state, county) from an Adzuna result's location.area, or None.
    area looks like [US, Ohio, Franklin County, Hilliard]."""
    area = (adzuna_result.get("location") or {}).get("area") or []
    if len(area) < 3:
        return None
    # county-equivalent is normally a suffixed element; non-contiguous places
    # (HI, AK) report it bare, where it sits in the third slot. The reverse-index
    # lookup in cbsa_of gates any wrong guess, so falling back to area[2] is safe.
    county = next((a for a in area if a.endswith(COUNTY_SUFFIXES)), None) or area[2]
    return (area[1], county)


def cbsa_of(adzuna_result):
    """CBSA code for a posting, or None if its county is in no MSA."""
    area = (adzuna_result.get("location") or {}).get("area") or []
    # CT: Adzuna reports OLD county names, which can't distinguish a planning region
    # carved from several old counties (Naugatuck Valley/Waterbury). Match town first.
    if len(area) >= 4 and area[1] == "Connecticut":
        code = CT_TOWN_CBSA.get(area[3])
        if code:
            return code
    key = county_of(adzuna_result)
    return _COUNTY_TO_CBSA.get(key) if key else None


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

    # Connecticut: Adzuna reports old county names but the crosswalk keys on
    # planning regions, so the CT alias must map them to their CBSA (else f_m=0).
    assert cbsa_of(res("US", "Connecticut", "Fairfield County", "Stamford")) == "14860"
    assert cbsa_of(res("US", "Connecticut", "New Haven County", "New Haven")) == "35300"
    # Naugatuck Valley (Waterbury 47930) is matched by TOWN, since its member towns
    # carry three different old-county tags from Adzuna; non-member towns are unchanged.
    assert len(CT_TOWN_CBSA) == 19 and set(CT_TOWN_CBSA.values()) == {"47930"}
    assert cbsa_of(res("US", "Connecticut", "New Haven County", "Waterbury")) == "47930"
    assert cbsa_of(res("US", "Connecticut", "Hartford County", "Bristol")) == "47930"    # old Hartford Co town
    assert cbsa_of(res("US", "Connecticut", "Fairfield County", "Shelton")) == "47930"   # old Fairfield Co town
    assert cbsa_of(res("US", "Connecticut", "New Haven County", "Wallingford")) == "35300"  # non-member -> New Haven
    # a representative Central county is exposed for the mis-geocode retry
    assert CBSA_COUNTIES["18140"]["central_county"] in CBSA_COUNTIES["18140"]["counties"]

    # Louisiana parishes (and AK boroughs) must join like counties, else f_m=0
    assert cbsa_of(res("US", "Louisiana", "Orleans Parish", "New Orleans")) == "35380"
    # Adzuna spells "Saint" where OMB abbreviates "St." — alias both (grayed Slidell)
    assert cbsa_of(res("US", "Louisiana", "Saint Tammany Parish", "Slidell")) == "43640"
    # Non-contiguous metros: Adzuna drops the suffix (bare "Honolulu"); the bare
    # alias + area[2] fallback recover them, and "Urban Honolulu" must geocode.
    assert principal_place("Urban Honolulu, HI") == "Honolulu, HI"
    # New England "... Town" places don't geocode on Adzuna; strip the suffix
    assert principal_place("Amherst Town-Northampton, MA") == "Amherst, MA"
    assert principal_place("Barnstable Town, MA") == "Barnstable, MA"
    assert cbsa_of(res("US", "Hawaii", "Honolulu", "Honolulu")) == "46520"

    # multi-state metro's LAUS series uses the principal (first-in-title) state,
    # with the other constituent states kept as fallbacks
    chi = CBSA_COUNTIES["16980"]                        # Chicago-Naperville-Elgin, IL-IN
    assert chi["laus_lf_series"].startswith("LAUMT17")  # IL, not IN
    assert any(s.startswith("LAUMT18") for s in chi["laus_lf_series_alts"])  # IN fallback
    assert CBSA_COUNTIES["47900"]["laus_lf_series"].startswith("LAUMT11")    # DC, not MD/VA

    # .env loader: loads + unquotes new keys, never overrides a real env var
    import tempfile
    p = Path(tempfile.gettempdir()) / "_jm_env_test.env"
    p.write_text('# comment\nJM_TEST_KEY = "hello"\nJM_EXISTING=fromfile\n')
    os.environ["JM_EXISTING"] = "real"
    _load_dotenv(p)
    assert os.environ["JM_TEST_KEY"] == "hello"
    assert os.environ["JM_EXISTING"] == "real"
    p.unlink()
    print(f"selftest ok ({len(CBSA_COUNTIES)} MSAs loaded)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(f"{len(CBSA_COUNTIES)} MSAs, "
              f"{len(_COUNTY_TO_CBSA)} counties indexed.")
