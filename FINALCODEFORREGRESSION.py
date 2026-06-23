# Import section 
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns 

def new_csv(csv_file):
    df = pd.read_csv(csv_file)
    
    # Optional but highly recommended: clean up column name spaces
    df.columns = df.columns.str.strip()

    new_df = pd.DataFrame()
    
    calc_runoff = (
        (((df["daily_precip"] - df["IA value"] * ((1000/ df["CN value"]) - 10)) ** 2) /
        (df["daily_precip"] + (1 - df["IA value"]) * ((1000/ df["CN value"]) - 10) ))
        / 12 * (df["drainage_area"] * 27878400) / 86400
    )
    
    new_df["Runoff"] = np.where(df["daily_precip"] <= (df["IA value"] * ((1000 / df["CN value"]) - 10)), 0, calc_runoff)
            
    # Standardized spelling to "Antecedent" to prevent KeyErrors later
    new_df["Antecedent Precip"] = (
        (df["weekly_precip"] / 12)
        * (df["drainage_area"] * 27878400)
        / 86400
    )
        
    new_df["Interflow"] = (((df["ADJ value"] + df["daily_precip"]) * 2323200 * df["drainage_area"]) / 86400)
    new_df["Streamflow"] = df["streamflow value"]

    return new_df


def make_regression(df_input):
    X = df_input[["Runoff", "Antecedent Precip", "Interflow"]]
    Y = df_input["Streamflow"]
    
    X_train, X_test, Y_train, Y_test = train_test_split(X, Y, test_size=0.2, random_state=42)

    lr = LinearRegression()
    lr.fit(X_train, Y_train)

    B1 = lr.coef_[0]
    B2 = lr.coef_[1]
    B3 = lr.coef_[2]
    B0 = lr.intercept_
    
    R2 = r2_score(Y_test, lr.predict(X_test))

    return B1, B2, B3, B0, R2, X_test, Y_test, lr


def regression_formula(ppt_daily, ppt_per_sum, DRNAREA, Curve, Adjustments, InitialAbstraction, B0, B1, B2, B3): 
    S = (1000 / Curve) - 10
      
    formula1 = (ppt_daily - InitialAbstraction * S) ** 2
    formula2 = ppt_daily + (1 - InitialAbstraction) * S
    formula3 = DRNAREA * 27878400
    
    if ppt_daily <= (InitialAbstraction * S):
        runoff = 0
    else:
        runoff = (((formula1 / formula2) / 12) * formula3) / 86400
        
    baseflow = ((ppt_per_sum / 12) * (DRNAREA * 27878400)) / 86400
    interflow = ((Adjustments + ppt_daily) * 2323200 * DRNAREA) / 86400

    finalFormula = B1 * runoff + B2 * baseflow + B3 * interflow + B0
    return finalFormula

calibration_df = new_csv(r"C:\Users\GUDUR\Downloads\calibration_output.csv")
B1_cal, B2_cal, B3_cal, B0_cal, R2_cal, _, _, _ = make_regression(calibration_df)

print("--- Calibration Metrics ---")
print("R squared (Calibration):", R2_cal)

# Processing the final spreadsheet
new_df = new_csv(r"C:\Users\GUDUR\Downloads\Final Spreadsheet - Sheet1 (1).csv")
new_df.to_csv(r"C:\Users\GUDUR\Downloads\Final_Output.csv", index=False)

B1, B2, B3, B0, R2, X_test, Y_test, lr = make_regression(new_df)

print("\n--- Final Model Metrics ---")
print("B1 (Runoff):", B1)
print("B2 (Antecedent Precip):", B2)
print("B3 (Interflow):", B3)
print("B0 (Intercept):", B0)
print("R squared:", R2)


streamflow = regression_formula(0.00025333411, 0.001078417206, 127, 53.519594, -0.02, 0.16, B0, B1, B2, B3)
print("\nPredicted Single Streamflow:", streamflow)


X = new_df[["Runoff", "Antecedent Precip", "Interflow"]]
Y = new_df["Streamflow"]

Y_pred_all = lr.predict(X)
residuals_all = Y - Y_pred_all

plt.figure(figsize=(8,5))
plt.scatter(Y_pred_all, residuals_all)
plt.axhline(y=0, color="red", linestyle="--")
plt.title("Residual Plot")
plt.xlabel("Predicted Streamflow")
plt.ylabel("Residuals")
plt.grid(True)
plt.show()

mse = mean_squared_error(Y, Y_pred_all)
print("Mean Squared Error:", mse)
