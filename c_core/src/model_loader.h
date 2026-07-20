/*
 * DEPRECATED — replaced by model_rt_wrapper.h for standalone executable builds.
 * Kept for reference; no longer compiled into the RT binary.
 */
#ifndef MODEL_LOADER_H
#define MODEL_LOADER_H

#include <stdint.h>

// 模型输入结构体（必须与 .so 中一致）
typedef struct {
    double lat_init, lon_init, alt_init;
    float roll_init, pitch_init, yaw_init;
    float pid_kp_roll, pid_ki_roll, pid_kd_roll;
    float pid_kp_pitch, pid_ki_pitch, pid_kd_pitch;
    float pid_kp_yaw, pid_ki_yaw, pid_kd_yaw;
    float target_alt;
    int cmd_mode;
    double cmd_x, cmd_y, cmd_z;
    double cmd_speed, cmd_duration;
    /* --- tune params --- */
    float throttle;
    float pitch_cmd;
    float roll_cmd;
    float yaw_cmd;
    int flight_mode;
    int experiment_mode;
    /* --- init params --- */
    double init_x, init_y;
    float min_speed, max_speed;
    float min_height, max_height;
} ModelLoader_U_t;

// 模型输出结构体（必须与 .so 中一致）
typedef struct {
    double pos_x, pos_y, pos_z;
    double lat, lon, alt;
    float roll, pitch, yaw;
    float vel_x, vel_y, vel_z;
    float acc_x, acc_y, acc_z;
    int airborne;
} ModelLoader_Y_t;

// ---------- API ----------
int model_load(const char* so_path);
void model_unload(void);
int model_is_loaded(void);
void model_step_call(void);
void model_get_output(ModelLoader_Y_t* out);
ModelLoader_U_t* model_get_input(void);
const char* model_get_version(void);

// 热加载检测
void model_check_for_update(void);
void model_apply_pending_update(void);

#endif