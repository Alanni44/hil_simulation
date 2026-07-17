#include "rt_nonfinite.h"
#include <math.h>

real_T rtInf = (real_T)INFINITY;
real_T rtMinusInf = (real_T)-INFINITY;
real_T rtNaN = (real_T)NAN;

void rt_InitInfAndNaN(void) {}
boolean_T rtIsInf(real_T x) { return (boolean_T)(isinf(x) != 0); }
boolean_T rtIsNaN(real_T x) { return (boolean_T)(isnan(x) != 0); }