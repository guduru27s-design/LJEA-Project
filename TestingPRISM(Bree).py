import requests

# 1. Define your parameters
latitude = 45.0000
longitude = -123.0000
element = "tmax"  # Options: ppt (precip), tmin, tmax, tmean
date_string = "20260601"  # YYYYMMDD format (or YYYYMM for monthly)

# 2. PRISM API URL
# We append ?json=true to get a clean data format back
url = f"https://services.nacse.org/prism/data/get/releaseDate/us/4km/{element}/{date_string}?json=true"

try:
    # 3. Make the request
    response = requests.get(url)
    response.raise_for_status()  # Check for errors
    
    # 4. Parse the data
    data = response.json()
    print("Data retrieved successfully!")

    '''

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
    print(f"An error occurred: {e}")
