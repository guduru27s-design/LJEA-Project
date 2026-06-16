import io
import zipfile
import requests
import rasterio
from rasterio.io import MemoryFile

def get_daily(latitude, longitude, date_string):
    #gets PRISM data for a single day and returns tmin, tmax, tmean, ppt in a dictionary
    year = date_string[:4] #need this for url

    elements = ["ppt", "tmin", "tmax", "tmean"]
    results = {}

    for element in elements:

        url = (
        f"https://data.prism.oregonstate.edu/time_series/us/an/4km/{element}/daily/{year}/prism_{element}_us_25m_{date_string}.zip"
        )

        r = requests.get(url)
        r.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(r.content)) as z: #z is zipfile
        
            raster_file = [
                f for f in z.namelist()
                if f.endswith(".tif")
            ][0]

            with z.open(raster_file) as tif_file:
                tif_bytes = tif_file.read()
            with MemoryFile(tif_bytes) as memfile:
                with memfile.open() as src:
                    row, col = src.index(longitude, latitude)

                    band1 = src.read(1)

                    value = band1[row, col]

                    results[element] = float(value)

    return results

# - - - TESTING PART - - - 

data = get_daily(35.6580,-82.0575,"20200101")

print(data)

# - - - END TESTING PART - - - 

def get_monthly(latitude, longitude, date_string):
    #gets PRISM data for a single month and returns tmin, tmax, tmean, ppt in a dictionary
    year = date_string[:4] #need this for url
    month = date_string[4:6]
    date_string = f"{year}{month}" #need this for url for month since it can't be more than 6 characters!

    elements = ["ppt", "tmin", "tmax", "tmean"]
    results = {}

    for element in elements:

        url = (
        f"https://data.prism.oregonstate.edu/time_series/us/an/4km/{element}/monthly/{year}/prism_{element}_us_25m_{date_string}.zip"
        )

        r = requests.get(url)
        r.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(r.content)) as z: #z is zipfile
        
            raster_file = [
                f for f in z.namelist()
                if f.endswith(".tif")
            ][0]

            with z.open(raster_file) as tif_file:
                tif_bytes = tif_file.read()
            with MemoryFile(tif_bytes) as memfile:
                with memfile.open() as src:
                    row, col = src.index(longitude, latitude)

                    band1 = src.read(1)

                    value = band1[row, col]

                    results[element] = float(value)

    return results

# - - - TESTING PART - - - 

month_data = get_monthly(35.6580,-82.0575,"20200101")

print(month_data)

# - - - END TESTING PART - - - 