/*
 * File: quadrotor_hil.h
 *
 * Code generated for Simulink model 'quadrotor_hil'.
 *
 * Model version                  : 1.1
 * Simulink Coder version         : 9.0 (R2018b) 24-May-2018
 * C/C++ source code generated on : Mon Nov 16 21:37:05 2026
 *
 * Target selection: ert.tlc
 * Embedded hardware selection: Intel->x86-64 (Windows64)
 * Code generation objectives: Unspecified
 * Validation result: Not run
 */

#ifndef RTW_HEADER_quadrotor_hil_h_
#define RTW_HEADER_quadrotor_hil_h_
#include <math.h>
#include <string.h>
#include <stddef.h>
#ifndef quadrotor_hil_COMMON_INCLUDES_
# define quadrotor_hil_COMMON_INCLUDES_
#include "rtwtypes.h"
#endif                                 /* quadrotor_hil_COMMON_INCLUDES_ */

#include "quadrotor_hil_types.h"
#include "rtGetNaN.h"
#include "rt_nonfinite.h"
#include "rtGetInf.h"

/* Macros for accessing real-time model data structure */
#ifndef rtmGetErrorStatus
# define rtmGetErrorStatus(rtm)        ((rtm)->errorStatus)
#endif

#ifndef rtmSetErrorStatus
# define rtmSetErrorStatus(rtm, val)   ((rtm)->errorStatus = (val))
#endif

/* Block states (default storage) for system '<Root>' */
typedef struct {
  real_T position_ned[3];              /* '<Root>/four_rotor_physical_plant' */
  real_T velocity_ned[3];              /* '<Root>/four_rotor_physical_plant' */
  real_T quaternion_frd_to_ned[4];     /* '<Root>/four_rotor_physical_plant' */
  real_T body_rates[3];                /* '<Root>/four_rotor_physical_plant' */
  real_T motor_response[4];            /* '<Root>/four_rotor_physical_plant' */
  real_T command_history[4004];        /* '<Root>/four_rotor_physical_plant' */
  real_T held_command[4];              /* '<Root>/four_rotor_physical_plant' */
  real_T loss_accumulator;             /* '<Root>/four_rotor_physical_plant' */
  real_T command_index;                /* '<Root>/four_rotor_physical_plant' */
} DW_quadrotor_hil_T;

/* External inputs (root inport signals with default storage) */
typedef struct {
  real_T motor_command[4];             /* '<Root>/motor_command' */
  real_T wind_n_mps;                   /* '<Root>/wind_n_mps' */
  real_T wind_e_mps;                   /* '<Root>/wind_e_mps' */
  real_T wind_d_mps;                   /* '<Root>/wind_d_mps' */
  real_T pressure_pa;                  /* '<Root>/pressure_pa' */
  real_T temperature_k;                /* '<Root>/temperature_k' */
  real_T ground_height_m;              /* '<Root>/ground_height_m' */
  real_T gps_bias_n_m;                 /* '<Root>/gps_bias_n_m' */
  real_T gps_bias_e_m;                 /* '<Root>/gps_bias_e_m' */
  real_T gps_bias_d_m;                 /* '<Root>/gps_bias_d_m' */
  real_T imu_bias_p_radps;             /* '<Root>/imu_bias_p_radps' */
  real_T imu_bias_q_radps;             /* '<Root>/imu_bias_q_radps' */
  real_T imu_bias_r_radps;             /* '<Root>/imu_bias_r_radps' */
  boolean_T motor_1_failed;            /* '<Root>/motor_1_failed' */
  boolean_T motor_2_failed;            /* '<Root>/motor_2_failed' */
  boolean_T motor_3_failed;            /* '<Root>/motor_3_failed' */
  boolean_T motor_4_failed;            /* '<Root>/motor_4_failed' */
  real_T command_delay_ms;             /* '<Root>/command_delay_ms' */
  real_T sensor_delay_ms;              /* '<Root>/sensor_delay_ms' */
  real_T packet_loss_ratio;            /* '<Root>/packet_loss_ratio' */
} ExtU_quadrotor_hil_T;

/* External outputs (root outports fed by signals with default storage) */
typedef struct {
  real_T north_m;                      /* '<Root>/north_m' */
  real_T east_m;                       /* '<Root>/east_m' */
  real_T down_m;                       /* '<Root>/down_m' */
  real_T vn_mps;                       /* '<Root>/vn_mps' */
  real_T ve_mps;                       /* '<Root>/ve_mps' */
  real_T vd_mps;                       /* '<Root>/vd_mps' */
  real_T q_w;                          /* '<Root>/q_w' */
  real_T q_x;                          /* '<Root>/q_x' */
  real_T q_y;                          /* '<Root>/q_y' */
  real_T q_z;                          /* '<Root>/q_z' */
  real_T p_radps;                      /* '<Root>/p_radps' */
  real_T q_radps;                      /* '<Root>/q_radps' */
  real_T r_radps;                      /* '<Root>/r_radps' */
  boolean_T airborne;                  /* '<Root>/airborne' */
  real_T ax_mps2;                      /* '<Root>/ax_mps2' */
  real_T ay_mps2;                      /* '<Root>/ay_mps2' */
  real_T az_mps2;                      /* '<Root>/az_mps2' */
} ExtY_quadrotor_hil_T;

/* Real-time Model Data Structure */
struct tag_RTM_quadrotor_hil_T {
  const char_T * volatile errorStatus;
};

/* Block states (default storage) */
extern DW_quadrotor_hil_T quadrotor_hil_DW;

/* External inputs (root inport signals with default storage) */
extern ExtU_quadrotor_hil_T quadrotor_hil_U;

/* External outputs (root outports fed by signals with default storage) */
extern ExtY_quadrotor_hil_T quadrotor_hil_Y;

/*
 * Exported Global Parameters
 *
 * Note: Exported global parameters are tunable parameters with an exported
 * global storage class designation.  Code generation will declare the memory for
 * these parameters and exports their symbols.
 *
 */
extern real_T uav_angular_drag_nms;    /* Variable: uav_angular_drag_nms
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
extern real_T uav_inertia_xx_kgm2;     /* Variable: uav_inertia_xx_kgm2
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
extern real_T uav_inertia_yy_kgm2;     /* Variable: uav_inertia_yy_kgm2
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
extern real_T uav_inertia_zz_kgm2;     /* Variable: uav_inertia_zz_kgm2
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
extern real_T uav_linear_drag_ns_m;    /* Variable: uav_linear_drag_ns_m
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
extern real_T uav_mass_kg;             /* Variable: uav_mass_kg
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
extern real_T uav_moment_coefficient_nm;/* Variable: uav_moment_coefficient_nm
                                         * Referenced by: '<Root>/four_rotor_physical_plant'
                                         */
extern real_T uav_motor_efficiency;    /* Variable: uav_motor_efficiency
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
extern real_T uav_thrust_coefficient_n;/* Variable: uav_thrust_coefficient_n
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
extern real_T uav_wind_d_bias_mps;     /* Variable: uav_wind_d_bias_mps
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
extern real_T uav_wind_e_bias_mps;     /* Variable: uav_wind_e_bias_mps
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
extern real_T uav_wind_n_bias_mps;     /* Variable: uav_wind_n_bias_mps
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */

/* Model entry point functions */
extern void quadrotor_hil_initialize(void);
extern void quadrotor_hil_step(void);
extern void quadrotor_hil_terminate(void);

/* Real-time Model object */
extern RT_MODEL_quadrotor_hil_T *const quadrotor_hil_M;

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
 * '<Root>' : 'quadrotor_hil'
 * '<S1>'   : 'quadrotor_hil/four_rotor_physical_plant'
 */
#endif                                 /* RTW_HEADER_quadrotor_hil_h_ */

/*
 * File trailer for generated code.
 *
 * [EOF]
 */
