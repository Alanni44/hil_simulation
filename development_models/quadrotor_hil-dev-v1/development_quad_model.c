#include "development_quad_model.h"

#include <math.h>
#include <string.h>

#define DT 0.001
#define GRAVITY 9.80665

DevelopmentQuadU development_quad_U;
DevelopmentQuadY development_quad_Y;
double uav_mass_kg = 1.5;
double uav_inertia_xx_kgm2 = 0.029;
double uav_inertia_yy_kgm2 = 0.029;
double uav_inertia_zz_kgm2 = 0.055;
double uav_thrust_coefficient_n = 4.2;
double uav_moment_coefficient_nm = 0.08;
double uav_linear_drag_ns_m = 0.25;
double uav_angular_drag_nms = 0.02;
double uav_wind_n_bias_mps = 0.0;
double uav_wind_e_bias_mps = 0.0;
double uav_wind_d_bias_mps = 0.0;
double uav_motor_efficiency = 1.0;
static int loaded = 0;

static double enabled_motor(unsigned index) {
    const bool failed[4] = {development_quad_U.motor_1_failed, development_quad_U.motor_2_failed,
                            development_quad_U.motor_3_failed, development_quad_U.motor_4_failed};
    return failed[index] ? 0.0 : development_quad_U.motor_command[index];
}

void development_quad_initialize(void) {
    memset(&development_quad_U, 0, sizeof(development_quad_U));
    memset(&development_quad_Y, 0, sizeof(development_quad_Y));
    development_quad_U.pressure_pa = 101325.0;
    development_quad_U.temperature_k = 288.15;
    development_quad_Y.q_w = 1.0;
    loaded = 1;
}

void development_quad_step(void) {
    double m[4], thrust = 0.0, roll_torque, pitch_torque, yaw_torque;
    double wind_n, wind_e, wind_d, mass;
    unsigned index;
    if (!loaded) return;
    for (index = 0; index < 4; ++index) {
        m[index] = enabled_motor(index);
        thrust += uav_thrust_coefficient_n * uav_motor_efficiency * m[index] * m[index];
    }
    mass = uav_mass_kg;
    wind_n = development_quad_U.wind_n_mps + uav_wind_n_bias_mps;
    wind_e = development_quad_U.wind_e_mps + uav_wind_e_bias_mps;
    wind_d = development_quad_U.wind_d_mps + uav_wind_d_bias_mps;
    development_quad_Y.ax_mps2 = -uav_linear_drag_ns_m * (development_quad_Y.vn_mps - wind_n) / mass;
    development_quad_Y.ay_mps2 = -uav_linear_drag_ns_m * (development_quad_Y.ve_mps - wind_e) / mass;
    development_quad_Y.az_mps2 = GRAVITY - thrust / mass
        - uav_linear_drag_ns_m * (development_quad_Y.vd_mps - wind_d) / mass;
    roll_torque = (m[0] - m[1] - m[2] + m[3]) * uav_moment_coefficient_nm;
    pitch_torque = (m[0] + m[1] - m[2] - m[3]) * uav_moment_coefficient_nm;
    yaw_torque = (m[0] - m[1] + m[2] - m[3]) * uav_moment_coefficient_nm;
    development_quad_Y.p_radps += DT * (roll_torque / uav_inertia_xx_kgm2
        - uav_angular_drag_nms * development_quad_Y.p_radps / uav_inertia_xx_kgm2);
    development_quad_Y.q_radps += DT * (pitch_torque / uav_inertia_yy_kgm2
        - uav_angular_drag_nms * development_quad_Y.q_radps / uav_inertia_yy_kgm2);
    development_quad_Y.r_radps += DT * (yaw_torque / uav_inertia_zz_kgm2
        - uav_angular_drag_nms * development_quad_Y.r_radps / uav_inertia_zz_kgm2);
    development_quad_Y.vn_mps += DT * development_quad_Y.ax_mps2;
    development_quad_Y.ve_mps += DT * development_quad_Y.ay_mps2;
    development_quad_Y.vd_mps += DT * development_quad_Y.az_mps2;
    development_quad_Y.north_m += DT * development_quad_Y.vn_mps + development_quad_U.gps_bias_n_m;
    development_quad_Y.east_m += DT * development_quad_Y.ve_mps + development_quad_U.gps_bias_e_m;
    development_quad_Y.down_m += DT * development_quad_Y.vd_mps + development_quad_U.gps_bias_d_m;
    development_quad_Y.airborne = development_quad_Y.down_m < development_quad_U.ground_height_m - 0.001;
}

void development_quad_terminate(void) { loaded = 0; }
DevelopmentQuadU *development_quad_get_input(void) { return &development_quad_U; }
void development_quad_get_output(DevelopmentQuadY *out) { if (out) *out = development_quad_Y; }
int development_quad_is_loaded(void) { return loaded; }
void development_quad_read_motor_command(double out[4]) {
    if (out) memcpy(out, development_quad_U.motor_command, sizeof(development_quad_U.motor_command));
}
