# This is only for values going into the regression equation CSV file!!!
def calculate_cn_for_calibration(df_chars):
    '''
    ---CN CALCULATION---
    '''

    Norm_CN = float(
        ((int(df_chars.loc["LC11CRPHAY", "value"]) / 100) * 
        ((df_chars.loc["SSURGOA", "value"] * 68 + df_chars.loc["SSURGOB", "value"]
        * 76 + df_chars.loc["SSURGOC", "value"] * 
        83 + df_chars.loc["SSURGOD", "value"] * 87) / 100))
        + ((int(df_chars.loc["LC11FOREST", "value"]) / 100) *
        ((df_chars.loc["SSURGOA", "value"] * 30 + df_chars.loc["SSURGOB", "value"]
            * 60 + df_chars.loc["SSURGOC", "value"] *
            75 + df_chars.loc["SSURGOD", "value"] * 81) / 100))
        + ((int(df_chars.loc["LC11DEV", "value"]) / 100) * 
        ((df_chars.loc["SSURGOA", "value"] * 77 + 
            df_chars.loc["SSURGOB", "value"] * 85 + df_chars.loc["SSURGOC", "value"]
            * 90 + df_chars.loc["SSURGOD", "value"] * 92) / 100))
        + ((int(df_chars.loc["LC11GRASS", "value"]) / 100) * 
        ((df_chars.loc["SSURGOA", "value"] * 45 + df_chars.loc["SSURGOB", "value"]
            * 59 + df_chars.loc["SSURGOC", "value"] * 75 +
            df_chars.loc["SSURGOD", "value"] * 85) / 100))
        + ((int(df_chars.loc["LC11SHRUB", "value"]) / 100) * 
        ((df_chars.loc["SSURGOA", "value"] * 35 + df_chars.loc["SSURGOB", "value"]
            * 56 + df_chars.loc["SSURGOC", "value"] * 70 + 
            df_chars.loc["SSURGOD", "value"] * 77) / 100))
        + ((int(df_chars.loc["LC11IMP", "value"]) / 100) *
        ((df_chars.loc["SSURGOA", "value"] * 98 + df_chars.loc["SSURGOB", "value"]
            * 98 + df_chars.loc["SSURGOC", "value"] * 98 + 
            df_chars.loc["SSURGOD", "value"] * 98) / 100))
        - ((int(df_chars.loc["LC11BARE", "value"]) + 
            int(df_chars.loc["LC11WATER", "value"]) + 
            int(df_chars.loc["LC11WETLND", "value"])) / 100) * 
        ((df_chars.loc["SSURGOA", "value"] * 59 + df_chars.loc["SSURGOB", "value"] 
        * 72 + df_chars.loc["SSURGOC", "value"] * 82 +
        df_chars.loc["SSURGOD", "value"] * 87) / 100) + 2
    )

    Wet_CN = float(Norm_CN + 4)
    Dry_CN = float(Norm_CN - 4)

    if ppt_per_sum >= 2:
        Curve = Wet_CN
        print(f"Calculated wet curve number (CN) for the watershed: {Curve}")
        return Curve
    elif ppt_per_sum < 2 and ppt_per_sum > 1:
        Curve = Norm_CN
        print(f"Calculated normal curve number (CN) for the watershed: {Curve}")
        return Curve
    elif ppt_per_sum <= 1:
        Curve = Dry_CN
        print(f"Calculated dry curve number (CN) for the watershed: {Curve}")
        return Curve
    else:
        pass

calculate_cn_for_calibration(df_chars)

def calculate_ia_for_calibration(df_chars):
    '''
    ---IA CALCULATION---
    '''


    if "BSLDEM30FT" in df_chars.index:
        BSLDEM30FT = float(df_chars.loc["BSLDEM30FT", "value"])
        if BSLDEM30FT > 10 and BSLDEM30FT <= 30:
            Ia = 0.2
        elif BSLDEM30FT > 30 and BSLDEM30FT <= 45:
            Ia = 0.15

    if SLOPECORRECTIONIA != 0.0:
        Norm_Ia = Ia + -.02
        
    Wet_Ia = float(Norm_Ia + 0.04)
    Dry_Ia = float(Norm_Ia - 0.04)
        
    if ppt_per_sum >= 2:
        IntialAbstraction = Wet_Ia
        print(f"Calculated wet initial abstraction (Ia) for the watershed: {IntialAbstraction}")
        return IntialAbstraction
    elif ppt_per_sum < 2 and ppt_per_sum > 1:
        IntialAbstraction = Norm_Ia
        print(f"Calculated normal initial abstraction (Ia) for the watershed: {IntialAbstraction}")
        return IntialAbstraction
    elif ppt_per_sum <= 1:
        IntialAbstraction = Dry_Ia
        print(f"Calculated dry initial abstraction (Ia) for the watershed: {IntialAbstraction}")
        return IntialAbstraction
    else:
        pass

calculate_ia_for_calibration(df_chars)

'''Adjustment factor calculation for the CN based on the month of the year and yesterday's precipitation'''    
def retrieve_month(ENDDATE):
    """
    Extracts the month from the ENDDATE string in YYYYMMDD format.
    """
    return int(ENDDATE[4:6])
month = retrieve_month(ENDDATE)
  
def calculate_daily_adjustment(df):
    """
    df requires columns: 'month', 'daily_precip', 'yesterday_precip'
    Returns an array for the 'A' variable in Term 3
    """
    adjustments = []
    for idx, row in df.iterrows():
        # 1. Base canopy interception penalty (in inches)
        # Higher in summer, lower in winter
        if row['month'] in [5, 6, 7, 8, 9]:  # May - Sept
            et_loss = -0.08  # High summer evapotranspiration / interception
        else:
            et_loss = -0.02  # Low winter loss
            
        # 2. Yesterday's priming factor (Shallow storage memory)
        if row['ppt_yesterday'] > 0.5:
            priming_bonus = 0.04  # Soil is wet, boost the linear response
        else:
            priming_bonus = 0.0
            
        # Total adjustment depth for the day
        daily_A = et_loss + priming_bonus
        adjustments.append(daily_A)
        
    return adjustments

print(calculate_daily_adjustment(pd.DataFrame({
    'month': [month],
    'ppt_yesterday': [ppt_yesterday]
})))
