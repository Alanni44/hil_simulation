#ifndef MODEL_RT_WRAPPER_H
#define MODEL_RT_WRAPPER_H

#ifdef __cplusplus
extern "C" {
#endif

/* The build script provides the generated ERT ABI through this header.
 * Include it before declaring development fallbacks so every translation
 * unit sees the exact same ModelU_t and ModelY_t definitions. */
#if defined(MODEL_RT_BRIDGE_HEADER)
#define MODEL_RT_STRINGIFY_(x) #x
#define MODEL_RT_STRINGIFY(x) MODEL_RT_STRINGIFY_(x)
#include MODEL_RT_STRINGIFY(MODEL_RT_BRIDGE_HEADER)
#endif

/*
 * When MODEL_RT_BRIDGE_HEADER is defined (by build_script.m at compile time),
 * the bridge header provides ModelU_t and ModelY_t typedefs automatically
 * (pointing to the generated model's actual struct types).
 *
 * The manual definitions below serve as a FALLBACK for development only.
 * They are #ifndef-guarded so the generated types always win.
 */

#ifndef MODEL_U_T_DEFINED
/* Fallback ModelU_t — only used when building without auto-generated bridge */
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
    float throttle, pitch_cmd, roll_cmd, yaw_cmd;
    int flight_mode, experiment_mode;
    double init_x, init_y;
    float min_speed, max_speed, min_height, max_height;
} ModelU_t;
#define MODEL_U_T_DEFINED 1
#endif

#ifndef MODEL_Y_T_DEFINED
/* Fallback ModelY_t — only used when building without auto-generated bridge */
typedef struct {
    double pos_x, pos_y, pos_z;
    double lat, lon, alt;
    float roll, pitch, yaw;
    float vel_x, vel_y, vel_z;
    float acc_x, acc_y, acc_z;
    int airborne;
} ModelY_t;
#define MODEL_Y_T_DEFINED 1
#endif

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
