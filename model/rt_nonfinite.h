#ifndef RT_NONFINITE_H
#define RT_NONFINITE_H

#include "rtwtypes.h"

extern real_T rtInf;
extern real_T rtMinusInf;
extern real_T rtNaN;

extern void rt_InitInfAndNaN(void);
extern boolean_T rtIsInf(real_T x);
extern boolean_T rtIsNaN(real_T x);

#endif