
def regression_formula(ppt_daily, ppt_per_sum, DRNAREA, Curve, Adjustments, InitialAbstraction, B0, B1, B2, B3): 
  S = (1000 / Curve) - 10
  B0 = B0
  B1 = B1
  B2 = B2
  B3 = B3
      
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

streamflow = regression_formula(0.04589667722,0.04589667722,67,55.17338,-0.02,0.16, B0, B1, B2, B3)
print(streamflow)
