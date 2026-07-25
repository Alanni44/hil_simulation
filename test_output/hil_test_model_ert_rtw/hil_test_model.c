/*
 * File: hil_test_model.c
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

#include "hil_test_model.h"
#include "hil_test_model_private.h"

/* Block states (default storage) */
DW_hil_test_model_T hil_test_model_DW;

/* External inputs (root inport signals with default storage) */
ExtU_hil_test_model_T hil_test_model_U;

/* External outputs (root outports fed by signals with default storage) */
ExtY_hil_test_model_T hil_test_model_Y;

/* Real-time model */
RT_MODEL_hil_test_model_T hil_test_model_M_;
RT_MODEL_hil_test_model_T *const hil_test_model_M = &hil_test_model_M_;

/* Model step function */
void hil_test_model_step(void)
{
  real_T rtb_PID_Z;
  real_T rtb_TSamp;
  real_T rtb_I_Z;
  real_T rtb_TSamp_g;
  real_T rtb_err_Z;
  real_T rtb_TSamp_f;

  /* Saturate: '<S1>/Sat_yaw' incorporates:
   *  DiscreteIntegrator: '<S1>/Int_yaw'
   */
  if (hil_test_model_DW.Int_yaw_DSTATE > 3.1415926535897931) {
    /* Outport: '<Root>/Psi' */
    hil_test_model_Y.Psi = 3.1415926535897931;
  } else if (hil_test_model_DW.Int_yaw_DSTATE < -3.1415926535897931) {
    /* Outport: '<Root>/Psi' */
    hil_test_model_Y.Psi = -3.1415926535897931;
  } else {
    /* Outport: '<Root>/Psi' */
    hil_test_model_Y.Psi = hil_test_model_DW.Int_yaw_DSTATE;
  }

  /* End of Saturate: '<S1>/Sat_yaw' */

  /* Sum: '<S1>/err_X' incorporates:
   *  Inport: '<Root>/cmd_x'
   *  UnitDelay: '<S1>/FB_X'
   */
  rtb_PID_Z = hil_test_model_U.cmd_x - hil_test_model_Y.X;

  /* SampleTimeMath: '<S3>/TSamp'
   *
   * About '<S3>/TSamp':
   *  y = u * K where K = 1 / ( w * Ts )
   */
  rtb_TSamp = rtb_PID_Z * 1000.0;

  /* Sum: '<S1>/PID_X' incorporates:
   *  Constant: '<Root>/u_kdxy'
   *  Constant: '<Root>/u_kpxy'
   *  DiscreteIntegrator: '<S1>/I_X'
   *  Product: '<S1>/Dg_X'
   *  Product: '<S1>/P_X'
   *  Sum: '<S3>/Diff'
   *  UnitDelay: '<S3>/UD'
   *
   * Block description for '<S3>/Diff':
   *
   *  Add in CPU
   *
   * Block description for '<S3>/UD':
   *
   *  Store in Global RAM
   */
  hil_test_model_Y.vx = (rtb_PID_Z * 1.5 + hil_test_model_DW.I_X_DSTATE) +
    (rtb_TSamp - hil_test_model_DW.UD_DSTATE) * 0.8;

  /* Saturate: '<S1>/Sat_X' */
  if (hil_test_model_Y.vx > 15.0) {
    /* Sum: '<S1>/PID_X' */
    hil_test_model_Y.vx = 15.0;
  } else {
    if (hil_test_model_Y.vx < -15.0) {
      /* Sum: '<S1>/PID_X' */
      hil_test_model_Y.vx = -15.0;
    }
  }

  /* End of Saturate: '<S1>/Sat_X' */

  /* Sum: '<S1>/err_Y' incorporates:
   *  Inport: '<Root>/cmd_y'
   *  UnitDelay: '<S1>/FB_Y'
   */
  rtb_I_Z = hil_test_model_U.cmd_y - hil_test_model_Y.Y;

  /* SampleTimeMath: '<S4>/TSamp'
   *
   * About '<S4>/TSamp':
   *  y = u * K where K = 1 / ( w * Ts )
   */
  rtb_TSamp_g = rtb_I_Z * 1000.0;

  /* Sum: '<S1>/PID_Y' incorporates:
   *  Constant: '<Root>/u_kdxy'
   *  Constant: '<Root>/u_kpxy'
   *  DiscreteIntegrator: '<S1>/I_Y'
   *  Product: '<S1>/Dg_Y'
   *  Product: '<S1>/P_Y'
   *  Sum: '<S4>/Diff'
   *  UnitDelay: '<S4>/UD'
   *
   * Block description for '<S4>/Diff':
   *
   *  Add in CPU
   *
   * Block description for '<S4>/UD':
   *
   *  Store in Global RAM
   */
  hil_test_model_Y.vy = (rtb_I_Z * 1.5 + hil_test_model_DW.I_Y_DSTATE) +
    (rtb_TSamp_g - hil_test_model_DW.UD_DSTATE_n) * 0.8;

  /* Saturate: '<S1>/Sat_Y' */
  if (hil_test_model_Y.vy > 15.0) {
    /* Sum: '<S1>/PID_Y' */
    hil_test_model_Y.vy = 15.0;
  } else {
    if (hil_test_model_Y.vy < -15.0) {
      /* Sum: '<S1>/PID_Y' */
      hil_test_model_Y.vy = -15.0;
    }
  }

  /* End of Saturate: '<S1>/Sat_Y' */

  /* DiscreteIntegrator: '<S1>/Pos_X' incorporates:
   *  UnitDelay: '<S1>/FB_X'
   */
  hil_test_model_Y.X = hil_test_model_DW.Pos_X_DSTATE;

  /* DiscreteIntegrator: '<S1>/Pos_Y' incorporates:
   *  UnitDelay: '<S1>/FB_Y'
   */
  hil_test_model_Y.Y = hil_test_model_DW.Pos_Y_DSTATE;

  /* Sum: '<S1>/err_Z' incorporates:
   *  Inport: '<Root>/cmd_z'
   *  UnitDelay: '<S1>/FB_Z'
   */
  rtb_err_Z = hil_test_model_U.cmd_z - hil_test_model_Y.Z;

  /* SampleTimeMath: '<S5>/TSamp'
   *
   * About '<S5>/TSamp':
   *  y = u * K where K = 1 / ( w * Ts )
   */
  rtb_TSamp_f = rtb_err_Z * 1000.0;

  /* Sum: '<S1>/PID_Z' incorporates:
   *  Constant: '<Root>/u_kdz'
   *  Constant: '<Root>/u_kpz'
   *  DiscreteIntegrator: '<S1>/I_Z'
   *  Product: '<S1>/Dg_Z'
   *  Product: '<S1>/P_Z'
   *  Sum: '<S5>/Diff'
   *  UnitDelay: '<S5>/UD'
   *
   * Block description for '<S5>/Diff':
   *
   *  Add in CPU
   *
   * Block description for '<S5>/UD':
   *
   *  Store in Global RAM
   */
  hil_test_model_Y.vz = (rtb_err_Z * 2.5 + hil_test_model_DW.I_Z_DSTATE) +
    (rtb_TSamp_f - hil_test_model_DW.UD_DSTATE_d) * 1.2;

  /* Saturate: '<S1>/Sat_Z' */
  if (hil_test_model_Y.vz > 10.0) {
    /* Sum: '<S1>/PID_Z' */
    hil_test_model_Y.vz = 10.0;
  } else {
    if (hil_test_model_Y.vz < -10.0) {
      /* Sum: '<S1>/PID_Z' */
      hil_test_model_Y.vz = -10.0;
    }
  }

  /* End of Saturate: '<S1>/Sat_Z' */

  /* DiscreteIntegrator: '<S1>/Pos_Z' incorporates:
   *  UnitDelay: '<S1>/FB_Z'
   */
  hil_test_model_Y.Z = hil_test_model_DW.Pos_Z_DSTATE;

  /* Outport: '<Root>/airborne' incorporates:
   *  Constant: '<S2>/Constant'
   *  RelationalOperator: '<S2>/Compare'
   *  UnitDelay: '<S1>/FB_Z'
   */
  hil_test_model_Y.airborne = (hil_test_model_Y.Z > 0.5);

  /* Update for DiscreteIntegrator: '<S1>/Int_yaw' incorporates:
   *  Inport: '<Root>/cmd_yaw'
   */
  hil_test_model_DW.Int_yaw_DSTATE += 0.001 * hil_test_model_U.cmd_yaw;

  /* Update for DiscreteIntegrator: '<S1>/I_X' incorporates:
   *  Constant: '<Root>/u_kixy'
   *  Product: '<S1>/Ig_X'
   */
  hil_test_model_DW.I_X_DSTATE += rtb_PID_Z * 0.02 * 0.001;

  /* Update for UnitDelay: '<S3>/UD'
   *
   * Block description for '<S3>/UD':
   *
   *  Store in Global RAM
   */
  hil_test_model_DW.UD_DSTATE = rtb_TSamp;

  /* Update for UnitDelay: '<S4>/UD'
   *
   * Block description for '<S4>/UD':
   *
   *  Store in Global RAM
   */
  hil_test_model_DW.UD_DSTATE_n = rtb_TSamp_g;

  /* Update for DiscreteIntegrator: '<S1>/I_Y' incorporates:
   *  Constant: '<Root>/u_kixy'
   *  Product: '<S1>/Ig_Y'
   */
  hil_test_model_DW.I_Y_DSTATE += rtb_I_Z * 0.02 * 0.001;

  /* Update for DiscreteIntegrator: '<S1>/Pos_X' */
  hil_test_model_DW.Pos_X_DSTATE += 0.001 * hil_test_model_Y.vx;

  /* Update for DiscreteIntegrator: '<S1>/Pos_Y' */
  hil_test_model_DW.Pos_Y_DSTATE += 0.001 * hil_test_model_Y.vy;

  /* Update for DiscreteIntegrator: '<S1>/I_Z' incorporates:
   *  Constant: '<Root>/u_kiz'
   *  Product: '<S1>/Ig_Z'
   */
  hil_test_model_DW.I_Z_DSTATE += rtb_err_Z * 0.05 * 0.001;

  /* Update for UnitDelay: '<S5>/UD'
   *
   * Block description for '<S5>/UD':
   *
   *  Store in Global RAM
   */
  hil_test_model_DW.UD_DSTATE_d = rtb_TSamp_f;

  /* Update for DiscreteIntegrator: '<S1>/Pos_Z' */
  hil_test_model_DW.Pos_Z_DSTATE += 0.001 * hil_test_model_Y.vz;
}

/* Model initialize function */
void hil_test_model_initialize(void)
{
  /* Registration code */

  /* initialize error status */
  rtmSetErrorStatus(hil_test_model_M, (NULL));

  /* states (dwork) */
  (void) memset((void *)&hil_test_model_DW, 0,
                sizeof(DW_hil_test_model_T));

  /* external inputs */
  (void)memset(&hil_test_model_U, 0, sizeof(ExtU_hil_test_model_T));

  /* external outputs */
  (void) memset((void *)&hil_test_model_Y, 0,
                sizeof(ExtY_hil_test_model_T));

  /* ConstCode for Outport: '<Root>/Phi' incorporates:
   *  Constant: '<S1>/zero_rp'
   */
  hil_test_model_Y.Phi = 0.0;

  /* ConstCode for Outport: '<Root>/Theta' incorporates:
   *  Constant: '<S1>/zero_rp'
   */
  hil_test_model_Y.Theta = 0.0;
}

/* Model terminate function */
void hil_test_model_terminate(void)
{
  /* (no terminate code required) */
}

/*
 * File trailer for generated code.
 *
 * [EOF]
 */
