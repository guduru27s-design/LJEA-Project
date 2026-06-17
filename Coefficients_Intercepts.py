import pandas as pd
from sklearn.linear_model import LinearRegression

def new_csv(csv_file):
    df = pd.read_csv(csv_file)

    CN = 50
    S = (1000 / CN) - 10
    ADJ= 0.25

    new_df = pd.DataFrame()


    new_df["Runoff"] = (
        (((df["Daily Precipitation"] - 0.2 * S) ** 2) /
        (df["Daily Precipitation"] - 0.2 * S + S))
        / 12 * (df["DA"] * 27878400) / 86400
        )


    new_df["Antecedant Precip"] = (
            (df["Weekly Precipitation"] / 12)
            * (df["DA"] * 27878400)
            / 86400
        )
        
    new_df["Interflow"] = (((ADJ + df["Daily Precipitation"]) * 2323200 * df["DA"]) / 86400)

    new_df["Streamflow"] = df["Streamflow"]

    return new_df


def make_regression(new_df):

    X = new_df[["Runoff", "Antecedant Precip", "Interflow"]]
    Y = new_df["Streamflow"]

    lr = LinearRegression()
    lr.fit(X, Y)

    return lr.coef_, lr.intercept_

new_csv= new_csv(r"C:\Users\GUDUR\Downloads\fake spreadsheet - Sheet1 (1).csv")
regression_results= make_regression(new_csv)

print("B1 (Runoff):", regression_results[0][0])
print("B2 (Antecedant Precip):", regression_results[0][1])
print("B3 (Interflow):", regression_results[0][2])
print("B0 (Intercept):", regression_results[1])
