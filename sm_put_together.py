from narwhals import when
import pandas as pd
import statsmodels.formula.api as smf
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import requests
import json
import copy

NWIS_SITE_URL     = "https://waterservices.usgs.gov/nwis/site/"
NWIS_IV_URL       = "https://waterservices.usgs.gov/nwis/iv/"
SS_DELINEATE_URL  = "https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/{region}"
SS_BASIN_CHAR_URL = "https://streamstats.usgs.gov/ss-hydro/v1/basin-characteristics/calculate"

REGION = input("Enter the region code for your site (e.g. CA for California): ")
LATITUDE = float(input("Enter the latitude of your site: "))
LONGITUDE = float(input("Enter the longitude of your site: "))
STARTDATE = input("Enter the start date for data retrieval (YYYYMMDD): ")
ENDDATE = input("Enter the end date for data retrieval (YYYYMMDD): ")

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

print(f"Delineating watershed for site...")

delineation = delineate_watershed(
    lat    = LATITUDE,
    lon    = LONGITUDE,
    region = REGION,
)

print("\nDelineation complete.")
print("Top-level keys:", list(delineation.keys()))

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

print(f"Fetching {len(CHAR_CODES)} characteristics for site...")
characteristics = get_basin_characteristics(delineation, char_codes=CHAR_CODES)
print(f"Done. {len(characteristics)} characteristics returned.")

df_chars = pd.DataFrame(characteristics).set_index("code")

print(f"Basin characteristics for: {LATITUDE:.5f}, {LONGITUDE:.5f} ({REGION}):")
df_chars[["name", "value", "unit"]]

print(df_chars[["name", "value", "unit"]])

CN = float(
    ((int(df_chars.loc["LC11CRPHAY", "value"]) / 100) * 
     ((df_chars.loc["SSURGOA", "value"] * 68 + df_chars.loc["SSURGOB", "value"]
       * 76 + df_chars.loc["SSURGOC", "value"] * 
       83 + df_chars.loc["SSURGOD", "value"] * 87) / 100))
    + ((int(df_chars.loc["LC11FOREST", "value"]) / 100) *
       ((df_chars.loc["SSURGOA", "value"] * 30 + df_chars.loc["SSURGOB", "value"]
         * 60 + df_chars.loc["SSURGOC", "value"] *
         75 + df_chars.loc["SSURGOD", "value"] * 81) / 100))
    + ((int(df_chars.loc["LC11DEV", "value"]) / 100) * 
       ((df_chars.loc["SSURGOA", "value"] * 77 + 
         df_chars.loc["SSURGOB", "value"] * 85 + df_chars.loc["SSURGOC", "value"]
         * 90 + df_chars.loc["SSURGOD", "value"] * 92) / 100))
    + ((int(df_chars.loc["LC11GRASS", "value"]) / 100) * 
       ((df_chars.loc["SSURGOA", "value"] * 45 + df_chars.loc["SSURGOB", "value"]
         * 59 + df_chars.loc["SSURGOC", "value"] * 75 +
         df_chars.loc["SSURGOD", "value"] * 85) / 100))
    + ((int(df_chars.loc["LC11SHRUB", "value"]) / 100) * 
       ((df_chars.loc["SSURGOA", "value"] * 35 + df_chars.loc["SSURGOB", "value"]
         * 56 + df_chars.loc["SSURGOC", "value"] * 70 + 
         df_chars.loc["SSURGOD", "value"] * 77) / 100))
    + ((int(df_chars.loc["LC11IMP", "value"]) / 100) *
       ((df_chars.loc["SSURGOA", "value"] * 98 + df_chars.loc["SSURGOB", "value"]
         * 98 + df_chars.loc["SSURGOC", "value"] * 98 + 
         df_chars.loc["SSURGOD", "value"] * 98) / 100))
    + ((int(df_chars.loc["LC11BARE", "value"]) + 
        int(df_chars.loc["LC11WATER", "value"]) + 
        int(df_chars.loc["LC11WETLND", "value"])) / 100) * 
    ((df_chars.loc["SSURGOA", "value"] * 59 + df_chars.loc["SSURGOB", "value"] 
      * 72 + df_chars.loc["SSURGOC", "value"] * 82 +
      df_chars.loc["SSURGOD", "value"] * 87) / 100) +2
)

Wet_CN = float(CN + 4)
Dry_CN = float(CN - 4)

precipW = [0.5, 1.5, 2.5, 3.0]
prev = ['CN', 'Wet_CN', 'Dry_CN', 'CN'] 

for precip in precipW:
    if prev == 'CN':
        if precip >= 2:
            Curve = Wet_CN
        elif precip < 2 and precip > 1:
            Curve = CN
        elif precip <= 1:
            Curve = Dry_CN
        else:
            pass
    elif prev == 'Wet_CN':
        if precip >= 2:
            Curve = Wet_CN
        elif precip < 2 and precip > 1:
            Curve = CN
        elif precip <= 1:
            Curve = CN
        else:
            pass
    elif prev == 'Dry_CN':
        if precip < 2 and precip > 1:
            Curve = Dry_CN
        elif precip <= 1:
            Curve = Dry_CN
        elif precip >= 2:
            Curve = CN
        else:
            pass
            
    print(f"Calculated curve number (CN) for the watershed: {Curve:.1f}")

    
    

