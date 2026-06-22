#Import section 
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score
import numpy as np
"""
This function create a new csv file filling the spreadsheet with calculated values and the headers are runoff, antecedant precipitation, interflow, and streamflow
Parameters:
- csv file
Returns:
- new csv file with calculate values
"""

def new_csv(csv_file):
    df = pd.read_csv(csv_file)

    new_df = pd.DataFrame()
    
    calc_runoff= (
                (((df["daily_precip"] - df["IA value"] * ((100/ df["CN value"]) -10)) ** 2) /
                (df["daily_precip"] - df["IA value"] * ((100/ df["CN value"]) -10) ))
                / 12 * (df["drainage_area"] * 27878400) / 86400
            )
    
    new_df["Runoff"]= np.where(df["daily_precip"] <= df["IA value"], 0, calc_runoff)
            
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
    
    X_train, X_test, Y_train, Y_test = train_test_split(X, Y, test_size=0.2, random_state=42)

    lr = LinearRegression()
    lr.fit(X_train, Y_train)

    B1= lr.coef_[0]
    B2= lr.coef_[1]
    B3= lr.coef_[2]
    B0= lr.intercept_
    
    R2= r2_score(Y_test, lr.predict(X_test))

    return B1, B2, B3, B0, R2


new_csv= new_csv(r"C:\Users\GUDUR\Downloads\calibration_output.csv")
B1, B2, B3, B0, R2= make_regression(new_csv)

print("B1 (Runoff):", B1)
print("B2 (Antecedant Precip):", B2)
print("B3 (Interflow):", B3)
print("B0 (Intercept):", B0)
print("R squared:", R2)
