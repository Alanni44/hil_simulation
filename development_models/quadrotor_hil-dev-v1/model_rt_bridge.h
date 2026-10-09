#ifndef DEVELOPMENT_QUAD_MODEL_RT_BRIDGE_H
#define DEVELOPMENT_QUAD_MODEL_RT_BRIDGE_H

#include "development_quad_model.h"

typedef DevelopmentQuadU ModelU_t;
typedef DevelopmentQuadY ModelY_t;
#define MODEL_U_T_DEFINED 1
#define MODEL_Y_T_DEFINED 1
#define MODEL_INIT_FN development_quad_initialize
#define MODEL_STEP_FN development_quad_step
#define MODEL_TERM_FN development_quad_terminate
#define MODEL_U_VAR development_quad_U
#define MODEL_Y_VAR development_quad_Y

#endif
