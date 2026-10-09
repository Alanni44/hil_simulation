#ifndef DEVELOPMENT_QUAD_MODEL_H
#define DEVELOPMENT_QUAD_MODEL_H

#include <stdbool.h>

typedef struct {
    double motor_command[4];
    double wind_n_mps, wind_e_mps, wind_d_mps;
    double pressure_pa, temperature_k, ground_height_m;
    double gps_bias_n_m, gps_bias_e_m, gps_bias_d_m;
    double imu_bias_p_radps, imu_bias_q_radps, imu_bias_r_radps;
    bool motor_1_failed, motor_2_failed, motor_3_failed, motor_4_failed;
    double command_delay_ms, sensor_delay_ms, packet_loss_ratio;
} DevelopmentQuadU;

typedef struct {
    double north_m, east_m, down_m;
    double vn_mps, ve_mps, vd_mps;
    double q_w, q_x, q_y, q_z;
    double p_radps, q_radps, r_radps;
    bool airborne;
    double ax_mps2, ay_mps2, az_mps2;
} DevelopmentQuadY;

extern DevelopmentQuadU development_quad_U;
extern DevelopmentQuadY development_quad_Y;
extern double uav_mass_kg, uav_inertia_xx_kgm2, uav_inertia_yy_kgm2;
extern double uav_inertia_zz_kgm2, uav_thrust_coefficient_n;
extern double uav_moment_coefficient_nm, uav_linear_drag_ns_m;
extern double uav_angular_drag_nms, uav_wind_n_bias_mps;
extern double uav_wind_e_bias_mps, uav_wind_d_bias_mps, uav_motor_efficiency;

void development_quad_initialize(void);
void development_quad_step(void);
void development_quad_terminate(void);
DevelopmentQuadU *development_quad_get_input(void);
void development_quad_get_output(DevelopmentQuadY *out);
int development_quad_is_loaded(void);
void development_quad_read_motor_command(double out[4]);

#endif
