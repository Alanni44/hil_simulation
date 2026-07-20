#ifndef MODEL_RT_WRAPPER_H
#define MODEL_RT_WRAPPER_H

#ifdef __cplusplus
extern "C" {
#endif

/* Model input struct — must match what Simulink ERT generates */
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
    float throttle;
    float pitch_cmd;
    float roll_cmd;
    float yaw_cmd;
    int flight_mode;
    int experiment_mode;
    double init_x, init_y;
    float min_speed, max_speed;
    float min_height, max_height;
} ModelU_t;

/* Model output struct — must match what Simulink ERT generates */
typedef struct {
    double pos_x, pos_y, pos_z;
    double lat, lon, alt;
    float roll, pitch, yaw;
    float vel_x, vel_y, vel_z;
    float acc_x, acc_y, acc_z;
    int airborne;
} ModelY_t;

/* ---- Static-link model API ---- */

void model_initialize(void);
void model_step(void);
void model_terminate(void);
ModelU_t* model_get_input(void);
void model_get_output(ModelY_t* out);
int model_is_loaded(void);

/* Hot-reload via execv */
void model_check_for_update(void);
void model_apply_pending_update(int* argc_ptr, char** argv);

#ifdef __cplusplus
}
#endif

#endif
