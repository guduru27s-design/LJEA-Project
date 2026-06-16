def regression_formula(precipitationDaily, precipitationWeekly, DA, CN, Interflow): 
  S= (1000/CN) - 10
  B0= 1
  B1= 1
  B2= 1
  B3= 1
  formula1= (precipitationDaily- 0.2 * S) ** 2
  formula2= precipitationDaily -0.2 * S + S
  formula3= DA * 27878400
  runoff= (((formula1/formula2)/12) * formula3)/86400
  antecedentPrecip= ((precipitationWeekly/12)*(DA * 27878400))/86400
  interflow= Interflow/86400

  finalFormula= B1 * runoff + B2 * antecedentPrecip + B3 * interflow + B0
  return finalFormula

value= regression_formula(9,8,7,6,5)
print(value)
