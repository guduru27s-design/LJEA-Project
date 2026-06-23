# This is for calculating the regression coefficients and calculating streamflow for inputs.

# This file will contain all function definitions for the project.
# Must be downloaded along with regression calibration and predictive model code to run all.

# Imports:
import pandas as pd
import statsmodels.formula.api as smf
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import requests
import json
import copy
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
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score
import csv

# Website URLs:
NWIS_SITE_URL     = "https://waterservices.usgs.gov/nwis/site/"
NWIS_IV_URL       = "https://waterservices.usgs.gov/nwis/iv/"
SS_DELINEATE_URL  = "https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/{region}"
SS_BASIN_CHAR_URL = "https://streamstats.usgs.gov/ss-hydro/v1/basin-characteristics/calculate"

# Functions for Sites:
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
def build_gauge_data(site_code):
    ''' Get gauge data for delineation '''
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
    #Get daily average streamflow from a site for date. 
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

# Functions for basins:
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


# PRISM Functions:
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

'''note: extract PRISM values from the list and turn them into variables we can pull from for regression
IF YOU ACTUALLY CALL THE prism_data, IT WILL PRINT OUT THE FULL DICT WITH ALL 4 ELEMENTS CONVERTED (ppt, tmin, tmax, tmean)'''


def save_end_day_prism():
    global ppt_daily, tmin_daily, tmax_daily, tmean_daily

    get_prism_for_date(ENDDATE)

    ppt_daily = ppt_day
    tmin_daily = tmin_f
    tmax_daily = tmax_f
    tmean_daily = tmean_f

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


# CN and Ia for Calibration:
def calculate_cn_for_calibration(df_chars):
    '''
    ---CN CALCULATION for Calibration---
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
    ---IA CALCULATION for Calibration---
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

# CN and Ia for Predicting Streamflow:
def calculate_cn(df_chars, SLOPECORRECTIONCN):
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

def calculate_ia(df_chars, SLOPECORRECTIONIA):
    '''
    ---IA CALCULATION---
    '''


    if "BSLDEM30FT" in df_chars.index:
        BSLDEM30FT = float(df_chars.loc["BSLDEM30FT", "value"])
        if BSLDEM30FT > 10 and BSLDEM30FT <= 30:
            Ia = 0.2
        elif BSLDEM30FT > 30 and BSLDEM30FT <= 45:
            Ia = 0.22

    if SLOPECORRECTIONIA != 0.0:
        Norm_Ia = Ia + SLOPECORRECTIONIA
        
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

# Calculate Adjustment Factor:
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
    
    adjustments = et_loss + priming_bonus
    
    print(f"Calculated daily adjustment: {adjustments}")

    return adjustments

# For Calibration and CSV: 
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

# Get week dates for PRISM:
def get_period(date_string):
    global STARTDATE, ENDDATE
    
    '''
    Takes the day the user inputted and determines the period range for the week before it (containing the inputted day and 6 days before it)
    '''
    STARTDATE = (datetime.strptime(date_string, "%Y%m%d") - timedelta(days=6)).strftime("%Y%m%d")
    ENDDATE = date_string
    return STARTDATE, ENDDATE

# Regression Functions:
def new_csv(csv_file):
    df = pd.read_csv(csv_file)
    new_df = pd.DataFrame()
    
    S = (1000 / df["CN value"]) - 10
    
    # Added 1e-9 to prevent division by zero if the denominator hits exactly 0
    denominator = df["daily_precip"] + (1 - df["IA value"]) * S + 1e-9
    
    calc_runoff = (
        (((df["daily_precip"] - df["IA value"] * S) ** 2) / denominator)
        / 12 * (df["drainage_area"] * 27878400) / 86400
    )
    
    new_df["Runoff"] = np.where(df["daily_precip"] <= (df["IA value"] * S), 0, calc_runoff)
            
    new_df["Antecedent Precip"] = (
        (df["weekly_precip"] / 12) * (df["drainage_area"] * 27878400) / 86400
    )
        
    # Calculate the raw interflow as you normally do
    calc_interflow = (((df["ADJ value"] + df["daily_precip"]) * 2323200 * df["drainage_area"]) / 86400)

    # Force any value below 0 to be exactly 0
    new_df["Interflow"] = np.maximum(0, calc_interflow)
    new_df["Streamflow"] = df["streamflow value"]

    # CRITICAL: Clean out any lingering infinity or NaN values
    new_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    new_df.dropna(inplace=True)

    return new_df

def make_regression(new_df):
    X = new_df[["Runoff", "Antecedent Precip", "Interflow"]]
    Y = new_df["Streamflow"]
    
    X_train, X_test, Y_train, Y_test = train_test_split(X, Y, test_size=0.2, random_state=42)

    lr = LinearRegression()
    lr.fit(X_train, Y_train)

    B1, B2, B3 = lr.coef_
    B0 = lr.intercept_
    
    R2 = r2_score(Y_test, lr.predict(X_test))

    return B1, B2, B3, B0, R2, lr

def regression_formula(ppt_daily, ppt_per_sum, DRNAREA, Curve, Adjustments, InitialAbstraction, B0, B1, B2, B3): 
    S = (1000 / Curve) - 10
      
    if ppt_daily <= (InitialAbstraction * S):
        runoff = 0
    else:
        formula1 = (ppt_daily - InitialAbstraction * S) ** 2
        formula2 = ppt_daily + (1 - InitialAbstraction) * S
        formula3 = DRNAREA * 27878400
        runoff = (((formula1 / formula2) / 12) * formula3) / 86400

    baseflow = ((ppt_per_sum / 12) * (DRNAREA * 27878400)) / 86400
    raw_interflow = ((Adjustments + ppt_daily) * 2323200 * DRNAREA) / 86400
    interflow = max(0, raw_interflow) # Using Python's built-in max() for a single number
    finalFormula = (B1 * runoff) + (B2 * baseflow) + (B3 * interflow) + B0
    return finalFormula
