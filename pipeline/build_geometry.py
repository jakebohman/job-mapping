"""One-time (rerun when the OMB delineation vintage changes): fetch the national
map geometry and vendor the mapping library, so the site has no external deps.

  site/data/us_metros.geojson   all ~393 Metropolitan Statistical Areas
  site/data/us_states.geojson   state outlines (light base under the metros)
  site/vendor/d3-array.min.js   d3-geo's dependency (load first)
  site/vendor/d3-geo.min.js     geoAlbersUsa + geoPath for the choropleth

Geometry comes from Census TIGERweb, server-simplified via ArcGIS
`maxAllowableOffset` so the files stay tiny.

    python pipeline/build_geometry.py
"""

import json
import urllib.request
from pathlib import Path

SITE = Path(__file__).parent.parent / "site"
TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
OFFSET = "0.02"        # ~2 km simplification; 393 MSAs -> ~210 KB
PRECISION = "3"
VENDOR = {
    "d3-array.min.js": "https://cdn.jsdelivr.net/npm/d3-array@3/dist/d3-array.min.js",
    "d3-geo.min.js": "https://cdn.jsdelivr.net/npm/d3-geo@3/dist/d3-geo.min.js",
}


def _signed_area(ring):
    return 0.5 * sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
                     for i in range(len(ring) - 1))


def _fix_rings(rings):
    """Wind rings for d3-geo: exterior CLOCKWISE, holes counterclockwise.
    d3-geo uses the opposite convention from RFC 7946 (its polygon interior is
    to the right of the ring), so RFC-7946 geometry — which is what TIGERweb
    emits — renders inverted, every polygon filling the whole map. Verified:
    a metro's CCW exterior spans 960x502; reversed to CW it renders 22x22."""
    out = []
    for j, ring in enumerate(rings):
        ccw = _signed_area(ring) > 0
        want_ccw = j != 0                 # exterior CW, holes CCW (d3 convention)
        out.append(ring[::-1] if ccw != want_ccw else ring)
    return out


def _rewind(js):
    for f in js["features"]:
        g = f["geometry"]
        if g["type"] == "Polygon":
            g["coordinates"] = _fix_rings(g["coordinates"])
        elif g["type"] == "MultiPolygon":
            g["coordinates"] = [_fix_rings(p) for p in g["coordinates"]]
    return js


def _fetch_geojson(service, layer, fields):
    url = (f"{TIGERWEB}/{service}/MapServer/{layer}/query?where=1%3D1"
           f"&outFields={fields}&returnGeometry=true&f=geojson&outSR=4326"
           f"&geometryPrecision={PRECISION}&maxAllowableOffset={OFFSET}")
    with urllib.request.urlopen(url, timeout=120) as r:
        js = json.load(r)
    if not js.get("features"):
        raise RuntimeError(f"No features from {service}/{layer}")
    return _rewind(js)


def main():
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    (SITE / "vendor").mkdir(parents=True, exist_ok=True)

    metros = _fetch_geojson("CBSA", 3, "GEOID,NAME")            # layer 3 = MSAs
    states = _fetch_geojson("State_County", 0, "GEOID,NAME")    # layer 0 = states
    for name, js in (("us_metros", metros), ("us_states", states)):
        path = SITE / "data" / f"{name}.geojson"
        path.write_text(json.dumps(js, separators=(",", ":")))
        print(f"  {path.relative_to(SITE.parent)}: "
              f"{len(js['features'])} features, {path.stat().st_size // 1024} KB")

    for name, url in VENDOR.items():
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        (SITE / "vendor" / name).write_bytes(data)
        print(f"  site/vendor/{name}: {len(data) // 1024} KB")


if __name__ == "__main__":
    main()
