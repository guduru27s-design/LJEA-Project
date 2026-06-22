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

