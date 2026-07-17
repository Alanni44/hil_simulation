#ifndef MY_UAV_MODEL_H
#define MY_UAV_MODEL_H

#ifdef __cplusplus
extern "C" {
#endif

void my_uav_model_initialize(void);
void my_uav_model_step(void);
void my_uav_model_terminate(void);

extern struct {
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

extern struct {
    double pos_x, pos_y, pos_z;
    double lat, lon, alt;
    float roll, pitch, yaw;
    float vel_x, vel_y, vel_z;
    float acc_x, acc_y, acc_z;
} my_uav_model_Y;

#ifdef __cplusplus
}
#endif

#endif