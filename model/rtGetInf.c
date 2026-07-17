#include "rtGetInf.h"
#include "rt_nonfinite.h"

real_T rtGetInf(void) { return rtInf; }
real32_T rtGetInfF(void) { return (real32_T)rtInf; }
real_T rtGetMinusInf(void) { return rtMinusInf; }
real32_T rtGetMinusInfF(void) { return (real32_T)rtMinusInf; }