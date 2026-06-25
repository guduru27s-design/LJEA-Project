import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_squared_error
import warnings
# Suppress the specific matmul runtime warnings caused by the Mac NumPy bug
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*matmul.*")
"""
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
THEDAY = input("Enter the date you want to look for (YYYYMMDD): ")

SLOPECORRECTIONCN = input("What is the slope correction factor for the CN? (Enter a number, or leave blank for no correction): ")
if SLOPECORRECTIONCN:
    SLOPECORRECTIONCN = float(SLOPECORRECTIONCN)
else:    SLOPECORRECTIONCN = 0.0
SLOPECORRECTIONIA = input("What is the slope correction factor for the initial abstraction ratio (Ia)? (Enter a number, or leave blank for no correction): ")
if SLOPECORRECTIONIA:
    SLOPECORRECTIONIA = float(SLOPECORRECTIONIA)
else:    SLOPECORRECTIONIA = 0.0

# get week code
def get_period(date_string):
    global STARTDATE, ENDDATE
    
    '''
    Takes the day the user inputted and determines the period range for the week before it (containing the inputted day and 6 days before it)
    '''
    STARTDATE = (datetime.strptime(date_string, "%Y%m%d") - timedelta(days=6)).strftime("%Y%m%d")
    ENDDATE = date_string
    return STARTDATE, ENDDATE

print("Week Analyzed (LATER):")
print(get_period(THEDAY))

# MIAS CODE - - - -

SITE_CODES = [
    "02138500",  # LINVILLE RIVER NEAR NEBO, NC
    "02137727",  # CATAWBA R NR PLEASANT GARDENS, NC
]

def get_site_info(site_code: str) -> dict:
    """"""
    Returns {'site_code', 'site_name', 'lat', 'lon', 'state', 'huc'} for a USGS gauge.
    Raises ValueError if the site is not found.
    """"""
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
print(get_site_info(SITE_CODES[0]))
print("\nSite 2 Information:")
print(get_site_info(SITE_CODES[1]))

# - - - - - -

def get_daily_avg_streamflow_original(site_no, date_string):
    '''
    Returns average streamflow (cfs) for a single day.

    site_no: USGS site number (string)
    date_string: YYYYMMDD
    '''

    start_date = datetime.strptime(date_string, "%Y%m%d")
    end_date = start_date + timedelta(days=1)

    params = {
        "format": "json",
        "sites": site_no,
        "startDT": start_date.strftime("%Y-%m-%d"),
        "endDT": end_date.strftime("%Y-%m-%d"),
        "parameterCd": "00060"   # discharge
    }

    r = requests.get(NWIS_IV_URL, params=params)
    r.raise_for_status()

    data = r.json()

    values = (
        data["value"]["timeSeries"][0]
        ["values"][0]["value"]
    )

    flows = []

    for point in values:
        if point["value"] != "":
            flows.append(float(point["value"]))

    if len(flows) == 0:
        return None

    return np.mean(flows)

daily_flow = get_daily_avg_streamflow_original(
    site_no="02137727",
    date_string=ENDDATE
)

print("END DAY STREAMFLOW:")

print(f"Average flow: {daily_flow:.2f} cfs")

# - - - - - -

def delineate_watershed(lat: float, lon: float, region: str) -> dict:
    '''
    Calls the StreamStats API to trace the watershed upstream of a point.

    Required inputs:
      lat    (float) — latitude in decimal degrees
      lon    (float) — longitude in decimal degrees
      region (str)   — two-letter state abbreviation, e.g. 'NC'

    Returns the full delineation response dict.
    This response is passed directly to get_basin_characteristics() in Step 4 —
    you do not need to modify it.

    '''
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
    '''
    Pulls global watershed geometry from StreamStats response.
    '''
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
    '''
    Basin-averaged PRISM values using StreamStats polygon.
    '''

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
    '''
    Computes basin characteristics for the watershed defined by a delineation response.

    Required input:
      delineation_response (dict) — the full JSON dict returned by delineate_watershed()

    Optional input:
      char_codes (list of str) — specific characteristic codes to compute,
                                 e.g. ['DRNAREA', 'ELEV', 'LC11FOREST']
                                 Pass None to fetch all available characteristics.

    Returns a list of dicts, one per characteristic:
      [{'code': 'DRNAREA', 'name': 'Drainage area', 'value': 23.4, 'unit': 'sq mi'}, ...]
    '''
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

    # note: extract PRISM values from the list and turn them into variables we can pull from for regression
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

Curve = calculate_cn(df_chars, SLOPECORRECTIONCN)

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

InitialAbstraction = calculate_ia(df_chars, SLOPECORRECTIONIA)

'''Adjustment factor calculation for the CN based on the month of the year and yesterday's precipitation'''    
def retrieve_month(ENDDATE):
    '''
    Extracts the month from the ENDDATE string in YYYYMMDD format.
    '''
    return int(ENDDATE[4:6])
month = retrieve_month(ENDDATE)
  
def calculate_daily_adjustment(month, ppt_yesterday):
    if month in [5, 6, 7, 8, 9]:
        et_loss = -0.08
    else:
        et_loss = -0.02

    priming_bonus = 0.04 if ppt_yesterday > 0.5 else 0.0

    adjustments = et_loss + priming_bonus

    print(f"Calculated daily adjustment for {THEDAY}: {adjustments}")

    return adjustments

Adjustments = (calculate_daily_adjustment(month, ppt_yesterday))
DRNAREA = float(df_chars.loc["DRNAREA", "value"])
"""

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

# --- Execution ---

# Load and process data
# Note: Ensure these file paths are correct for your local environment
input_path = "/Users/smgallop08/Downloads/Final Spreadsheet - Sheet1 (1).csv"
output_path = "/Users/smgallop08/Documents/calibration_outputs.csv"

new_df = new_csv(input_path)
new_df.to_csv(output_path, index=False)
print(new_df[["Runoff", "Antecedent Precip", "Interflow", "Streamflow"]].describe())
# Train model
B1, B2, B3, B0, R2, lr = make_regression(new_df)

print(f"B1 (Runoff): {B1:.6f}")
print(f"B2 (Antecedent Precip): {B2:.6f}")
print(f"B3 (Interflow): {B3:.6f}")
print(f"B0 (Intercept): {B0:.6f}")
print(f"R squared: {R2:.4f}")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score

def plot_pairwise_slopes(df):
    """
    Creates isolated pairwise regression plots for each feature 
    against the target Streamflow variable.
    """
    features = ["Runoff", "Antecedent Precip", "Interflow"]
    target = "Streamflow"
    
    # Setup row of subplots sharing the same Y-axis for scaling consistency
    fig, axes = plt.subplots(1, len(features), figsize=(16, 5), sharey=True)
    
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c'] # Distinct colors for each plot
    
    for i, col in enumerate(features):
        sns.regplot(
            x=df[col], 
            y=df[target], 
            ax=axes[i], 
            color=colors[i],
            scatter_kws={'alpha': 0.4, 'edgecolor': 'w'}, 
            line_kws={'color': 'black', 'lw': 2}
        )
        axes[i].set_title(f'{target} vs {col}', fontsize=12, fontweight='bold')
        axes[i].set_xlabel(col, fontsize=10)
        axes[i].grid(True, linestyle='--', alpha=0.5)
        
    axes[0].set_ylabel(target, fontsize=10)
    plt.suptitle("Pairwise Linear Regression Slopes", fontsize=14, y=1.05, fontweight='bold')
    plt.tight_layout()
    plt.show()

plot_pairwise_slopes(new_df)
# --- Single Point Prediction Function ---

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

    return ((B1 * runoff) ** 2) + (B2 * baseflow) + (B3 * interflow) + B0


'''
# Test single prediction
streamflow_pred = regression_formula(
    0.00025333411, 0.001078417206, 127, 53.519594, -0.02, 0.16, 
    B0, B1, B2, B3
)
print(f"\nPredicted Streamflow for single point: {streamflow_pred:.6f}")
'''


# --- Diagnostics ---
X = new_df[["Runoff", "Antecedent Precip", "Interflow"]]
Y = new_df["Streamflow"]
Y_pred_all = lr.predict(X)
residuals_all = Y - Y_pred_all

from statsmodels.stats.outliers_influence import variance_inflation_factor

# Select your independent variables
X = new_df[["Runoff", "Antecedent Precip", "Interflow"]]

# Calculate VIF for each feature
vif_data = pd.DataFrame()
vif_data["Feature"] = X.columns
vif_data["VIF"] = [variance_inflation_factor(X.values, i) for i in range(len(X.columns))]

print("\n--- Variance Inflation Factor (VIF) ---")
print(vif_data)


# Residual Plot
plt.figure(figsize=(8, 5))
plt.scatter(Y_pred_all, residuals_all, alpha=0.6)
plt.axhline(y=0, color="red", linestyle="--")
plt.title("Residual Plot")
plt.xlabel("Predicted Streamflow")
plt.ylabel("Residuals")
plt.grid(True)
plt.show()

# --- Observed vs. Predicted Plot ---
plt.figure(figsize=(8, 6))

# --- Observed vs. Predicted Plot (Actual Line of Best Fit) ---
plt.figure(figsize=(8, 6))

# 1. Scatter plot of actual vs predicted values
plt.scatter(Y, Y_pred_all, alpha=0.6, color="blue", label="Data Points")

# 2. Calculate the ACTUAL line of best fit (degree 1 polynomial = linear)
# polyfit returns [slope, intercept]
slope, intercept = np.polyfit(Y, Y_pred_all, 1)

# Create x values spanning your actual data range to draw the line
x_vals = np.linspace(Y.min(), Y.max(), 100)
y_vals = slope * x_vals + intercept

# Plot the actual trendline
plt.plot(x_vals, y_vals, color="darkorange", linestyle="-", linewidth=2.5, 
         label=f"Line of Best Fit (y = {slope:.2f}x + {intercept:.2f})")
perfect_line = np.linspace(min(Y.min(), Y_pred_all.min()), max(Y.max(), Y_pred_all.max()), 100)
plt.plot(perfect_line, perfect_line, color="red", linestyle="--", linewidth=2, label="Perfect Fit (1:1)")

# 3. Graph labels and styling
plt.title(f"Observed vs. Predicted Streamflow (R² = {R2:.4f})", fontsize=14)
plt.xlabel("Actual Streamflow (cfs)", fontsize=12)
plt.ylabel("Predicted Streamflow (cfs)", fontsize=12)
plt.legend()
plt.grid(True, linestyle=":", alpha=0.6)

plt.show()

# --- Coefficients Bar Chart ---
plt.figure(figsize=(8, 5))

features = ["Runoff (B1)", "Antecedent Precip (B2)", "Interflow (B3)"]
coefficients = [B1, B2, B3]

# Create bar plot
sns.barplot(x=features, y=coefficients, palette="viridis")

# Graph labels and styling
plt.axhline(0, color="black", linewidth=0.8) # line at 0
plt.title("Regression Coefficients (Feature Weights)", fontsize=14)
plt.ylabel("Coefficient Value", fontsize=12)
plt.xlabel("Hydrological Predictors", fontsize=12)
plt.grid(axis="y", linestyle=":", alpha=0.6)

plt.show()

# --- Time-Series Tracking Plot ---
plt.figure(figsize=(12, 5))

# Reset index to treat rows as sequential timesteps/days
plt.plot(new_df.index, Y, label="Actual Streamflow", color="black", alpha=0.8, linewidth=1.5)
plt.plot(new_df.index, Y_pred_all, label="Predicted Streamflow", color="orange", alpha=0.8, linestyle="-")

# Graph labels and styling
plt.title("Streamflow Hydrograph Estimation Comparison", fontsize=14)
plt.xlabel("Data Point Index / Chronology", fontsize=12)
plt.ylabel("Streamflow (cfs)", fontsize=12)
plt.legend()
plt.grid(True, alpha=0.3)

plt.show()

import scipy.stats as stats

# Assuming residuals_all = Y - Y_pred_all is already calculated
plt.figure(figsize=(6, 6))
stats.probplot(residuals_all, dist="norm", plot=plt)
plt.title("Normal Q-Q Plot of Residuals")
plt.grid(True, linestyle=":", alpha=0.6)
plt.show()

import seaborn as sns
import matplotlib.pyplot as plt

# Using a built-in dataset for demonstration


from sklearn.model_selection import cross_val_score

# Calculate 5-fold cross-validation R² scores
cv_scores = cross_val_score(lr, X, Y, cv=5, scoring='r2')

print("\n--- 5-Fold Cross-Validation ---")
print(f"All R² Scores: {cv_scores}")
print(f"Mean CV R² Score: {cv_scores.mean():.4f}")
print(f"Standard Deviation: {cv_scores.std():.4f}")


import statsmodels.api as sm

# statsmodels requires explicitly adding a constant (intercept) term
X_with_constant = sm.add_constant(X)

# Fit Ordinary Least Squares (OLS) regression
ols_model = sm.OLS(Y, X_with_constant).fit()

# Print the comprehensive statistical summary
print(ols_model.summary())

mse = mean_squared_error(Y, Y_pred_all)
print(f"Overall Mean Squared Error: {mse:.6f}")
