"""One-time: download the OMB 2023 delineation file and emit cbsa_counties.csv
(the national county <-> CBSA crosswalk geo.py loads). Metropolitan Statistical
Areas only (~387), matching the design and the TIGERweb MSA geometry layer.

xlsx is a zip of XML, so we parse it with the stdlib — no pandas/openpyxl.

    python pipeline/build_crosswalk.py     # writes pipeline/cbsa_counties.csv
"""

import csv
import io
import re
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

URL = ("https://www2.census.gov/programs-surveys/metro-micro/geographies/"
       "reference-files/2023/delineation-files/list1_2023.xlsx")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
# Column layout of list1_2023: A CBSA code, D CBSA title, E type,
# H county, I state name, J state FIPS, K county FIPS, L central/outlying.
COLS = {"A": "cbsa_code", "D": "cbsa_title", "E": "type", "H": "county_name",
        "I": "state_name", "J": "state_fips", "K": "county_fips",
        "L": "central_outlying"}


def _cells(xlsx_bytes):
    """Yield rows as {col_letter: text} from the first worksheet."""
    z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    shared = [(si.find(f"{NS}t").text if si.find(f"{NS}t") is not None else
               "".join(t.text or "" for t in si.iter(f"{NS}t")))
              for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    for row in sheet.iter(f"{NS}row"):
        out = {}
        for c in row.iter(f"{NS}c"):
            col = re.match(r"[A-Z]+", c.get("r")).group()
            v = c.find(f"{NS}v")
            if v is None or v.text is None:
                continue
            out[col] = shared[int(v.text)] if c.get("t") == "s" else v.text
        yield out


def build(url=URL, out_path=Path(__file__).parent / "cbsa_counties.csv"):
    data = urllib.request.urlopen(url, timeout=60).read()
    rows = []
    for cells in _cells(data):
        r = {name: cells.get(col, "").strip() for col, name in COLS.items()}
        if re.fullmatch(r"\d{5}", r["cbsa_code"] or "") and \
                r["type"] == "Metropolitan Statistical Area":
            rows.append(r)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[c for c in COLS.values() if c != "type"])
        w.writeheader()
        for r in rows:
            r.pop("type")
            w.writerow(r)
    cbsas = {r["cbsa_code"] for r in rows}
    print(f"Wrote {out_path}: {len(rows)} county rows across {len(cbsas)} MSAs")
    return rows


if __name__ == "__main__":
    build()
