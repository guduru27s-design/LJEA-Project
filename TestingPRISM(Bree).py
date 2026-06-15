import io
import zipfile
import requests
import rasterio

# 1. Define your parameters
latitude = 35.6580
longitude = -82.0575
element = "tmin"  # Options: ppt (precip), tmin, tmax, tmean
date_string = "20260601"  # YYYYMMDD format (or YYYYMM for monthly)

# 2. PRISM API URL
# We append ?json=true to get a clean data format back
url = f"https://services.nacse.org/prism/data/get/us/4km/{element}/{date_string}"

try:
    # 3. Make the request to download map data (rastorio)
    print("connect to PRISM server to download map...")
    response = requests.get(url)
    response.raise_for_status()  # Check for errors
    print("data retrieved successfully!")

    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        #look inside zip folder and find the main map image file
        raster_file = [f for f in z.namelist() if f.endswith('.tif') or f.endswith('.bil')][0]

        with z.open(raster_file) as f:
            with rasterio.open(f) as src:
                #translate lat lon coords into map pixels
                row, col = src.index(longitude, latitude)
                band1 = src.read(1)  # Read the first band (temperature data)
                temperature = band1[row, col]  # Get the temperature value at the specified location
        
        unit = "mm" if element == "ppt" else "°C"

        print("PRISM DATA:")
        print(f"Date: {date_string}")
        print(f"Coordinates: {latitude}, {longitude}")
        print(f"Element: {element}")
        print(f"Value: {temperature} {unit}")

    '''
    data = response.json()
    temperature = data['data'][0]
    print(f"The temperature value is: {temperature}°C")
    print(data)

    IN THE DATA THAT IS PRINTED, HERE IS THE CONTEXT [1,2,3,4,5]

    1. The Target Weather Date you requested
    2. The Release Date (when OSU last updated this specific day's data)
    3. The Weather Element (Maximum Temperature)
    4. Grid Count (The stability version of the data file)
    5. The actual Direct Download Link to fetch the full map file for that day

    '''
    # THIS ONLY TELLS YOU THE TYPE OF DATA WE'RE LOOKING FOR (AKA MAX TEMPERATURE)
    # print(data[2])

    '''
    
    To see the data of the data, we use the 'data' KEY from the API to look at the
    actual value of the element that popped up in the reponse list
    
    '''
    
except requests.exceptions.RequestException as e:
    print(f"An error occurred while downloading: {e}")
except IndexError:
    print("Error: Could not find the climate map image inside the downloaded package.")
except Exception as e:
    print(f"An error occurred while extracting the pixel value: {e}")
