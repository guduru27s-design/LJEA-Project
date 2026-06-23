import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_squared_error
import warnings
# Suppress the specific matmul runtime warnings caused by the Mac NumPy bug
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*matmul.*")

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
        
    new_df["Interflow"] = (((df["ADJ value"] + df["daily_precip"]) * 2323200 * df["drainage_area"]) / 86400)
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
    interflow = ((Adjustments + ppt_daily) * 2323200 * DRNAREA) / 86400

    return (B1 * runoff) + (B2 * baseflow) + (B3 * interflow) + B0

# Test single prediction
streamflow_pred = regression_formula(
    0.00025333411, 0.001078417206, 127, 53.519594, -0.02, 0.16, 
    B0, B1, B2, B3
)
print(f"\nPredicted Streamflow for single point: {streamflow_pred:.6f}")

# --- Diagnostics ---
X = new_df[["Runoff", "Antecedent Precip", "Interflow"]]
Y = new_df["Streamflow"]
Y_pred_all = lr.predict(X)
residuals_all = Y - Y_pred_all

# Residual Plot
plt.figure(figsize=(8, 5))
plt.scatter(Y_pred_all, residuals_all, alpha=0.6)
plt.axhline(y=0, color="red", linestyle="--")
plt.title("Residual Plot")
plt.xlabel("Predicted Streamflow")
plt.ylabel("Residuals")
plt.grid(True)
plt.show()

mse = mean_squared_error(Y, Y_pred_all)
print(f"Overall Mean Squared Error: {mse:.6f}")
