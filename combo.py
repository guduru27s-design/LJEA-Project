#ADDING PRISM AND NWIS
'''
THIS IS A NEW FILE TO TEST ADDING PRISM AND NWIS CODE TOGETHER :)
'''
import pandas as pd
import statsmodels.formula.api as smf
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import requests
import json
import copy

# PRISM IMPORTS - - - -
import io
import zipfile
import rasterio
from rasterio.io import MemoryFile

import numpy as np
import requests

from shapely.geometry import shape, box
from rasterio.mask import mask as rio_mask
from shapely.ops import transform
import pyproj

from datetime import datetime, timedelta
# - - - - - - - - - -

NWIS_SITE_URL     = "https://waterservices.usgs.gov/nwis/site/"
NWIS_IV_URL       = "https://waterservices.usgs.gov/nwis/iv/"
SS_DELINEATE_URL  = "https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/{region}"
SS_BASIN_CHAR_URL = "https://streamstats.usgs.gov/ss-hydro/v1/basin-characteristics/calculate"

REGION = input("Enter the region code for your site (e.g. CA for California): ")
LATITUDE = float(input("Enter the latitude of your site: "))
LONGITUDE = float(input("Enter the longitude of your site: "))
STARTDATE = input("Enter the start date for data retrieval (YYYYMMDD) (e.g., 20230101 if looking for data from 20230107): ")
ENDDATE = input("Enter the end date for data retrieval (YYYYMMDD) (e.g., the date you want to look for): ")
SLOPECORRECTIONCN = input("What is the slope correction factor for the CN? (Enter a number, or leave blank for no correction): ")
if SLOPECORRECTIONCN:
    SLOPECORRECTIONCN = float(SLOPECORRECTIONCN)
else:    SLOPECORRECTIONCN = 0.0
SLOPECORRECTIONIA = input("What is the slope correction factor for the initial abstraction ratio (Ia)? (Enter a number, or leave blank for no correction): ")
if SLOPECORRECTIONIA:
    SLOPECORRECTIONIA = float(SLOPECORRECTIONIA)
else:    SLOPECORRECTIONIA = 0.0

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

# ── NEW: extract watershed polygon from StreamStats ──
def extract_watershed_polygon(delineation_response: dict):
    """
    Pulls global watershed geometry from StreamStats response.
    """
    try:
        fc = delineation_response["bcrequest"]["wsresp"]["featurecollection"]

        for group in fc:
            for item in group:
                if item.get("name") == "globalwatershed":
                    for feat in item["feature"]["features"]:
                        if feat["properties"].get("GlobalWshd") == 1:
                            return feat["geometry"]
    except Exception:
        pass

    return None

polygon = extract_watershed_polygon(delineation)

print(f"Watershed polygon geometry type: {polygon['type']}")

def get_basin_prism(polygon_geojson, date_string):
    """
    Basin-averaged PRISM values using StreamStats polygon.
    """

    elements = ["ppt", "tmin", "tmax", "tmean"]
    results = {}

    basin_shape = shape(polygon_geojson)

    for element in elements:

        year = date_string[:4]

        url = (
            f"https://data.prism.oregonstate.edu/time_series/us/an/4km/"
            f"{element}/daily/{year}/prism_{element}_us_25m_{date_string}.zip"
        )

        r = requests.get(url)
        r.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(r.content)) as z:

            tif_file = [f for f in z.namelist() if f.endswith(".tif")][0]

            with z.open(tif_file) as tif:
                tif_bytes = tif.read()

            with MemoryFile(tif_bytes) as memfile:
                with memfile.open() as src:

                    # reproject if needed
                    if src.crs.to_epsg() != 4326:
                        project = pyproj.Transformer.from_crs(
                            "EPSG:4326",
                            src.crs,
                            always_xy=True
                        ).transform
                        geom = transform(project, basin_shape)
                    else:
                        geom = basin_shape

                    masked, tfm = rio_mask(
                        src,
                        [geom],
                        crop=True,
                        all_touched=True
                    )

                    data = masked[0].astype(float)
                    nodata = src.nodata

        rows, cols = np.where(data != nodata)

        weighted_sum = 0.0
        total_area = 0.0

        for r_i, c_i in zip(rows, cols):

            pixel = box(
                tfm.c + c_i * tfm.a,
                tfm.f + (r_i + 1) * tfm.e,
                tfm.c + (c_i + 1) * tfm.a,
                tfm.f + r_i * tfm.e,
            )

            overlap = geom.intersection(pixel).area

            if overlap > 0:
                weighted_sum += float(data[r_i, c_i]) * overlap
                total_area += overlap

        results[element] = (
            weighted_sum / total_area if total_area > 0 else None
        )

    return results

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

print("\n")

def get_prism_for_date(date_string):
    global ppt_day, tmin_f, tmax_f, tmean_f

    print(f"Fetching PRISM data for {date_string}...")
    if polygon is None:
        print("No polygon found — skipping PRISM")
        prism_data = None
    else:
        prism_data = get_basin_prism(polygon, date_string)

    # Convert PRISM units

    ppt_day = prism_data["ppt"] / 25.4

    tmin_f = (prism_data["tmin"] * 9/5) + 32
    tmax_f = (prism_data["tmax"] * 9/5) + 32
    tmean_f = (prism_data["tmean"] * 9/5) + 32

    prism_data = {
        "ppt": ppt_day,
        "tmin": tmin_f,
        "tmax": tmax_f,
        "tmean": tmean_f}

    print(f"PRISM data for {date_string} extracted and converted!")

    return prism_data

    # NOTE: extract PRISM values from the list and turn them into variables we can pull from for regression
    # IF YOU ACTUALLY CALL THE prism_data, IT WILL PRINT OUT THE FULL DICT WITH ALL 4 ELEMENTS CONVERTED (ppt, tmin, tmax, tmean)

def save_end_day_prism():
    global ppt_daily, tmin_daily, tmax_daily, tmean_daily

    get_prism_for_date(ENDDATE)

    ppt_daily = ppt_day
    tmin_daily = tmin_f
    tmax_daily = tmax_f
    tmean_daily = tmean_f

save_end_day_prism()
prism_endday_df = pd.DataFrame({
    "Variable": [
        "Precipitation",
        "Minimum Temperature",
        "Maximum Temperature",
        "Mean Temperature"
    ],
    "Value": [
        round(ppt_daily, 2),
        round(tmin_daily, 1),
        round(tmax_daily, 1),
        round(tmean_daily, 1)
    ],
    "Unit": [
        "in",
        "°F",
        "°F",
        "°F"
    ]
})


print("\nPRISM Climate Data (END DAY ONLY):")
print(prism_endday_df)

print("\n")

def get_yesterday_prism_str():
    global previous_day_str
    end_dt = datetime.strptime(ENDDATE, "%Y%m%d")
    previous_day = end_dt - timedelta(days=1)
    previous_day_str = previous_day.strftime("%Y%m%d")
    return previous_day_str

def save_yesterday_prism():
    global ppt_yesterday, tmin_yesterday, tmax_yesterday, tmean_yesterday

    get_prism_for_date(get_yesterday_prism_str())

    ppt_yesterday = ppt_day
    tmin_yesterday = tmin_f
    tmax_yesterday = tmax_f
    tmean_yesterday = tmean_f

save_yesterday_prism()
prism_yesterday_df = pd.DataFrame({
    "Variable": [
        "Precipitation",
        "Minimum Temperature",
        "Maximum Temperature",
        "Mean Temperature"
    ],
    "Value": [
        round(ppt_yesterday, 2),
        round(tmin_yesterday, 1),
        round(tmax_yesterday, 1),
        round(tmean_yesterday, 1)
    ],
    "Unit": [
        "in",
        "°F",
        "°F",
        "°F"
    ]
})

print("\nPRISM Climate Data (DAY BEFORE END DAY):")
print(prism_yesterday_df)

def get_basin_prism_range(polygon_geojson, start_date, end_date):
    global ppt_per_sum, tmin_per_avg, tmax_per_avg, tmean_per_avg

    current = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")

    all_days = []

    while current <= end:

        date_string = current.strftime("%Y%m%d")
        print(f"Fetching PRISM data for {date_string}...")

        daily_data = get_basin_prism(
            polygon_geojson,
            date_string
        )

        all_days.append(daily_data)

        current += timedelta(days=1)

    ppt_total_mm = sum(d["ppt"] for d in all_days)

    tmin_avg_c = np.mean([d["tmin"] for d in all_days])
    tmax_avg_c = np.mean([d["tmax"] for d in all_days])
    tmean_avg_c = np.mean([d["tmean"] for d in all_days])

    prism_period_data = {
        "ppt": ppt_total_mm / 25.4,
        "tmin": (tmin_avg_c * 9/5) + 32,
        "tmax": (tmax_avg_c * 9/5) + 32,
        "tmean": (tmean_avg_c * 9/5) + 32
    }

    ppt_per_sum = prism_period_data["ppt"]
    tmin_per_avg = prism_period_data["tmin"]
    tmax_per_avg = prism_period_data["tmax"]
    tmean_per_avg = prism_period_data["tmean"]

    return prism_period_data

prism_days = get_basin_prism_range(polygon, STARTDATE, ENDDATE)

prism_period_df = pd.DataFrame({
    "Variable": [
        "Precipitation",
        "Minimum Temperature",
        "Maximum Temperature",
        "Mean Temperature"
    ],
    "Value": [
        round(ppt_per_sum, 2),
        round(tmin_per_avg, 1),
        round(tmax_per_avg, 1),
        round(tmean_per_avg, 1)
    ],
    "Unit": [
        "in",
        "°F",
        "°F",
        "°F"
    ]
})

print("\nPRISM Climate Data (PERIOD DATA):")
print(prism_period_df)
'''
---CN CALCULATION---
'''
Norm_CN = float(
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
    - ((int(df_chars.loc["LC11BARE", "value"]) + 
        int(df_chars.loc["LC11WATER", "value"]) + 
        int(df_chars.loc["LC11WETLND", "value"])) / 100) * 
    ((df_chars.loc["SSURGOA", "value"] * 59 + df_chars.loc["SSURGOB", "value"] 
      * 72 + df_chars.loc["SSURGOC", "value"] * 82 +
      df_chars.loc["SSURGOD", "value"] * 87) / 100) + SLOPECORRECTIONCN
)

Wet_CN = float(Norm_CN + 4)
Dry_CN = float(Norm_CN - 4)

if ppt_per_sum >= 2:
    Curve = Wet_CN
    print(f"Calculated wet curve number (CN) for the watershed: {Curve}")
elif ppt_per_sum < 2 and ppt_per_sum > 1:
    Curve = Norm_CN
    print(f"Calculated normal curve number (CN) for the watershed: {Curve}")
elif ppt_per_sum <= 1:
    Curve = Dry_CN
    print(f"Calculated dry curve number (CN) for the watershed: {Curve}")
else:
    pass


'''
---IA CALCULATION---
'''


if "BSLDEM30FT" in df_chars.index:
    BSLDEM30FT = float(df_chars.loc["BSLDEM30FT", "value"])
    if BSLDEM30FT > 10 and BSLDEM30FT <= 30:
        Ia = 0.2
    elif BSLDEM30FT > 30 and BSLDEM30FT <= 45:
        Ia = 0.15

if SLOPECORRECTIONIA != 0.0:
    Norm_Ia = Ia + SLOPECORRECTIONIA
    
Wet_Ia = float(Norm_Ia + 0.04)
Dry_Ia = float(Norm_Ia - 0.04)
    
if ppt_per_sum >= 2:
    IntialAbstraction = Wet_Ia
    print(f"Calculated wet initial abstraction (Ia) for the watershed: {IntialAbstraction}")
elif ppt_per_sum < 2 and ppt_per_sum > 1:
    IntialAbstraction = Norm_Ia
    print(f"Calculated normal initial abstraction (Ia) for the watershed: {IntialAbstraction}")
elif ppt_per_sum <= 1:
    IntialAbstraction = Dry_Ia
    print(f"Calculated dry initial abstraction (Ia) for the watershed: {IntialAbstraction}")
else:
    pass

'''Adjustment factor calculation for the CN based on the month of the year and yesterday's precipitation'''    
def retrieve_month(ENDDATE):
    """
    Extracts the month from the ENDDATE string in YYYYMMDD format.
    """
    return int(ENDDATE[4:6])
month = retrieve_month(ENDDATE)
  
def calculate_daily_adjustment(df):
    """
    df requires columns: 'month', 'daily_precip', 'yesterday_precip'
    Returns an array for the 'A' variable in Term 3
    """
    adjustments = []
    for idx, row in df.iterrows():
        # 1. Base canopy interception penalty (in inches)
        # Higher in summer, lower in winter
        if row['month'] in [5, 6, 7, 8, 9]:  # May - Sept
            et_loss = -0.08  # High summer evapotranspiration / interception
        else:
            et_loss = -0.02  # Low winter loss
            
        # 2. Yesterday's priming factor (Shallow storage memory)
        if row['ppt_yesterday'] > 0.5:
            priming_bonus = 0.04  # Soil is wet, boost the linear response
        else:
            priming_bonus = 0.0
            
        # Total adjustment depth for the day
        daily_A = et_loss + priming_bonus
        adjustments.append(daily_A)
        
    return adjustments

print(calculate_daily_adjustment(pd.DataFrame({
    'month': [month],
    'ppt_yesterday': [ppt_yesterday]
})))
