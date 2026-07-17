#include "my_uav_model.h"
#include <math.h>
#include <string.h>

struct {
    double lat_init, lon_init, alt_init;
    float roll_init, pitch_init, yaw_init;
    float pid_kp_roll, pid_ki_roll, pid_kd_roll;
    float pid_kp_pitch, pid_ki_pitch, pid_kd_pitch;
    float pid_kp_yaw, pid_ki_yaw, pid_kd_yaw;
    float target_alt;
} my_uav_model_U;

struct {
    double pos_x, pos_y, pos_z;
    double lat, lon, alt;
    float roll, pitch, yaw;
    float vel_x, vel_y, vel_z;
    float acc_x, acc_y, acc_z;
} my_uav_model_Y;

static double sim_time = 0.0;

void my_uav_model_initialize(void) {
    sim_time = 0.0;
    memset(&my_uav_model_Y, 0, sizeof(my_uav_model_Y));
}

void my_uav_model_step(void) {
    sim_time += 0.001;

    my_uav_model_Y.pos_x = sim_time * 5.0;
    my_uav_model_Y.pos_y = 5.0 * sin(sim_time * 0.5);
    my_uav_model_Y.pos_z = 100.0 + 10.0 * sin(sim_time * 0.2);
    my_uav_model_Y.lat = 39.9 + sim_time * 0.00001;
    my_uav_model_Y.lon = 116.4 + sim_time * 0.00001;
    my_uav_model_Y.alt = my_uav_model_Y.pos_z;
    my_uav_model_Y.roll = 0.05f * (float)sin(sim_time * 0.8);
    my_uav_model_Y.pitch = 0.03f * (float)sin(sim_time * 0.6 + 0.5);
    my_uav_model_Y.yaw = 0.02f * (float)sin(sim_time * 0.3);
    my_uav_model_Y.vel_x = 5.0f;
    my_uav_model_Y.vel_y = 2.5f * (float)cos(sim_time * 0.5);
    my_uav_model_Y.vel_z = 2.0f * (float)cos(sim_time * 0.2);
    my_uav_model_Y.acc_x = 0.0f;
    my_uav_model_Y.acc_y = -1.25f * (float)sin(sim_time * 0.5);
    my_uav_model_Y.acc_z = -2.0f * (float)sin(sim_time * 0.2);
}

void my_uav_model_terminate(void) {}