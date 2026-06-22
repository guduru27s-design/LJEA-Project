
#Import section 
import pandas as pd
from sklearn.linear_model import LinearRegression
"""
This function create a new csv file filling the spreadsheet with calculated values and the headers are runoff, antecedant precipitation, interflow, and streamflow
Parameters:
- csv file
Returns:
- new csv file with calculate values
"""
def new_csv(csv_file):
    df = pd.read_csv(csv_file)

    CN = 50
    S = (1000 / CN) - 10
    ADJ= 0.25

    new_df = pd.DataFrame()


    new_df["Runoff"] = (
        (((df["daily_precip"] - df["IA value"] * ((100/ df["CN value"]) -10)) ** 2) /
        (df["daily_precip"] - (1-df["IA value"]) * ((100/ df["CN value"]) -10) ))
        / 12 * (df["drainage_area"] * 27878400) / 86400
        )


    new_df["Antecedant Precip"] = (
            (df["weekly_precip"] / 12)
            * (df["drainage_area"] * 27878400)
            / 86400
        )
        
    new_df["Interflow"] = (((df["ADJ value"] + df["daily_precip"]) * 2323200 * df["drainage_area"]) / 86400)

    new_df["Streamflow"] = df["streamflow value"]
    

    return new_df


def make_regression(new_df):

    X = new_df[["Runoff", "Antecedant Precip", "Interflow"]]
    Y = new_df["Streamflow"]

    lr = LinearRegression()
    lr.fit(X, Y)
    
    B1= lr.coef_[0]
    B2= lr.coef_[1]
    B3= lr.coef_[2]
    B0= lr.intercept_

    return B1, B2, B3, B0


new_csv= new_csv(r"C:\Users\GUDUR\Downloads\finalized fake spreadsheet - Sheet1 (2).csv")
B1, B2, B3, B0= make_regression(new_csv)

print("B1 (Runoff):", B1)
print("B2 (Antecedant Precip):", B2)
print("B3 (Interflow):", B3)
print("B0 (Intercept):", B0)






