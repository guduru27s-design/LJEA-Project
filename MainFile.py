"""
"""
import copy
import requests
import pandas as pd
import matplotlib.pyplot as plt


NWIS_SITE_URL     = "https://waterservices.usgs.gov/nwis/site/"
NWIS_IV_URL       = "https://waterservices.usgs.gov/nwis/iv/"
SS_DELINEATE_URL  = "https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/{region}"
SS_BASIN_CHAR_URL = "https://streamstats.usgs.gov/ss-hydro/v1/basin-characteristics/calculate"

SITE_CODE = "02138816"  
REGION    = "NC"    

def get_site_info(site_code: str) -> dict:
    """
    Queries NWIS for basic metadata about a stream gauge.

    Required input:
      site_code (str) — 8-digit USGS site code, e.g. '02138816'

    Returns a dict with keys:
      site_code, site_name, lat, lon, state, huc
    """
    params = {
        "format":     "rdb",        # request tab-delimited text (RDB format)
        "sites":      site_code,
        "siteOutput": "expanded",   # include coordinates and HUC
    }
    r = requests.get(NWIS_SITE_URL, params=params, timeout=30)
    r.raise_for_status()  # raises an error if the HTTP request failed

    # Remove comment lines (lines starting with '#')
    lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]

    # lines[0] = column headers
    # lines[1] = format spec row (skip)
    # lines[2] = first (and only) data row for a single site
    if len(lines) < 3:
        raise ValueError(f"Site {site_code} not found in NWIS")

    headers = lines[0].split("\t")
    values  = lines[2].split("\t")
    row     = dict(zip(headers, values))   # pair each header with its value

    return {
        "site_code": site_code,
        "site_name": row.get("station_nm", ""),
        "lat":       float(row["dec_lat_va"]),
        "lon":       float(row["dec_long_va"]),
        "state":     row.get("state_cd", ""),
        "huc":       row.get("huc_cd", ""),
    }

site_info = get_site_info(SITE_CODE)

print(f"Name:      {site_info['site_name']}")
print(f"Location:  {site_info['lat']:.5f}°N, {site_info['lon']:.5f}°W")
print(f"State:     {site_info['state']}")
print(f"HUC:       {site_info['huc']}")

def get_discharge(site_code: str, start: str = None, end: str = None) -> dict:
    """
    Downloads instantaneous discharge (ft³/s) from NWIS.

    Required input:
      site_code (str) — 8-digit USGS site code

    Optional inputs:
      start (str) — start date, e.g. '2026-01-01'
      end   (str) — end date,   e.g. '2026-01-31'
      (If omitted, returns only the last 120 minutes of data.)

    Returns a dict with:
      site_code, site_name, lat, lon, variable, unit,
      readings — list of {datetime, discharge_cfs}
    """
    params = {
        "format":      "json",
        "sites":       site_code,
        "parameterCd": "00060",       # 00060 = streamflow discharge in ft³/s
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

    ts      = series[0]
    geo     = ts["sourceInfo"]["geoLocation"]["geogLocation"]
    var     = ts["variable"]
    no_data = var["noDataValue"]   # NWIS uses a sentinel value for missing readings

    readings = []
    for v in ts["values"][0]["value"]:
        raw = float(v["value"])
        if raw == no_data:            # skip missing/erroneous readings
            continue
        readings.append({
            "datetime":      v["dateTime"],
            "discharge_cfs": raw,
        })

    return {
        "site_code": site_code,
        "site_name": ts["sourceInfo"]["siteName"],
        "lat":       geo["latitude"],
        "lon":       geo["longitude"],
        "variable":  var["variableName"],
        "unit":      var["unit"]["unitCode"],
        "readings":  readings,
    }


# Adjust the dates to any time window you want to study
FLOW_START = "2026-05-01"
FLOW_END   = "2026-05-07"

discharge = get_discharge(SITE_CODE, start=FLOW_START, end=FLOW_END)

print(f"Site:     {discharge['site_name']}")
print(f"Variable: {discharge['variable']}")
print(f"Unit:     {discharge['unit']}")
print(f"Readings: {len(discharge['readings'])} measurements")


# Load the time series into a DataFrame for easy inspection
df_flow = pd.DataFrame(discharge["readings"])
df_flow["datetime"] = pd.to_datetime(df_flow["datetime"])
df_flow = df_flow.set_index("datetime")

print("Summary statistics:")
print(df_flow.describe().round(2))
print()
df_flow.head(10)


# Load the time series into a DataFrame for easy inspection
df_flow = pd.DataFrame(discharge["readings"])
df_flow["datetime"] = pd.to_datetime(df_flow["datetime"])
df_flow = df_flow.set_index("datetime")

print("Summary statistics:")
print(df_flow.describe().round(2))
print()
df_flow.head(10)


fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(df_flow.index, df_flow["discharge_cfs"], linewidth=1.2, color="steelblue")
ax.fill_between(df_flow.index, df_flow["discharge_cfs"], alpha=0.15, color="steelblue")
ax.set_title(f"Discharge — {discharge['site_name']}\n({SITE_CODE}, {FLOW_START} to {FLOW_END})",
             fontsize=12)
ax.set_xlabel("Date")
ax.set_ylabel("Discharge (ft³/s)")
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

def delineate_watershed(lat: float, lon: float, region: str) -> dict:
    """
    Calls the StreamStats API to trace the watershed upstream of a point.

    Required inputs:
      lat    (float) — latitude in decimal degrees
      lon    (float) — longitude in decimal degrees
      region (str)   — two-letter state abbreviation, e.g. 'NC'

    Returns the full delineation response dict.
    This response is passed directly to get_basin_characteristics() in Step 4 —
    you do not need to modify it.

    """
    url = SS_DELINEATE_URL.format(region=region)
    print(f"  Sending delineation request for ({lat:.5f}, {lon:.5f}) in region '{region}'...")

    r = requests.get(url, params={"lat": lat, "lon": lon}, timeout=120)

    if r.status_code != 200:
        raise RuntimeError(
            f"StreamStats delineation failed ({r.status_code}): {r.text[:300]}"
        )

    return r.json()


print(f"Delineating watershed for site {SITE_CODE}...")

delineation = delineate_watershed(
    lat    = site_info["lat"],
    lon    = site_info["lon"],
    region = REGION,
)

print("\nDelineation complete.")

# The delineation response is a large nested JSON object.
# Let's look at the top-level keys to understand its structure.
print("Top-level keys:", list(delineation.keys()))

# ── Extract watershed area from the geometry properties ───────────────────────
def get_watershed_area_sqmi(delineation_response: dict) -> float:
    """
    Pulls the drainage area (sq mi) out of the delineation response geometry.
    Returns None if the area property is not found.
    """
    try:
        collections = delineation_response["bcrequest"]["wsresp"]["featurecollection"][0]
        for item in collections:
            if item.get("name") == "globalwatershed":
                for feat in item["feature"]["features"]:
                    if feat.get("properties", {}).get("GlobalWshd") == 1:
                        return feat["properties"].get("AreaSqMi")
    except (KeyError, IndexError, TypeError):
        pass
    return None

area = get_watershed_area_sqmi(delineation)
print(f"\nWatershed drainage area: {area} sq mi")


def get_basin_characteristics(delineation_response: dict, char_codes: list = None) -> list:
    """
    Computes basin characteristics for the watershed defined by a delineation response.

    Required input:
      delineation_response (dict) — the full JSON dict returned by delineate_watershed()

    Optional input:
      char_codes (list of str) — specific characteristic codes to compute,
                                 e.g. ['DRNAREA', 'ELEV', 'LC11FOREST']
                                 Pass None to fetch all available characteristics.

    Returns a list of dicts, one per characteristic:
      [{'code': 'DRNAREA', 'name': 'Drainage area', 'value': 23.4, 'unit': 'sq mi'}, ...]
    """
    # deepcopy so we don't accidentally modify the caller's delineation dict
    payload = copy.deepcopy(delineation_response)

    # Add the list of requested codes to the bcrequest block
    # '*' means 'all available for this region'
    payload["bcrequest"]["bcLabels"] = ";".join(char_codes) if char_codes else "*"

    print("  Sending request to StreamStats basin characteristics API...")
    r = requests.post(SS_BASIN_CHAR_URL, json=payload, timeout=180)

    if r.status_code != 200:
        raise RuntimeError(
            f"Basin characteristics failed ({r.status_code}): {r.text[:300]}"
        )

    return [
        {
            "code":  bc["code"],
            "name":  bc["name"],
            "value": bc["value"],
            "unit":  bc.get("unit", ""),
        }
        for bc in r.json()
    ]


# Choose which characteristics to fetch.
# Requesting only what you need is faster than requesting all.
CHAR_CODES = [
    "DRNAREA",     # Drainage area (sq mi)
    "ELEV",        # Mean basin elevation (ft)
    "ELEVMAX",     # Maximum elevation (ft)
    "MINBELEV",    # Minimum (outlet) elevation (ft)
    "BSLDEM30FT",  # Mean basin slope (%)
    "LFPLENGTH",   # Longest flow path length (mi)
    "LC11FOREST",  # Forest cover, NLCD 2011 (%)
    "LC11DEV",     # Developed/urban land, NLCD 2011 (%)
    "LC11IMP",     # Impervious surface, NLCD 2011 (%)
    "LC11WATER",   # Open water, NLCD 2011 (%)
    "LC11WETLND",  # Wetlands, NLCD 2011 (%)
    "PRECIP",      # Mean annual precipitation (in)
    "I24H50Y",     # 24-hr, 50-year storm depth (in)
]

print(f"Fetching {len(CHAR_CODES)} characteristics for site {SITE_CODE}...")
characteristics = get_basin_characteristics(delineation, char_codes=CHAR_CODES)
print(f"Done. {len(characteristics)} characteristics returned.")

df_chars = pd.DataFrame(characteristics).set_index("code")

print(f"Basin characteristics — {site_info['site_name']} ({SITE_CODE})\n")
df_chars[["name", "value", "unit"]]

def collect_site_data(site_code: str, region: str, char_codes: list = None) -> dict:
    """
    Runs Steps 1, 3, and 4 for a single USGS gauge site.

    Steps:
      1. get_site_info        — fetch gauge name and coordinates
      3. delineate_watershed  — trace the watershed boundary
      4. get_basin_characteristics — compute physical basin descriptors

    Returns a dict with keys:
      'info'           — from get_site_info()
      'delineation'    — from delineate_watershed()
      'characteristics'— from get_basin_characteristics()
      'area_sqmi'      — watershed area extracted from delineation geometry
    """
    print(f"\n{'='*60}")
    print(f"  Site: {site_code}  |  Region: {region}")
    print(f"{'='*60}")

    # Step 1
    print("\n[Step 1] Fetching site information...")
    info = get_site_info(site_code)
    print(f"  → {info['site_name']}")
    print(f"  → {info['lat']:.5f}°N, {info['lon']:.5f}°W  |  HUC: {info['huc']}")

    # Step 3
    print("\n[Step 3] Delineating watershed (may take ~60s)...")
    delineation = delineate_watershed(info["lat"], info["lon"], region)
    area = get_watershed_area_sqmi(delineation)
    print(f"  → Drainage area: {area} sq mi")

    # Step 4
    print("\n[Step 4] Computing basin characteristics...")
    chars = get_basin_characteristics(delineation, char_codes=char_codes)
    print(f"  → {len(chars)} characteristics retrieved")

    return {
        "info":            info,
        "delineation":     delineation,
        "characteristics": chars,
        "area_sqmi":       area,
    }

# Run the full pipeline
result = collect_site_data(SITE_CODE, REGION, char_codes=CHAR_CODES)

info  = result["info"]
chars = result["characteristics"]

print(f"\n{'─'*50}")
print(f"  {info['site_name']}")
print(f"  Site code : {info['site_code']}")
print(f"  Location  : {info['lat']:.5f}°N, {info['lon']:.5f}°W")
print(f"  HUC       : {info['huc']}")
print(f"  Area      : {result['area_sqmi']} sq mi")
print(f"{'─'*50}\n")

df_final = pd.DataFrame(chars).set_index("code")
df_final[["name", "value", "unit"]]

