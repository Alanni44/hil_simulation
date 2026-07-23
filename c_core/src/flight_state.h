#ifndef FLIGHT_STATE_H
#define FLIGHT_STATE_H

#include <stdint.h>

#pragma pack(push, 1)

typedef struct {
    double init_lat, init_lon, init_alt;
    float init_roll, init_pitch, init_yaw;
    float pid_kp_roll, pid_ki_roll, pid_kd_roll;
    float pid_kp_pitch, pid_ki_pitch, pid_kd_pitch;
    float pid_kp_yaw, pid_ki_yaw, pid_kd_yaw;
    float target_alt;
    double init_x, init_y;
    float min_speed, max_speed;
    float min_height, max_height;
    uint32_t mission_id;
    uint32_t waypoint_index;
    uint8_t flight_phase;
    uint8_t reserved[3];
} ModelInput_t;

#define MAX_WAYPOINTS 50

typedef struct {
    uint32_t version;
    uint64_t timestamp_us;
    /* ---- core fields (always present, read by Python) ---- */
    double pos_x, pos_y, pos_z;
    double lat, lon, alt;
    float roll, pitch, yaw;
    float vel_x, vel_y, vel_z;
    float acc_x, acc_y, acc_z;
    float ang_vel_p, ang_vel_q, ang_vel_r;
    /* ---- telemetry fields (optional, filled with defaults if missing) ---- */
    float battery_voltage;
    float motor_speed_0, motor_speed_1, motor_speed_2, motor_speed_3;
    uint32_t status_word;
    uint32_t mission_id;
    uint32_t waypoint_index;
    uint8_t flight_phase;
    uint8_t flight_state;  /* V2.0: 0=ready 1=taking_off 2=flying 3=hovering 4=landing 5=landed 6=fault */
    uint8_t reserved[2];
} FlightState_t;

#pragma pack(pop)

#define FLIGHT_STATE_SIZE sizeof(FlightState_t)

#endif