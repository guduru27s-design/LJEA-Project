# - - - - - PY IMPORTS - - - - -

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

# - - - - - FUNCTION IMPORTS - - - - -

import get_site_info
import build_gauge_data
import get_daily_avg_streamflow
import delineate_watershed
import extract_watershed_polygon
import get_basin_prism
import get_basin_characteristics
import build_prism_cache
import load_day_variables
import get_weekly_precip
import calculate_cn_for_calibration
import calculate_ia_for_calibration
import retrieve_month
import calculate_daily_adjustment
import build_calibration_row
import build_calibration_csv

# - - - - - ASSIGNING VARIABLES - - - - -

'''
COMMENT
'''

start_date = "20250525"
end_date = "20250526"

SITE_CODES = [
    "02138500",  # LINVILLE RIVER NEAR NEBO, NC
    "02137727",  # CATAWBA R NR PLEASANT GARDENS, NC
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

GAUGES = {
    "linville": "02138500",
    "catawba":  "02137727"
}

GAUGE_DATA = {}

# - - - - - FUNCTION CALLING - - - - -

'''
COMMENT
'''

print("\nSite 1 Information:")
LINVILLE_LIST = get_site_info(SITE_CODES[0])
print(LINVILLE_LIST)

print("\nSite 2 Information:")
CATAWBA_LIST = get_site_info(SITE_CODES[1])
print(CATAWBA_LIST)

'''
COMMENT
'''

for gauge_name, site_code in GAUGES.items():

    print(f"Building watershed for {gauge_name}")

    GAUGE_DATA[gauge_name] = build_gauge_data(
        site_code
    )

'''
COMMENT
'''

df = build_calibration_csv(
    start_date=start_date,
    end_date=end_date,
    output_file = os.path.join(
    os.path.expanduser("~"),
    "Documents",
    "calibration_output.csv"
)
)
