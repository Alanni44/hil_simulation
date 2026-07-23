/* Stub model_config.h for manual GCC builds.
   When building without the MATLAB pipeline, this header provides
   the minimum symbols main_rt.c expects. */
#ifndef MODEL_CONFIG_STUB_H
#define MODEL_CONFIG_STUB_H

#define MODEL_NAME "manual_fallback"
#define MODEL_SLX ""
#define MODEL_ADAPTED 0

#define MODEL_U_TUNABLE_COUNT 0

/* Dummy tunable table — no Inports available */
#include <stddef.h>
struct _tunable_entry { const char* name; size_t offset; };
static const struct _tunable_entry MODEL_U_TUNABLE_TABLE[] = {};

#define MODEL_DEFAULT_POS_X 0.0
#define MODEL_DEFAULT_POS_Y 0.0
#define MODEL_DEFAULT_POS_Z 10.0
#define MODEL_DEFAULT_ROLL  0.0f
#define MODEL_DEFAULT_PITCH 0.0f
#define MODEL_DEFAULT_YAW   0.0f

/* Hand-written model field macros (matches my_uav_model.h) */
#define HAS_Y_pos_x 1
#define MODEL_Y_pos_x pos_x
#define HAS_Y_pos_y 1
#define MODEL_Y_pos_y pos_y
#define HAS_Y_pos_z 1
#define MODEL_Y_pos_z pos_z
#define HAS_Y_roll 1
#define MODEL_Y_roll roll
#define HAS_Y_pitch 1
#define MODEL_Y_pitch pitch
#define HAS_Y_yaw 1
#define MODEL_Y_yaw yaw
#define HAS_Y_vel_x 1
#define MODEL_Y_vel_x vel_x
#define HAS_Y_vel_y 1
#define MODEL_Y_vel_y vel_y
#define HAS_Y_vel_z 1
#define MODEL_Y_vel_z vel_z
#define HAS_Y_lat 1
#define MODEL_Y_lat lat
#define HAS_Y_lon 1
#define MODEL_Y_lon lon
#define HAS_Y_alt 1
#define MODEL_Y_alt alt
#define HAS_Y_acc_x 1
#define MODEL_Y_acc_x acc_x
#define HAS_Y_acc_y 1
#define MODEL_Y_acc_y acc_y
#define HAS_Y_acc_z 1
#define MODEL_Y_acc_z acc_z
#define HAS_Y_airborne 1
#define MODEL_Y_airborne airborne

#define HAS_U_throttle 1
#define MODEL_U_throttle throttle
#define HAS_U_pitch_cmd 1
#define MODEL_U_pitch_cmd pitch_cmd
#define HAS_U_roll_cmd 1
#define MODEL_U_roll_cmd roll_cmd
#define HAS_U_yaw_cmd 1
#define MODEL_U_yaw_cmd yaw_cmd
#define HAS_U_flight_mode 1
#define MODEL_U_flight_mode flight_mode
#define HAS_U_experiment_mode 1
#define MODEL_U_experiment_mode experiment_mode
#define HAS_U_cmd_x 1
#define MODEL_U_cmd_x cmd_x
#define HAS_U_cmd_y 1
#define MODEL_U_cmd_y cmd_y
#define HAS_U_cmd_z 1
#define MODEL_U_cmd_z cmd_z
#define HAS_U_cmd_speed 1
#define MODEL_U_cmd_speed cmd_speed
#define HAS_U_cmd_mode 1
#define MODEL_U_cmd_mode cmd_mode
#define HAS_U_cmd_duration 1
#define MODEL_U_cmd_duration cmd_duration
#define HAS_U_target_alt 1
#define MODEL_U_target_alt target_alt
#define HAS_U_lat_init 1
#define MODEL_U_lat_init lat_init
#define HAS_U_lon_init 1
#define MODEL_U_lon_init lon_init
#define HAS_U_alt_init 1
#define MODEL_U_alt_init alt_init
#define HAS_U_roll_init 1
#define MODEL_U_roll_init roll_init
#define HAS_U_pitch_init 1
#define MODEL_U_pitch_init pitch_init
#define HAS_U_yaw_init 1
#define MODEL_U_yaw_init yaw_init
#define HAS_U_init_x 1
#define MODEL_U_init_x init_x
#define HAS_U_init_y 1
#define MODEL_U_init_y init_y
#define HAS_U_min_speed 1
#define MODEL_U_min_speed min_speed
#define HAS_U_max_speed 1
#define MODEL_U_max_speed max_speed
#define HAS_U_min_height 1
#define MODEL_U_min_height min_height
#define HAS_U_max_height 1
#define MODEL_U_max_height max_height
#define HAS_U_pid_kp_roll 1
#define MODEL_U_pid_kp_roll pid_kp_roll
#define HAS_U_pid_ki_roll 1
#define MODEL_U_pid_ki_roll pid_ki_roll
#define HAS_U_pid_kd_roll 1
#define MODEL_U_pid_kd_roll pid_kd_roll
#define HAS_U_pid_kp_pitch 1
#define MODEL_U_pid_kp_pitch pid_kp_pitch
#define HAS_U_pid_ki_pitch 1
#define MODEL_U_pid_ki_pitch pid_ki_pitch
#define HAS_U_pid_kd_pitch 1
#define MODEL_U_pid_kd_pitch pid_kd_pitch
#define HAS_U_pid_kp_yaw 1
#define MODEL_U_pid_kp_yaw pid_kp_yaw
#define HAS_U_pid_ki_yaw 1
#define MODEL_U_pid_ki_yaw pid_ki_yaw
#define HAS_U_pid_kd_yaw 1
#define MODEL_U_pid_kd_yaw pid_kd_yaw

#endif
