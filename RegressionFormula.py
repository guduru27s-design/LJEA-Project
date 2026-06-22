def regression_formula(ppt_daily, ppt_per_sum, DRNAREA, CN, ADJ, B0, B1, B2, B3): 
  S= (1000/CN) - 10
  B0= B0
  B1= B1
  B2= B2
  B3= B3
  formula1= (ppt_daily- 0.2 * S) ** 2
  formula2= ppt_daily -0.2 * S + S
  formula3= DRNAREA * 27878400
  runoff= (((formula1/formula2)/12) * formula3)/86400
  antecedentPrecip= ((ppt_per_sum/12)*(DRNAREA * 27878400))/86400
  interflow= ((ADJ + ppt_daily) * 2323200 * DRNAREA)/86400

  finalFormula= B1 * runoff + B2 * antecedentPrecip + B3 * interflow + B0
  return finalFormula

streamflow= regression_formula(9,8,7,6,5,4,3,2,1)
print(streamflow)

