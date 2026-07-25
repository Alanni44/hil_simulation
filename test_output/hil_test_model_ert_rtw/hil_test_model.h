/*
 * File: hil_test_model.h
 *
 * Code generated for Simulink model 'hil_test_model'.
 *
 * Model version                  : 1.1
 * Simulink Coder version         : 9.0 (R2018b) 24-May-2018
 * C/C++ source code generated on : Sat Jul 25 15:27:52 2026
 *
 * Target selection: ert.tlc
 * Embedded hardware selection: Intel->x86-64 (Windows64)
 * Code generation objectives: Unspecified
 * Validation result: Not run
 */

#ifndef RTW_HEADER_hil_test_model_h_
#define RTW_HEADER_hil_test_model_h_
#include <string.h>
#include <stddef.h>
#ifndef hil_test_model_COMMON_INCLUDES_
# define hil_test_model_COMMON_INCLUDES_
#include "rtwtypes.h"
#endif                                 /* hil_test_model_COMMON_INCLUDES_ */

#include "hil_test_model_types.h"

/* Macros for accessing real-time model data structure */
#ifndef rtmGetErrorStatus
# define rtmGetErrorStatus(rtm)        ((rtm)->errorStatus)
#endif

#ifndef rtmSetErrorStatus
# define rtmSetErrorStatus(rtm, val)   ((rtm)->errorStatus = (val))
#endif

/* Block states (default storage) for system '<Root>' */
typedef struct {
  real_T Int_yaw_DSTATE;               /* '<S1>/Int_yaw' */
  real_T I_X_DSTATE;                   /* '<S1>/I_X' */
  real_T UD_DSTATE;                    /* '<S3>/UD' */
  real_T UD_DSTATE_n;                  /* '<S4>/UD' */
  real_T I_Y_DSTATE;                   /* '<S1>/I_Y' */
  real_T Pos_X_DSTATE;                 /* '<S1>/Pos_X' */
  real_T Pos_Y_DSTATE;                 /* '<S1>/Pos_Y' */
  real_T I_Z_DSTATE;                   /* '<S1>/I_Z' */
  real_T UD_DSTATE_d;                  /* '<S5>/UD' */
  real_T Pos_Z_DSTATE;                 /* '<S1>/Pos_Z' */
} DW_hil_test_model_T;

/* External inputs (root inport signals with default storage) */
typedef struct {
  real_T cmd_x;                        /* '<Root>/cmd_x' */
  real_T cmd_y;                        /* '<Root>/cmd_y' */
  real_T cmd_z;                        /* '<Root>/cmd_z' */
  real_T cmd_yaw;                      /* '<Root>/cmd_yaw' */
  real_T cmd_mode;                     /* '<Root>/cmd_mode' */
  real_T cmd_speed;                    /* '<Root>/cmd_speed' */
} ExtU_hil_test_model_T;

/* External outputs (root outports fed by signals with default storage) */
typedef struct {
  real_T X;                            /* '<Root>/X' */
  real_T Y;                            /* '<Root>/Y' */
  real_T Z;                            /* '<Root>/Z' */
  real_T Phi;                          /* '<Root>/Phi' */
  real_T Theta;                        /* '<Root>/Theta' */
  real_T Psi;                          /* '<Root>/Psi' */
  real_T vx;                           /* '<Root>/vx' */
  real_T vy;                           /* '<Root>/vy' */
  real_T vz;                           /* '<Root>/vz' */
  boolean_T airborne;                  /* '<Root>/airborne' */
} ExtY_hil_test_model_T;

/* Real-time Model Data Structure */
struct tag_RTM_hil_test_model_T {
  const char_T * volatile errorStatus;
};

/* Block states (default storage) */
extern DW_hil_test_model_T hil_test_model_DW;

/* External inputs (root inport signals with default storage) */
extern ExtU_hil_test_model_T hil_test_model_U;

/* External outputs (root outports fed by signals with default storage) */
extern ExtY_hil_test_model_T hil_test_model_Y;

/* Model entry point functions */
extern void hil_test_model_initialize(void);
extern void hil_test_model_step(void);
extern void hil_test_model_terminate(void);

/* Real-time Model object */
extern RT_MODEL_hil_test_model_T *const hil_test_model_M;

/*-
 * These blocks were eliminated from the model due to optimizations:
 *
 * Block '<S3>/Data Type Duplicate' : Unused code path elimination
 * Block '<S4>/Data Type Duplicate' : Unused code path elimination
 * Block '<S5>/Data Type Duplicate' : Unused code path elimination
 * Block '<Root>/Scope_Phi' : Unused code path elimination
 * Block '<Root>/Scope_Psi' : Unused code path elimination
 * Block '<Root>/Scope_Theta' : Unused code path elimination
 * Block '<Root>/Scope_X' : Unused code path elimination
 * Block '<Root>/Scope_Y' : Unused code path elimination
 * Block '<Root>/Scope_Z' : Unused code path elimination
 * Block '<Root>/u_drag_x' : Unused code path elimination
 * Block '<Root>/u_drag_y' : Unused code path elimination
 * Block '<Root>/u_gravity' : Unused code path elimination
 * Block '<Root>/u_mass' : Unused code path elimination
 */

/*-
 * The generated code includes comments that allow you to trace directly
 * back to the appropriate location in the model.  The basic format
 * is <system>/block_name, where system is the system number (uniquely
 * assigned by Simulink) and block_name is the name of the block.
 *
 * Use the MATLAB hilite_system command to trace the generated code back
 * to the model.  For example,
 *
 * hilite_system('<S3>')    - opens system 3
 * hilite_system('<S3>/Kp') - opens and selects block Kp which resides in S3
 *
 * Here is the system hierarchy for this model
 *
 * '<Root>' : 'hil_test_model'
 * '<S1>'   : 'hil_test_model/Drone'
 * '<S2>'   : 'hil_test_model/Drone/Airborne'
 * '<S3>'   : 'hil_test_model/Drone/Deriv_X'
 * '<S4>'   : 'hil_test_model/Drone/Deriv_Y'
 * '<S5>'   : 'hil_test_model/Drone/Deriv_Z'
 */
#endif                                 /* RTW_HEADER_hil_test_model_h_ */

/*
 * File trailer for generated code.
 *
 * [EOF]
 */
