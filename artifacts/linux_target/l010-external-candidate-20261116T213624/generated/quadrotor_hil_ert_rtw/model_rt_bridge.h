#ifndef HIL_MODEL_RT_BRIDGE_H
#define HIL_MODEL_RT_BRIDGE_H
#include "quadrotor_hil.h"
typedef ExtU_quadrotor_hil_T ModelU_t;
#define MODEL_U_T_DEFINED 1
typedef ExtY_quadrotor_hil_T ModelY_t;
#define MODEL_Y_T_DEFINED 1
typedef DW_quadrotor_hil_T ModelDW_t;
#define MODEL_DW_T_DEFINED 1
#define HIL_MODEL_ID "quadrotor_hil"
#define MODEL_INIT_FN quadrotor_hil_initialize
#define MODEL_STEP_FN quadrotor_hil_step
#define MODEL_TERM_FN quadrotor_hil_terminate
#define MODEL_U_VAR quadrotor_hil_U
#define MODEL_Y_VAR quadrotor_hil_Y
#define MODEL_DW_VAR quadrotor_hil_DW
#endif
