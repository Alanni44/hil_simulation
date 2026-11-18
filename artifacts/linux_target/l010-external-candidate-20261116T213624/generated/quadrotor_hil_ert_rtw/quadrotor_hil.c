/*
 * File: quadrotor_hil.c
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

#include "quadrotor_hil.h"
#include "quadrotor_hil_private.h"

/* Exported block parameters */
real_T uav_angular_drag_nms = 0.02;    /* Variable: uav_angular_drag_nms
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
real_T uav_inertia_xx_kgm2 = 0.029;    /* Variable: uav_inertia_xx_kgm2
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
real_T uav_inertia_yy_kgm2 = 0.029;    /* Variable: uav_inertia_yy_kgm2
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
real_T uav_inertia_zz_kgm2 = 0.055;    /* Variable: uav_inertia_zz_kgm2
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
real_T uav_linear_drag_ns_m = 0.25;    /* Variable: uav_linear_drag_ns_m
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
real_T uav_mass_kg = 1.5;              /* Variable: uav_mass_kg
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
real_T uav_moment_coefficient_nm = 0.08;/* Variable: uav_moment_coefficient_nm
                                         * Referenced by: '<Root>/four_rotor_physical_plant'
                                         */
real_T uav_motor_efficiency = 1.0;     /* Variable: uav_motor_efficiency
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
real_T uav_thrust_coefficient_n = 4.2; /* Variable: uav_thrust_coefficient_n
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
real_T uav_wind_d_bias_mps = 0.0;      /* Variable: uav_wind_d_bias_mps
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
real_T uav_wind_e_bias_mps = 0.0;      /* Variable: uav_wind_e_bias_mps
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */
real_T uav_wind_n_bias_mps = 0.0;      /* Variable: uav_wind_n_bias_mps
                                        * Referenced by: '<Root>/four_rotor_physical_plant'
                                        */

/* Block states (default storage) */
DW_quadrotor_hil_T quadrotor_hil_DW;

/* External inputs (root inport signals with default storage) */
ExtU_quadrotor_hil_T quadrotor_hil_U;

/* External outputs (root outports fed by signals with default storage) */
ExtY_quadrotor_hil_T quadrotor_hil_Y;

/* Real-time model */
RT_MODEL_quadrotor_hil_T quadrotor_hil_M_;
RT_MODEL_quadrotor_hil_T *const quadrotor_hil_M = &quadrotor_hil_M_;

/* Forward declaration for local functions */
static real_T quadrotor_hil_mod(real_T x);

/* Function for MATLAB Function: '<Root>/four_rotor_physical_plant' */
static real_T quadrotor_hil_mod(real_T x)
{
  real_T r;
  if ((!rtIsInf(x)) && (!rtIsNaN(x))) {
    if (x == 0.0) {
      r = 0.0;
    } else {
      r = fmod(x, 1001.0);
      if (r == 0.0) {
        r = 0.0;
      } else {
        if (x < 0.0) {
          r += 1001.0;
        }
      }
    }
  } else {
    r = (rtNaN);
  }

  return r;
}

/* Model step function */
void quadrotor_hil_step(void)
{
  real_T density_scale;
  real_T acceleration_ned[3];
  real_T inertia[3];
  real_T angular_momentum[3];
  real_T y;
  real_T scale;
  real_T t;
  static const real_T gravity_ned[3] = { 0.0, 0.0, 9.80665 };

  real_T tmp[9];
  real_T tmp_0[3];
  real_T command;
  real_T command_idx_0;
  real_T command_idx_1;
  real_T command_idx_2;
  int32_T command_history_tmp;
  int32_T motor_response_tmp;
  real_T tmp_1;
  real_T tmp_2;
  real_T tmp_3;
  real_T tmp_4;
  real_T tmp_5;
  real_T y_tmp;
  real_T command_idx_2_tmp;
  real_T command_tmp;

  /* MATLAB Function: '<Root>/four_rotor_physical_plant' incorporates:
   *  Inport: '<Root>/command_delay_ms'
   *  Inport: '<Root>/ground_height_m'
   *  Inport: '<Root>/motor_1_failed'
   *  Inport: '<Root>/motor_2_failed'
   *  Inport: '<Root>/motor_3_failed'
   *  Inport: '<Root>/motor_4_failed'
   *  Inport: '<Root>/motor_command'
   *  Inport: '<Root>/packet_loss_ratio'
   *  Inport: '<Root>/pressure_pa'
   *  Inport: '<Root>/temperature_k'
   *  Inport: '<Root>/wind_d_mps'
   *  Inport: '<Root>/wind_e_mps'
   *  Inport: '<Root>/wind_n_mps'
   */
  quadrotor_hil_DW.loss_accumulator += fmin(fmax
    (quadrotor_hil_U.packet_loss_ratio, 0.0), 1.0);
  if (quadrotor_hil_DW.loss_accumulator >= 1.0) {
    quadrotor_hil_DW.loss_accumulator--;
  } else {
    quadrotor_hil_DW.held_command[0] = (1.0 - (real_T)
      quadrotor_hil_U.motor_1_failed) * fmin(fmax(quadrotor_hil_U.motor_command
      [0], 0.0), 1.0);
    quadrotor_hil_DW.held_command[1] = (1.0 - (real_T)
      quadrotor_hil_U.motor_2_failed) * fmin(fmax(quadrotor_hil_U.motor_command
      [1], 0.0), 1.0);
    quadrotor_hil_DW.held_command[2] = (1.0 - (real_T)
      quadrotor_hil_U.motor_3_failed) * fmin(fmax(quadrotor_hil_U.motor_command
      [2], 0.0), 1.0);
    quadrotor_hil_DW.held_command[3] = (1.0 - (real_T)
      quadrotor_hil_U.motor_4_failed) * fmin(fmax(quadrotor_hil_U.motor_command
      [3], 0.0), 1.0);
  }

  command_history_tmp = (int32_T)quadrotor_hil_DW.command_index;
  motor_response_tmp = (int32_T)(quadrotor_hil_mod
    ((quadrotor_hil_DW.command_index - 1.0) - floor(fmin(fmax
    (quadrotor_hil_U.command_delay_ms, 0.0), 1000.0) + 0.5)) + 1.0);
  quadrotor_hil_DW.command_index = quadrotor_hil_mod
    (quadrotor_hil_DW.command_index) + 1.0;
  command_history_tmp = (command_history_tmp - 1) << 2;
  quadrotor_hil_DW.command_history[command_history_tmp] =
    quadrotor_hil_DW.held_command[0];
  motor_response_tmp = (motor_response_tmp - 1) << 2;
  quadrotor_hil_DW.motor_response[0] +=
    (quadrotor_hil_DW.command_history[motor_response_tmp] * uav_motor_efficiency
     - quadrotor_hil_DW.motor_response[0]) * 0.001 / 0.035;
  quadrotor_hil_DW.command_history[1 + command_history_tmp] =
    quadrotor_hil_DW.held_command[1];
  quadrotor_hil_DW.motor_response[1] +=
    (quadrotor_hil_DW.command_history[motor_response_tmp + 1] *
     uav_motor_efficiency - quadrotor_hil_DW.motor_response[1]) * 0.001 / 0.035;
  quadrotor_hil_DW.command_history[2 + command_history_tmp] =
    quadrotor_hil_DW.held_command[2];
  quadrotor_hil_DW.motor_response[2] +=
    (quadrotor_hil_DW.command_history[motor_response_tmp + 2] *
     uav_motor_efficiency - quadrotor_hil_DW.motor_response[2]) * 0.001 / 0.035;
  quadrotor_hil_DW.command_history[3 + command_history_tmp] =
    quadrotor_hil_DW.held_command[3];
  quadrotor_hil_DW.motor_response[3] +=
    (quadrotor_hil_DW.command_history[motor_response_tmp + 3] *
     uav_motor_efficiency - quadrotor_hil_DW.motor_response[3]) * 0.001 / 0.035;
  quadrotor_hil_DW.motor_response[0] = fmin(fmax
    (quadrotor_hil_DW.motor_response[0], 0.0), 1.2);
  quadrotor_hil_DW.motor_response[1] = fmin(fmax
    (quadrotor_hil_DW.motor_response[1], 0.0), 1.2);
  quadrotor_hil_DW.motor_response[2] = fmin(fmax
    (quadrotor_hil_DW.motor_response[2], 0.0), 1.2);
  quadrotor_hil_DW.motor_response[3] = fmin(fmax
    (quadrotor_hil_DW.motor_response[3], 0.0), 1.2);
  density_scale = fmin(fmax(fmax(quadrotor_hil_U.pressure_pa, 1000.0) / (287.05 *
    fmax(quadrotor_hil_U.temperature_k, 150.0)) / 1.225, 0.5), 1.5);
  scale = quadrotor_hil_DW.motor_response[0] * quadrotor_hil_DW.motor_response[0];
  command_idx_0 = scale * uav_thrust_coefficient_n * density_scale;
  t = quadrotor_hil_DW.motor_response[1] * quadrotor_hil_DW.motor_response[1];
  command_idx_1 = t * uav_thrust_coefficient_n * density_scale;
  command_idx_2_tmp = quadrotor_hil_DW.motor_response[2] *
    quadrotor_hil_DW.motor_response[2];
  command_idx_2 = command_idx_2_tmp * uav_thrust_coefficient_n * density_scale;
  command_tmp = quadrotor_hil_DW.motor_response[3] *
    quadrotor_hil_DW.motor_response[3];
  command = command_tmp * uav_thrust_coefficient_n * density_scale;
  y_tmp = command_idx_0 + command_idx_1;
  y = (y_tmp + command_idx_2) + command;
  density_scale = quadrotor_hil_DW.quaternion_frd_to_ned[3] *
    quadrotor_hil_DW.quaternion_frd_to_ned[3];
  tmp_5 = quadrotor_hil_DW.quaternion_frd_to_ned[2] *
    quadrotor_hil_DW.quaternion_frd_to_ned[2];
  tmp[0] = 1.0 - (tmp_5 + density_scale) * 2.0;
  tmp_1 = quadrotor_hil_DW.quaternion_frd_to_ned[1] *
    quadrotor_hil_DW.quaternion_frd_to_ned[2];
  tmp_2 = quadrotor_hil_DW.quaternion_frd_to_ned[0] *
    quadrotor_hil_DW.quaternion_frd_to_ned[3];
  tmp[3] = (tmp_1 - tmp_2) * 2.0;
  tmp_3 = quadrotor_hil_DW.quaternion_frd_to_ned[1] *
    quadrotor_hil_DW.quaternion_frd_to_ned[3];
  tmp_4 = quadrotor_hil_DW.quaternion_frd_to_ned[0] *
    quadrotor_hil_DW.quaternion_frd_to_ned[2];
  tmp[6] = (tmp_3 + tmp_4) * 2.0;
  tmp[1] = (tmp_1 + tmp_2) * 2.0;
  tmp_1 = quadrotor_hil_DW.quaternion_frd_to_ned[1] *
    quadrotor_hil_DW.quaternion_frd_to_ned[1];
  tmp[4] = 1.0 - (tmp_1 + density_scale) * 2.0;
  density_scale = quadrotor_hil_DW.quaternion_frd_to_ned[2] *
    quadrotor_hil_DW.quaternion_frd_to_ned[3];
  tmp_2 = quadrotor_hil_DW.quaternion_frd_to_ned[0] *
    quadrotor_hil_DW.quaternion_frd_to_ned[1];
  tmp[7] = (density_scale - tmp_2) * 2.0;
  tmp[2] = (tmp_3 - tmp_4) * 2.0;
  tmp[5] = (density_scale + tmp_2) * 2.0;
  tmp[8] = 1.0 - (tmp_1 + tmp_5) * 2.0;
  tmp_0[0] = quadrotor_hil_U.wind_n_mps + uav_wind_n_bias_mps;
  tmp_0[1] = quadrotor_hil_U.wind_e_mps + uav_wind_e_bias_mps;
  tmp_0[2] = quadrotor_hil_U.wind_d_mps + uav_wind_d_bias_mps;
  inertia[0] = uav_inertia_xx_kgm2;
  inertia[1] = uav_inertia_yy_kgm2;
  inertia[2] = uav_inertia_zz_kgm2;
  for (motor_response_tmp = 0; motor_response_tmp < 3; motor_response_tmp++) {
    density_scale = (((tmp[motor_response_tmp + 3] * 0.0 +
                       tmp[motor_response_tmp] * 0.0) + tmp[motor_response_tmp +
                      6] * -y) +
                     (quadrotor_hil_DW.velocity_ned[motor_response_tmp] -
                      tmp_0[motor_response_tmp]) * -uav_linear_drag_ns_m) /
      uav_mass_kg + gravity_ned[motor_response_tmp];
    angular_momentum[motor_response_tmp] = inertia[motor_response_tmp] *
      quadrotor_hil_DW.body_rates[motor_response_tmp];
    quadrotor_hil_DW.velocity_ned[motor_response_tmp] += 0.001 * density_scale;
    quadrotor_hil_DW.position_ned[motor_response_tmp] += 0.001 *
      quadrotor_hil_DW.velocity_ned[motor_response_tmp];
    acceleration_ned[motor_response_tmp] = density_scale;
  }

  density_scale = quadrotor_hil_DW.body_rates[0];
  tmp_5 = quadrotor_hil_DW.body_rates[0];
  tmp_1 = quadrotor_hil_DW.body_rates[1];
  quadrotor_hil_DW.body_rates[0] += (((((command_idx_0 - command_idx_1) -
    command_idx_2) + command) * 0.16263455967290594 -
    (quadrotor_hil_DW.body_rates[1] * angular_momentum[2] -
     quadrotor_hil_DW.body_rates[2] * angular_momentum[1])) -
    uav_angular_drag_nms * quadrotor_hil_DW.body_rates[0]) / uav_inertia_xx_kgm2
    * 0.001;
  quadrotor_hil_DW.body_rates[1] += ((((y_tmp - command_idx_2) - command) *
    0.16263455967290594 - (quadrotor_hil_DW.body_rates[2] * angular_momentum[0]
    - density_scale * angular_momentum[2])) - uav_angular_drag_nms *
    quadrotor_hil_DW.body_rates[1]) / uav_inertia_yy_kgm2 * 0.001;
  quadrotor_hil_DW.body_rates[2] += (((((-scale + t) - command_idx_2_tmp) +
    command_tmp) * uav_moment_coefficient_nm - (tmp_5 * angular_momentum[1] -
    tmp_1 * angular_momentum[0])) - uav_angular_drag_nms *
    quadrotor_hil_DW.body_rates[2]) / uav_inertia_zz_kgm2 * 0.001;
  density_scale = quadrotor_hil_DW.quaternion_frd_to_ned[0];
  tmp_5 = quadrotor_hil_DW.quaternion_frd_to_ned[0];
  tmp_1 = quadrotor_hil_DW.quaternion_frd_to_ned[1];
  tmp_2 = quadrotor_hil_DW.quaternion_frd_to_ned[0];
  tmp_3 = quadrotor_hil_DW.quaternion_frd_to_ned[1];
  tmp_4 = quadrotor_hil_DW.quaternion_frd_to_ned[2];
  scale = 3.3121686421112381E-170;
  quadrotor_hil_DW.quaternion_frd_to_ned[0] +=
    ((-quadrotor_hil_DW.quaternion_frd_to_ned[1] * quadrotor_hil_DW.body_rates[0]
      - quadrotor_hil_DW.quaternion_frd_to_ned[2] * quadrotor_hil_DW.body_rates
      [1]) - quadrotor_hil_DW.quaternion_frd_to_ned[3] *
     quadrotor_hil_DW.body_rates[2]) * 0.5 * 0.001;
  command_idx_0 = fabs(quadrotor_hil_DW.quaternion_frd_to_ned[0]);
  if (command_idx_0 > 3.3121686421112381E-170) {
    command_idx_1 = 1.0;
    scale = command_idx_0;
  } else {
    t = command_idx_0 / 3.3121686421112381E-170;
    command_idx_1 = t * t;
  }

  quadrotor_hil_DW.quaternion_frd_to_ned[1] += ((density_scale *
    quadrotor_hil_DW.body_rates[0] + quadrotor_hil_DW.quaternion_frd_to_ned[2] *
    quadrotor_hil_DW.body_rates[2]) - quadrotor_hil_DW.quaternion_frd_to_ned[3] *
    quadrotor_hil_DW.body_rates[1]) * 0.5 * 0.001;
  command_idx_0 = fabs(quadrotor_hil_DW.quaternion_frd_to_ned[1]);
  if (command_idx_0 > scale) {
    t = scale / command_idx_0;
    command_idx_1 = command_idx_1 * t * t + 1.0;
    scale = command_idx_0;
  } else {
    t = command_idx_0 / scale;
    command_idx_1 += t * t;
  }

  quadrotor_hil_DW.quaternion_frd_to_ned[2] += ((tmp_5 *
    quadrotor_hil_DW.body_rates[1] + quadrotor_hil_DW.quaternion_frd_to_ned[3] *
    quadrotor_hil_DW.body_rates[0]) - tmp_1 * quadrotor_hil_DW.body_rates[2]) *
    0.5 * 0.001;
  command_idx_0 = fabs(quadrotor_hil_DW.quaternion_frd_to_ned[2]);
  if (command_idx_0 > scale) {
    t = scale / command_idx_0;
    command_idx_1 = command_idx_1 * t * t + 1.0;
    scale = command_idx_0;
  } else {
    t = command_idx_0 / scale;
    command_idx_1 += t * t;
  }

  quadrotor_hil_DW.quaternion_frd_to_ned[3] += ((tmp_2 *
    quadrotor_hil_DW.body_rates[2] + tmp_3 * quadrotor_hil_DW.body_rates[1]) -
    tmp_4 * quadrotor_hil_DW.body_rates[0]) * 0.5 * 0.001;
  command_idx_0 = fabs(quadrotor_hil_DW.quaternion_frd_to_ned[3]);
  if (command_idx_0 > scale) {
    t = scale / command_idx_0;
    command_idx_1 = command_idx_1 * t * t + 1.0;
    scale = command_idx_0;
  } else {
    t = command_idx_0 / scale;
    command_idx_1 += t * t;
  }

  command_idx_1 = scale * sqrt(command_idx_1);
  density_scale = fmax(command_idx_1, 1.0E-12);
  quadrotor_hil_DW.quaternion_frd_to_ned[0] /= density_scale;
  quadrotor_hil_DW.quaternion_frd_to_ned[1] /= density_scale;
  quadrotor_hil_DW.quaternion_frd_to_ned[2] /= density_scale;
  quadrotor_hil_DW.quaternion_frd_to_ned[3] /= density_scale;
  if (quadrotor_hil_DW.position_ned[2] > -quadrotor_hil_U.ground_height_m) {
    quadrotor_hil_DW.position_ned[2] = -quadrotor_hil_U.ground_height_m;
    quadrotor_hil_DW.velocity_ned[2] = fmin(quadrotor_hil_DW.velocity_ned[2],
      0.0);
  }

  /* Outport: '<Root>/north_m' incorporates:
   *  Inport: '<Root>/gps_bias_d_m'
   *  Inport: '<Root>/gps_bias_e_m'
   *  Inport: '<Root>/gps_bias_n_m'
   *  Inport: '<Root>/imu_bias_p_radps'
   *  Inport: '<Root>/imu_bias_q_radps'
   *  Inport: '<Root>/imu_bias_r_radps'
   *  Inport: '<Root>/sensor_delay_ms'
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.north_m = ((((((quadrotor_hil_U.sensor_delay_ms +
    quadrotor_hil_U.gps_bias_n_m) + quadrotor_hil_U.gps_bias_e_m) +
    quadrotor_hil_U.gps_bias_d_m) + quadrotor_hil_U.imu_bias_p_radps) +
    quadrotor_hil_U.imu_bias_q_radps) + quadrotor_hil_U.imu_bias_r_radps) * 0.0
    + quadrotor_hil_DW.position_ned[0];

  /* Outport: '<Root>/east_m' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.east_m = quadrotor_hil_DW.position_ned[1];

  /* Outport: '<Root>/down_m' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.down_m = quadrotor_hil_DW.position_ned[2];

  /* Outport: '<Root>/vn_mps' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.vn_mps = quadrotor_hil_DW.velocity_ned[0];

  /* Outport: '<Root>/ve_mps' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.ve_mps = quadrotor_hil_DW.velocity_ned[1];

  /* Outport: '<Root>/vd_mps' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.vd_mps = quadrotor_hil_DW.velocity_ned[2];

  /* Outport: '<Root>/q_w' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.q_w = quadrotor_hil_DW.quaternion_frd_to_ned[0];

  /* Outport: '<Root>/q_x' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.q_x = quadrotor_hil_DW.quaternion_frd_to_ned[1];

  /* Outport: '<Root>/q_y' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.q_y = quadrotor_hil_DW.quaternion_frd_to_ned[2];

  /* Outport: '<Root>/q_z' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.q_z = quadrotor_hil_DW.quaternion_frd_to_ned[3];

  /* Outport: '<Root>/p_radps' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.p_radps = quadrotor_hil_DW.body_rates[0];

  /* Outport: '<Root>/q_radps' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.q_radps = quadrotor_hil_DW.body_rates[1];

  /* Outport: '<Root>/r_radps' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.r_radps = quadrotor_hil_DW.body_rates[2];

  /* Outport: '<Root>/airborne' incorporates:
   *  Inport: '<Root>/ground_height_m'
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.airborne = (quadrotor_hil_DW.position_ned[2] <
    -quadrotor_hil_U.ground_height_m - 0.05);

  /* Outport: '<Root>/ax_mps2' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.ax_mps2 = acceleration_ned[0];

  /* Outport: '<Root>/ay_mps2' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.ay_mps2 = acceleration_ned[1];

  /* Outport: '<Root>/az_mps2' incorporates:
   *  MATLAB Function: '<Root>/four_rotor_physical_plant'
   */
  quadrotor_hil_Y.az_mps2 = acceleration_ned[2];
}

/* Model initialize function */
void quadrotor_hil_initialize(void)
{
  /* Registration code */

  /* initialize non-finites */
  rt_InitInfAndNaN(sizeof(real_T));

  /* initialize error status */
  rtmSetErrorStatus(quadrotor_hil_M, (NULL));

  /* states (dwork) */
  (void) memset((void *)&quadrotor_hil_DW, 0,
                sizeof(DW_quadrotor_hil_T));

  /* external inputs */
  (void)memset(&quadrotor_hil_U, 0, sizeof(ExtU_quadrotor_hil_T));

  /* external outputs */
  (void) memset((void *)&quadrotor_hil_Y, 0,
                sizeof(ExtY_quadrotor_hil_T));

  /* SystemInitialize for MATLAB Function: '<Root>/four_rotor_physical_plant' */
  quadrotor_hil_DW.quaternion_frd_to_ned[0] = 1.0;
  quadrotor_hil_DW.quaternion_frd_to_ned[1] = 0.0;
  quadrotor_hil_DW.quaternion_frd_to_ned[2] = 0.0;
  quadrotor_hil_DW.quaternion_frd_to_ned[3] = 0.0;
  quadrotor_hil_DW.position_ned[0] = 0.0;
  quadrotor_hil_DW.velocity_ned[0] = 0.0;
  quadrotor_hil_DW.body_rates[0] = 0.0;
  quadrotor_hil_DW.position_ned[1] = 0.0;
  quadrotor_hil_DW.velocity_ned[1] = 0.0;
  quadrotor_hil_DW.body_rates[1] = 0.0;
  quadrotor_hil_DW.position_ned[2] = 0.0;
  quadrotor_hil_DW.velocity_ned[2] = 0.0;
  quadrotor_hil_DW.body_rates[2] = 0.0;
  quadrotor_hil_DW.motor_response[0] = 0.0;
  quadrotor_hil_DW.motor_response[1] = 0.0;
  quadrotor_hil_DW.motor_response[2] = 0.0;
  quadrotor_hil_DW.motor_response[3] = 0.0;
  memset(&quadrotor_hil_DW.command_history[0], 0, 4004U * sizeof(real_T));
  quadrotor_hil_DW.held_command[0] = 0.0;
  quadrotor_hil_DW.held_command[1] = 0.0;
  quadrotor_hil_DW.held_command[2] = 0.0;
  quadrotor_hil_DW.held_command[3] = 0.0;
  quadrotor_hil_DW.loss_accumulator = 0.0;
  quadrotor_hil_DW.command_index = 1.0;
}

/* Model terminate function */
void quadrotor_hil_terminate(void)
{
  /* (no terminate code required) */
}

/*
 * File trailer for generated code.
 *
 * [EOF]
 */
