# CODE THAT BRINGS EVERYTHING TOGETHER TO GRAB DATA FOR ALL THE DATES WE ASK FOR AND PUTS THE STUFF IN CSV?
'''
I HOPE THIS WORKS
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

import os
print(os.getcwd())
# - - - - - - - - - -

NWIS_SITE_URL     = "https://waterservices.usgs.gov/nwis/site/"
NWIS_IV_URL       = "https://waterservices.usgs.gov/nwis/iv/"
SS_DELINEATE_URL  = "https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/{region}"
SS_BASIN_CHAR_URL = "https://streamstats.usgs.gov/ss-hydro/v1/basin-characteristics/calculate"



start_date = "20250525"
end_date = "20250526"

# MIAS CODE - - - -

SITE_CODES = [
    "02138500",  # LINVILLE RIVER NEAR NEBO, NC
    "02137727",  # CATAWBA R NR PLEASANT GARDENS, NC
]

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
print("\nSite 1 Information:")
LINVILLE_LIST = get_site_info(SITE_CODES[0])
print(LINVILLE_LIST)


print("\nSite 2 Information:")
CATAWBA_LIST = get_site_info(SITE_CODES[1])
print(CATAWBA_LIST)

# - - - - - -

def build_gauge_data(site_code):

    site_info = get_site_info(site_code)

    delineation = delineate_watershed(
        lat=site_info["lat"],
        lon=site_info["lon"],
        region="NC"
    )

    polygon = extract_watershed_polygon(delineation)

    characteristics = get_basin_characteristics(
        delineation,
        char_codes=CHAR_CODES
    )

    df_chars = pd.DataFrame(
        characteristics
    ).set_index("code")

    prism_cache = build_prism_cache(
        polygon,
        start_date,
        end_date
    )

    return {
        "df_chars": df_chars,
        "prism_cache": prism_cache,
        "polygon": polygon
    }

def get_daily_avg_streamflow(site_no, date_string):

    start_date = datetime.strptime(date_string, "%Y%m%d")
    end_date = start_date + timedelta(days=1)

    params = {
        "format": "json",
        "sites": site_no,
        "startDT": start_date.strftime("%Y-%m-%d"),
        "endDT": end_date.strftime("%Y-%m-%d"),
        "parameterCd": "00060"
    }

    r = requests.get(NWIS_IV_URL, params=params)
    r.raise_for_status()

    data = r.json()

    try:
        values = data["value"]["timeSeries"][0]["values"][0]["value"]
    except (KeyError, IndexError):
        return None

    flows = [
        float(p["value"])
        for p in values
        if p.get("value") not in ["", None]
    ]

    return np.mean(flows) if flows else None

# - - - - - -

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

def build_prism_cache(polygon, start_date, end_date):
    """
    Downloads PRISM once for every day and stores it.

    Returns:
        {
            "20250101": {
                "ppt": ...,
                "tmin": ...,
                "tmax": ...,
                "tmean": ...
            },
            ...
        }
    """

    current = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")

    prism_cache = {}

    while current <= end:

        date_string = current.strftime("%Y%m%d")

        print(f"Downloading PRISM {date_string}")

        raw = get_basin_prism(
            polygon,
            date_string
        )

        prism_cache[date_string] = {
            "ppt": raw["ppt"] / 25.4,
            "tmin": (raw["tmin"] * 9/5) + 32,
            "tmax": (raw["tmax"] * 9/5) + 32,
            "tmean": (raw["tmean"] * 9/5) + 32
        }

        current += timedelta(days=1)

    return prism_cache

def load_day_variables(date_string, prism_cache):
    global ppt_daily, ppt_per_sum, ppt_yesterday
    global tmin_daily, tmax_daily, tmean_daily
    global DRNAREA

    # ----- Daily PRISM -----

    ppt_daily = prism_cache[date_string]["ppt"]

    tmin_daily = prism_cache[date_string]["tmin"]
    tmax_daily = prism_cache[date_string]["tmax"]
    tmean_daily = prism_cache[date_string]["tmean"]

    # ----- Yesterday PRISM -----

    yesterday = (
        datetime.strptime(date_string, "%Y%m%d")
        - timedelta(days=1)
    ).strftime("%Y%m%d")

    if yesterday in prism_cache:
        ppt_yesterday = prism_cache[yesterday]["ppt"]
    else:
        ppt_yesterday = 0.0

    # ----- Weekly Precip -----

    ppt_per_sum = get_weekly_precip(
        prism_cache,
        date_string
    )

    # ----- Drainage Area -----

    DRNAREA = float(
        df_chars.loc["DRNAREA", "value"]
    )

def get_weekly_precip(prism_cache, date_string):
    """
    Returns total precip for date and previous 6 days.
    """

    current = datetime.strptime(date_string, "%Y%m%d")

    total = 0.0

    for i in range(7):

        d = (current - timedelta(days=i)).strftime("%Y%m%d")

        if d in prism_cache:
            total += prism_cache[d]["ppt"]

    return total

# This is only for values going into the regression equation CSV file!!!
def calculate_cn_for_calibration(df_chars):
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
        df_chars.loc["SSURGOD", "value"] * 87) / 100) + 2
    )

    Wet_CN = float(Norm_CN + 4)
    Dry_CN = float(Norm_CN - 4)

    if ppt_per_sum >= 2:
        Curve = Wet_CN
        print(f"Calculated wet curve number (CN) for the watershed: {Curve}")
        return Curve
    elif ppt_per_sum < 2 and ppt_per_sum > 1:
        Curve = Norm_CN
        print(f"Calculated normal curve number (CN) for the watershed: {Curve}")
        return Curve
    elif ppt_per_sum <= 1:
        Curve = Dry_CN
        print(f"Calculated dry curve number (CN) for the watershed: {Curve}")
        return Curve
    else:
        pass

def calculate_ia_for_calibration(df_chars):
    '''
    ---IA CALCULATION---
    '''


    if "BSLDEM30FT" in df_chars.index:
        BSLDEM30FT = float(df_chars.loc["BSLDEM30FT", "value"])
        if BSLDEM30FT > 10 and BSLDEM30FT <= 30:
            Ia = 0.2
        elif BSLDEM30FT > 30 and BSLDEM30FT <= 45:
            Ia = 0.22

    Norm_Ia = Ia + -.02
        
    Wet_Ia = float(Norm_Ia + 0.04)
    Dry_Ia = float(Norm_Ia - 0.04)
        
    if ppt_per_sum >= 2:
        IntialAbstraction = Wet_Ia
        print(f"Calculated wet initial abstraction (Ia) for the watershed: {IntialAbstraction}")
        return IntialAbstraction
    elif ppt_per_sum < 2 and ppt_per_sum > 1:
        IntialAbstraction = Norm_Ia
        print(f"Calculated normal initial abstraction (Ia) for the watershed: {IntialAbstraction}")
        return IntialAbstraction
    elif ppt_per_sum <= 1:
        IntialAbstraction = Dry_Ia
        print(f"Calculated dry initial abstraction (Ia) for the watershed: {IntialAbstraction}")
        return IntialAbstraction
    else:
        pass

'''Adjustment factor calculation for the CN based on the month of the year and yesterday's precipitation'''    
def retrieve_month(date_string):
    """
    Extracts the month from the ENDDATE string in YYYYMMDD format.
    """
    return int(date_string[4:6])
  
def calculate_daily_adjustment(month, ppt_yesterday):
    if month in [5, 6, 7, 8, 9]:
        et_loss = -0.08
    else:
        et_loss = -0.02

    priming_bonus = 0.04 if ppt_yesterday > 0.5 else 0.0

    return et_loss + priming_bonus

GAUGES = {
    "linville": "02138500",
    "catawba":  "02137727"
}

GAUGE_DATA = {}

for gauge_name, site_code in GAUGES.items():

    print(f"Building watershed for {gauge_name}")

    GAUGE_DATA[gauge_name] = build_gauge_data(
        site_code
    )

def build_calibration_row(date_string, site_name, site_code):
    """
    makes rows for csv
    """

    gauge_data = GAUGE_DATA[site_name]

    global prism_cache
    global df_chars

    prism_cache = gauge_data["prism_cache"]
    df_chars = gauge_data["df_chars"]

    # update PRISM state for this day
    load_day_variables(date_string, prism_cache)

    # CN + IA
    cn_value = calculate_cn_for_calibration(df_chars)
    ia_value = calculate_ia_for_calibration(df_chars)

    # ADJ
    adj_value = calculate_daily_adjustment(
    retrieve_month(date_string),
    ppt_yesterday
    )

    # streamflow
    flow = get_daily_avg_streamflow(
        site_no=site_code,
        date_string=date_string
    )

    return {
        "gauge": site_name,
        "day": date_string,
        "drainage_area": float(df_chars.loc["DRNAREA", "value"]),
        "daily_precip": ppt_daily,
        "weekly_precip": ppt_per_sum,
        "IA value": ia_value,
        "CN value": cn_value,
        "ADJ value": adj_value,
        "streamflow value": flow
    }

def build_calibration_csv(start_date, end_date, output_file):
    """
    makes csv
    """

    rows = []

    current = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")

    while current <= end:

        date_string = current.strftime("%Y%m%d")

        for gauge_name, site_code in GAUGES.items():

            print(f"Processing {gauge_name} {date_string}")

            try:
                row = build_calibration_row(
                    date_string=date_string,
                    site_name=gauge_name,
                    site_code=site_code
                )
                rows.append(row)

            except Exception as e:
                print(f"Skipped {gauge_name} {date_string}: {e}")

        current += timedelta(days=1)

    df = pd.DataFrame(rows)

    df.to_csv(output_file, index=False)

    print(f"\nSaved {len(df)} rows to {output_file}")

    return df

df = build_calibration_csv(
    start_date=start_date,
    end_date=end_date,
    output_file = os.path.join(
    os.path.expanduser("~"),
    "Documents",
    "calibration_output.csv"
)
)