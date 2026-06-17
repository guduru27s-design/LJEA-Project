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
STARTDATE = input("Enter the start date for data retrieval (YYYYMMDD): ")
ENDDATE = input("Enter the end date for data retrieval (YYYYMMDD): ")

# - - - - - - - - - -

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

# -

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

# - 

def get_prism_for_date(date_string):
    global ppt_day, tmin_f, tmax_f, tmean_f

    print(f"Fetching PRISM data for {date_string}...")
    if polygon is None:
        print("No polygon found — skipping PRISM")
        prism_data = None
    else:
        prism_data = get_basin_prism(polygon, ENDDATE)

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