def regression_formula(precipitationDaily, precipitationWeekly, DA, Ia, CN): 
  B0= 1
  B1= 1
  B2= 1
  B3= 1
  formula1= (precipitationDaily-Ia * ((1000/CN)-10))**2
  formula2= precipitationDaily + (1-Ia)* ((1000/CN)-10)
  formula3= DA * (27878400)
  finalFormula= (B1*((formula1/formula2)/12)*(formula3)+ B2*(precipitationWeekly)+B0)/86400
  return finalFormula

value= regression_formula(4,4,4,4,4)
print(value)

