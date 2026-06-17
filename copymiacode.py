"""
Fetch StreamStats basin characteristics, precipitation, and discharge for USGS
gauged monitoring sites.

For each site code the script collects:
  - NWIS site info (name, coordinates, HUC)
  - StreamStats watershed delineation + basin characteristics
  - total basin precipitation over a date range (PRISM 800m, area-weighted)
  - instantaneous discharge

Outputs (all under ./data/ next to this script):
  data/basin_characteristics.csv   — one row per site, info + characteristics + total precip
  data/discharge/{site}.csv        — one file per site, de-duplicated readings
  data/prism/us_800m_ppt_*.zip     — cached daily PRISM grids
"""

import copy
import csv
import os
import time

import requests

# ── API endpoints ──────────────────────────────────────────────────────────────
NWIS_SITE_URL     = "https://waterservices.usgs.gov/nwis/site/"                          # site information: name + coordinates
NWIS_IV_URL       = "https://waterservices.usgs.gov/nwis/iv/"                            # instantaneous streamflow data
PRISM_URL         = "https://services.nacse.org/prism/data/get/us/800m/ppt"             # daily precipitation gridded data
SS_DELINEATE_URL  = "https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/{region}"  # watershed delineation
SS_BASIN_CHAR_URL = "https://streamstats.usgs.gov/ss-hydro/v1/basin-characteristics/calculate"  # basin characteristics

# ── Data directories (relative to this script) ───────────────────────────────────
DATA_DIR        = os.makedirs(d := os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), exist_ok=True) or d
PRISM_DIR       = os.path.join(DATA_DIR, "prism")
DISCHARGE_DIR   = os.path.join(DATA_DIR, "discharge")
BASIN_CHAR_CSV  = os.path.join(DATA_DIR, "basin_characteristics.csv")

# ── Useful globals ──────────────────────────────────────────────────────────────

# Find site codes using this map: https://apps.usgs.gov/nwismapper/
SITE_CODES = [
    "02138500",  # LINVILLE RIVER NEAR NEBO, NC
    "02137727",  # CATAWBA R NR PLEASANT GARDENS, NC
]

# Specify codes to fetch only what you need (faster).
# Pass char_codes=None to fetch everything available for the region.
CHAR_CODES = [
    "BSLDEM30FT",  # Mean basin slope (%)
    "DRNAREA",     # Drainage area (sq mi)
    "ELEV",        # Mean basin elevation (ft)
    "ELEVMAX",     # Maximum elevation (ft)
    "LC11BARE",    # Bare soil, NLCD 2011 (%)
    "LC11CRPHAY",  # Cultivated crops and hay, NLCD 2011 (%)
    "LC11FOREST",  # Forest cover, NLCD 2011 (%)
    "LC11DEV",     # Developed/urban land, NLCD 2011 (%)
    "LC11GRASS",   # Grassland, NLCD 2011 (%)
    "LC11IMP",     # Impervious surface, NLCD 2011 (%)
    "LC11SHRUB",   # Shrubland, NLCD 2011 (%)
    "LC11WATER",   # Open water, NLCD 2011 (%)
    "LC11WETLND",  # Wetlands, NLCD 2011 (%)
    "SSURGOA",     # Percent of watershed area covered by hydric soils, from SSURGO database (%)
    "SSURGOB",     # Percent of watershed area covered by hydric soils, from SSURGO database, buffered to 100m around streams (%)
    "SSURGOC",     # Percent of watershed area covered by hydric soils, from SSURGO database, buffered to 500m around streams (%)
    "SSURGOD",     # Percent of watershed area covered by hydric soils, from SSURGO database, buffered to 1000m around streams (%)
]

PRECIP_START = DISCHARGE_START = "2020-05-05"
PRECIP_END   = DISCHARGE_END   = "2026-05-05"


# ── Step 1: look up lat/lon/state from a USGS site code ───────────────────────
def get_site_info(site_code: str) -> dict:
    """
    Returns {'site_code', 'site_name', 'lat', 'lon', 'state', 'huc'} for a USGS gauge.
    Raises ValueError if the site is not found.
    """
    params = {
        "format":     "rdb",
        "sites":      site_code,
        "siteOutput": "expanded",
    }
    r = requests.get(NWIS_SITE_URL, params=params, timeout=30)
    r.raise_for_status()

    # RDB format: comment lines (#), header, format spec, data rows
    lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
    if len(lines) < 3:
        raise ValueError(f"Site {site_code} not found in NWIS")

    headers = lines[0].split("\t")
    values  = lines[2].split("\t")
    row     = dict(zip(headers, values))

    return {
        "site_code": site_code,
        "site_name": row.get("station_nm", ""),
        "lat":       float(row["dec_lat_va"]),
        "lon":       float(row["dec_long_va"]),
        "state":     row.get("state_cd", ""),
        "huc":       row.get("huc_cd", ""),
    }


# ── Discharge: fetch instantaneous measurements ───────────────────────────────
def get_discharge(site_code: str, start: str | None = None, end: str | None = None) -> dict:
    """
    Fetches instantaneous discharge (ft³/s) for a continuously monitored USGS site.
    Parameter code 00060 = streamflow in ft³/s.

    start / end: ISO 8601 strings, e.g. '2024-01-01' or '2024-01-01T06:00'.
                 If omitted, NWIS returns the last 120 minutes of data.
    """
    params = {
        "format":      "json",
        "sites":       site_code,
        "parameterCd": "00060",
        "siteStatus":  "active",
    }
    if start:
        params["startDT"] = start
    if end:
        params["endDT"] = end

    r = requests.get(NWIS_IV_URL, params=params, timeout=30)
    r.raise_for_status()

    series = r.json()["value"]["timeSeries"]
    if not series:
        raise ValueError(f"No discharge data found for site {site_code}")

    ts = series[0]

    geo     = ts["sourceInfo"]["geoLocation"]["geogLocation"]
    var     = ts["variable"]
    methods = {m["methodID"]: m["methodDescription"] for m in ts["values"][0].get("method", [])}
    ql_map  = {
        q["qualityControlLevelCode"]: q["qualityControlLevelDescription"]
        for q in ts["values"][0].get("qualityControlLevel", [])
    }

    no_data  = var["noDataValue"]
    readings = []
    for v in ts["values"][0]["value"]:
        raw = float(v["value"])
        if raw == no_data:
            continue
        qualifiers = v.get("qualifiers", [])
        readings.append({
            "datetime":      v["dateTime"],
            "discharge_cfs": raw,
            "qualifiers":    qualifiers,
            "quality_level": ql_map.get(qualifiers[0], "") if qualifiers else "",
            "method":        next(iter(methods.values()), ""),
        })

    return {
        "site_code":     site_code,
        "site_name":     ts["sourceInfo"]["siteName"],
        "lat":           geo["latitude"],
        "lon":           geo["longitude"],
        "variable":      var["variableName"],
        "unit":          var["unit"]["unitCode"],
        "no_data_value": no_data,
        "readings":      readings,
    }


def save_discharge(site_code: str, start: str, end: str):
    """
    Fetch discharge for one site and write it to data/discharge/{site_code}.csv,
    merging with any rows already in the file and dropping duplicates (keyed on
    timestamp) so the same reading is never stored twice.
    """
    os.makedirs(DISCHARGE_DIR, exist_ok=True)
    out_path   = os.path.join(DISCHARGE_DIR, f"{site_code}.csv")
    fieldnames = ["site_code", "site_name", "variable", "value", "unit", "timestamp"]

    result = get_discharge(site_code, start=start, end=end)

    rows: dict = {}  # timestamp → row, so re-fetched timestamps overwrite rather than duplicate
    if os.path.exists(out_path):
        with open(out_path, newline="") as f:
            for row in csv.DictReader(f):
                rows[row["timestamp"]] = row

    for reading in result["readings"]:
        rows[reading["datetime"]] = {
            "site_code": result["site_code"],
            "site_name": result["site_name"],
            "variable":  result["variable"],
            "value":     reading["discharge_cfs"],
            "unit":      result["unit"],
            "timestamp": reading["datetime"],
        }

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(rows.values(), key=lambda r: r["timestamp"]))

    print(f"  {len(result['readings'])} readings fetched → {out_path} ({len(rows)} total rows)")


# ── Precipitation: download PRISM grids, then extract basin totals ────────────
def save_prism_data(start: str, end: str):
    """
    Download daily PRISM 800m precipitation grids for [start, end] (inclusive) into
    PRISM_DIR. Files are named us_800m_ppt_{YYYYMMDD}.zip; any date already on disk
    is skipped, so the same day is never downloaded twice.

    NOTE: PRISM limits downloads to 2 per file per 24h; we sleep 2s between fetches.
    PRISM daily data starts 1981-01-01. start / end are 'YYYY-MM-DD' strings.
    """
    from datetime import date, timedelta

    os.makedirs(PRISM_DIR, exist_ok=True)
    d, end_dt = date.fromisoformat(start), date.fromisoformat(end)
    while d <= end_dt:
        date_str = d.strftime("%Y%m%d")
        d += timedelta(days=1)
        zip_path = os.path.join(PRISM_DIR, f"us_800m_ppt_{date_str}.zip")
        if os.path.exists(zip_path):
            print(f"  PRISM {date_str} ... cached")
            continue
        print(f"  PRISM {date_str} ... downloading", end=" ", flush=True)
        resp = requests.get(f"{PRISM_URL}/{date_str}", timeout=60)
        if resp.status_code != 200:
            print(f"HTTP {resp.status_code} — skipped")
            continue
        with open(zip_path, "wb") as fh:
            fh.write(resp.content)
        print(f"saved ({len(resp.content) / 1024 / 1024:.1f} MB)")
        time.sleep(2)  # only throttle on actual downloads


def get_basin_precip(polygon: dict, start: str, end: str) -> float | None:
    """
    Total area-weighted precipitation (inches) over a basin polygon for [start, end].

    Reads the cached PRISM grids written by save_prism_data() (call that first). For
    each day it overlays the polygon on the PRISM grid, averages the cells the polygon
    intersects weighted by each cell's fractional overlap, then sums the daily basin
    averages over the period. Returns None if no day had any overlap/data.

    polygon: GeoJSON geometry dict ('Polygon' or 'MultiPolygon').
    Requires: rasterio, shapely, pyproj, numpy.
    """
    import zipfile
    from datetime import date, timedelta

    import numpy as np
    import pyproj
    from rasterio.io import MemoryFile
    from rasterio.mask import mask as rasterio_mask
    from shapely.geometry import box as shapely_box
    from shapely.geometry import shape
    from shapely.ops import transform as shapely_transform

    basin_shape = shape(polygon)
    total_in    = 0.0
    had_data    = False

    d, end_dt = date.fromisoformat(start), date.fromisoformat(end)
    while d <= end_dt:
        date_str = d.strftime("%Y%m%d")
        d += timedelta(days=1)
        zip_path = os.path.join(PRISM_DIR, f"us_800m_ppt_{date_str}.zip")
        if not os.path.exists(zip_path):
            print(f"  PRISM {date_str} ... missing (running save_prism_data first)")
            save_prism_data(start=start, end=end)

        with zipfile.ZipFile(zip_path) as zf:
            tif_name = next(
                n for n in zf.namelist()
                if n.endswith(".tif") and not n.endswith(".aux.xml")
            )
            tif_bytes = zf.read(tif_name)

        with MemoryFile(tif_bytes) as memfile:
            with memfile.open() as src:
                # reproject basin polygon to the raster CRS if it differs from WGS84
                if src.crs.to_epsg() != 4326:
                    tfm = pyproj.Transformer.from_crs(
                        "EPSG:4326", src.crs.to_wkt(), always_xy=True
                    )
                    basin_in_crs = shapely_transform(tfm.transform, basin_shape)
                else:
                    basin_in_crs = basin_shape
                # all_touched=True keeps every pixel the polygon touches
                masked, mask_tf = rasterio_mask(src, [basin_in_crs], crop=True, all_touched=True)
                nodata = src.nodata
                data   = masked[0].astype(float)

        # Weight each PRISM cell by the fraction of the BASIN that falls inside it:
        #   weight_i = (basin ∩ cell area) / (basin area covered)
        # so the weights sum to 1 and day_in = Σ weight_i · precip_i.
        # e.g. 63% of the basin in a 5 in cell + 37% in an 8 in cell → 0.63·5 + 0.37·8.
        rows_idx, cols_idx = np.where(data != nodata)
        weighted_sum = covered_area = 0.0
        for r, c in zip(rows_idx, cols_idx):
            pixel_box = shapely_box(
                mask_tf.c + c * mask_tf.a,
                mask_tf.f + (r + 1) * mask_tf.e,   # mask_tf.e is negative for north-up
                mask_tf.c + (c + 1) * mask_tf.a,
                mask_tf.f + r * mask_tf.e,
            )
            overlap_area = basin_in_crs.intersection(pixel_box).area
            if overlap_area > 0:
                weighted_sum += float(data[r, c]) * overlap_area
                covered_area += overlap_area

        if covered_area:
            day_in    = weighted_sum / covered_area  # Σ (overlap_i / covered) · precip_i
            total_in += day_in
            had_data  = True
            print(f"  PRISM {date_str} ... {round(day_in, 4)} in")

    return round(total_in, 4) if had_data else None


# ── Step 2: delineate the watershed with StreamStats ──────────────────────────
def delineate_watershed(lat: float, lon: float, region: str) -> dict:
    """
    Calls the StreamStats delineation API.
    Returns the full delineationResponse dict (needed for basin char calculation).
    """
    url = SS_DELINEATE_URL.format(region=region)
    r = requests.get(url, params={"lat": lat, "lon": lon}, timeout=120)

    if r.status_code != 200:
        raise RuntimeError(f"StreamStats delineation failed ({r.status_code}): {r.text[:300]}")

    return r.json()


# ── Step 3: compute basin characteristics ─────────────────────────────────────
def get_basin_characteristics(delineation_response: dict, char_codes: list[str] | None = None) -> list[dict]:
    """
    Submits the delineation response to the basin characteristics endpoint.
    Returns a list of {'code', 'name', 'value', 'unit'} dicts.

    char_codes: specific codes to request (e.g. ['DRNAREA', 'LC11FOREST']).
                Pass None to fetch all available characteristics for the region.
    """
    # deepcopy so we don't mutate the caller's delineation_response
    payload = copy.deepcopy(delineation_response)
    payload["bcrequest"]["bcLabels"] = ";".join(char_codes) if char_codes else "*"

    r = requests.post(SS_BASIN_CHAR_URL, json=payload, timeout=180)

    if r.status_code != 200:
        raise RuntimeError(f"Basin characteristics failed ({r.status_code}): {r.text[:300]}")

    return [
        {
            "code":  bc["code"],
            "name":  bc["name"],
            "value": bc["value"],
            "unit":  bc.get("unit", ""),
        }
        for bc in r.json()
    ]


# ── Helper: pull geometry out of a delineation response ──────────────────────
def extract_watershed_polygon(delineation_response: dict) -> dict | None:
    try:
        for item in delineation_response["bcrequest"]["wsresp"]["featurecollection"][0]:
            if item.get("name") == "globalwatershed":
                for feat in item["feature"]["features"]:
                    if feat.get("properties", {}).get("GlobalWshd") == 1:
                        return feat["geometry"] if feat else None
    except (KeyError, IndexError, TypeError):
        pass
    return None


# ── Collect everything for a single site ──────────────────────────────────────
def collect_site_data(
    site_code: str,
    char_codes: list[str] | None,
    precip_start: str,
    precip_end: str,
    discharge_start: str,
    discharge_end: str,
) -> dict:
    """
    Collect all data for one site and return a flat dict (one CSV row) of site info,
    basin characteristics, and total basin precipitation. Discharge is written to the
    site's own CSV as a side effect (see save_discharge).
    """
    print(f"\n[{site_code}] site info...")
    info = get_site_info(site_code)
    lat, lon, region = info["lat"], info["lon"], "NC"
    print(f"[{site_code}] {info['site_name']}  lat={lat:.5f} lon={lon:.5f} region={region}")

    print(f"[{site_code}] delineating watershed (this may take ~30s)...")
    delineation = delineate_watershed(lat, lon, region)
    polygon     = extract_watershed_polygon(delineation)

    print(f"[{site_code}] basin characteristics...")
    chars = get_basin_characteristics(delineation, char_codes=char_codes)

    row = {
        "site_code":      site_code,
        "site_name":      info.get("site_name", ""),
        "lat":            lat,
        "lon":            lon,
        "region":         region,
        "huc":            info.get("huc", ""),
    }
    for bc in chars:
        row[bc["code"]] = bc["value"]

    print(f"[{site_code}] precipitation {precip_start} → {precip_end}...")
    if polygon is None:
        print("  WARNING: no watershed polygon — skipping precip.")
        row["precip_total_in"] = None
    else:
        save_prism_data(precip_start, precip_end)  # cached after the first site
        row["precip_total_in"] = get_basin_precip(polygon, precip_start, precip_end)

    print(f"[{site_code}] discharge {discharge_start} → {discharge_end}...")
    save_discharge(site_code, discharge_start, discharge_end)

    print(f"[{site_code}] done.")
    return row


if __name__ == "__main__":
    rows: list[dict] = []
    for site in SITE_CODES:
        try:
            rows.append(collect_site_data(
                site, CHAR_CODES,
                precip_start=PRECIP_START, precip_end=PRECIP_END,
                discharge_start=DISCHARGE_START, discharge_end=DISCHARGE_END,
            ))
        except Exception as e:
            print(f"[{site}] ERROR: {e}")

    if not rows:
        print("\nNo data collected. Check site codes and region.")
    else:
        # union of all columns, fixed metadata first then basin characteristics
        fixed  = ["site_code", "site_name", "lat", "lon", "region",
                  "huc", "precip_total_in"]
        extra  = sorted({k for r in rows for k in r} - set(fixed))
        fields = fixed + extra

        with open(BASIN_CHAR_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        print(f"\nSaved {len(rows)} sites → {BASIN_CHAR_CSV}")
        print(f"Columns: {len(fields)} total ({len(extra)} basin characteristics)")
