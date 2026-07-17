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
    int cmd_mode;
    double cmd_x, cmd_y, cmd_z;
    double cmd_speed, cmd_duration;
} my_uav_model_U;

struct {
    double pos_x, pos_y, pos_z;
    double lat, lon, alt;
    float roll, pitch, yaw;
    float vel_x, vel_y, vel_z;
    float acc_x, acc_y, acc_z;
} my_uav_model_Y;

static double sim_time = 0.0;
static double target_x = 0.0, target_y = 0.0, target_z = 0.0;
static double cmd_vx = 0.0, cmd_vy = 0.0, cmd_vz = 0.0;
static double cmd_remain = 0.0;
static int airborne = 0;

void my_uav_model_initialize(void) {
    sim_time = 0.0;
    target_x = target_y = target_z = 0.0;
    cmd_vx = cmd_vy = cmd_vz = 0.0;
    cmd_remain = 0.0;
    airborne = 0;
    memset(&my_uav_model_Y, 0, sizeof(my_uav_model_Y));
}

void my_uav_model_step(void) {
    sim_time += 0.001;
    double dt = 0.001;

    if (my_uav_model_U.cmd_mode == 1) {
        airborne = 1;
        target_z = 50.0;
        my_uav_model_U.cmd_mode = 0;
    } else if (my_uav_model_U.cmd_mode == 2) {
        airborne = 0;
        target_z = 0.0;
        my_uav_model_U.cmd_mode = 0;
    } else if (my_uav_model_U.cmd_mode == 3) {
        target_x = my_uav_model_Y.pos_x;
        target_y = my_uav_model_Y.pos_y;
        target_z = my_uav_model_Y.pos_z;
        cmd_vx = cmd_vy = cmd_vz = 0.0;
        cmd_remain = 0.0;
        my_uav_model_U.cmd_mode = 0;
    } else if (my_uav_model_U.cmd_mode == 4) {
        target_x = my_uav_model_U.cmd_x;
        target_y = my_uav_model_U.cmd_y;
        target_z = my_uav_model_U.cmd_z;
        cmd_vx = cmd_vy = cmd_vz = 0.0;
        cmd_remain = 0.0;
        my_uav_model_U.cmd_mode = 0;
    } else if (my_uav_model_U.cmd_mode == 5) {
        cmd_vx = my_uav_model_U.cmd_x;
        cmd_vy = my_uav_model_U.cmd_y;
        cmd_vz = my_uav_model_U.cmd_z;
        cmd_remain = my_uav_model_U.cmd_duration;
        my_uav_model_U.cmd_mode = 0;
    }

    if (cmd_remain > 0.0) {
        cmd_remain -= dt;
        if (cmd_remain < 0.0) { cmd_vx = cmd_vy = cmd_vz = 0.0; cmd_remain = 0.0; }
    }

    double spd = my_uav_model_U.cmd_speed > 0.0 ? my_uav_model_U.cmd_speed : 5.0;
    double dx = target_x - my_uav_model_Y.pos_x;
    double dy = target_y - my_uav_model_Y.pos_y;
    double dz = target_z - my_uav_model_Y.pos_z;
    double dist = sqrt(dx*dx + dy*dy + dz*dz);
    if (dist < 0.5) { dx = dy = dz = 0.0; }

    my_uav_model_Y.vel_x = (dist > 0.5) ? (dx / dist) * spd + cmd_vx : cmd_vx;
    my_uav_model_Y.vel_y = (dist > 0.5) ? (dy / dist) * spd + cmd_vy : cmd_vy;
    my_uav_model_Y.vel_z = (dist > 0.5) ? (dz / dist) * spd + cmd_vz : cmd_vz;

    my_uav_model_Y.pos_x += my_uav_model_Y.vel_x * dt;
    my_uav_model_Y.pos_y += my_uav_model_Y.vel_y * dt;
    my_uav_model_Y.pos_z += my_uav_model_Y.vel_z * dt;
    if (my_uav_model_Y.pos_z < 0.0) my_uav_model_Y.pos_z = 0.0;
    my_uav_model_Y.alt = my_uav_model_Y.pos_z;

    my_uav_model_Y.lat = 39.9 + my_uav_model_Y.pos_x * 0.00001;
    my_uav_model_Y.lon = 116.4 + my_uav_model_Y.pos_y * 0.00001;

    my_uav_model_Y.roll = 0.05f * (float)sin(sim_time * 0.8);
    my_uav_model_Y.pitch = 0.03f * (float)sin(sim_time * 0.6 + 0.5);
    my_uav_model_Y.yaw = 0.02f * (float)sin(sim_time * 0.3);

    my_uav_model_Y.acc_x = 0.0f;
    my_uav_model_Y.acc_y = 0.0f;
    my_uav_model_Y.acc_z = 0.0f;
}

void my_uav_model_terminate(void) {}