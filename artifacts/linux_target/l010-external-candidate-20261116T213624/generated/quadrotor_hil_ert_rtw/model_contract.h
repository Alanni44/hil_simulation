#ifndef HIL_MODEL_CONTRACT_H
#define HIL_MODEL_CONTRACT_H
#include <string.h>
#define MODEL_READ_north_m(y) ((y)->north_m)
#define MODEL_READ_east_m(y) ((y)->east_m)
#define MODEL_READ_down_m(y) ((y)->down_m)
#define MODEL_READ_vn_mps(y) ((y)->vn_mps)
#define MODEL_READ_ve_mps(y) ((y)->ve_mps)
#define MODEL_READ_vd_mps(y) ((y)->vd_mps)
#define MODEL_READ_q_w(y) ((y)->q_w)
#define MODEL_READ_q_x(y) ((y)->q_x)
#define MODEL_READ_q_y(y) ((y)->q_y)
#define MODEL_READ_q_z(y) ((y)->q_z)
#define MODEL_READ_p_radps(y) ((y)->p_radps)
#define MODEL_READ_q_radps(y) ((y)->q_radps)
#define MODEL_READ_r_radps(y) ((y)->r_radps)
#define MODEL_READ_airborne(y) ((y)->airborne)
#define HIL_CONTRACT_INITIAL_STATE 1
typedef struct { double north_m,east_m,down_m; double vn_mps,ve_mps,vd_mps; double q_w,q_x,q_y,q_z; double p_radps,q_radps,r_radps; int airborne; } HilInitialState;
static int hil_contract_set_initial_state(const HilInitialState* s) { if (!s) return 0; MODEL_DW_VAR.position_ned[0]=s->north_m; MODEL_DW_VAR.position_ned[1]=s->east_m; MODEL_DW_VAR.position_ned[2]=s->down_m; MODEL_DW_VAR.velocity_ned[0]=s->vn_mps; MODEL_DW_VAR.velocity_ned[1]=s->ve_mps; MODEL_DW_VAR.velocity_ned[2]=s->vd_mps; MODEL_DW_VAR.quaternion_frd_to_ned[0]=s->q_w; MODEL_DW_VAR.quaternion_frd_to_ned[1]=s->q_x; MODEL_DW_VAR.quaternion_frd_to_ned[2]=s->q_y; MODEL_DW_VAR.quaternion_frd_to_ned[3]=s->q_z; MODEL_DW_VAR.body_rates[0]=s->p_radps; MODEL_DW_VAR.body_rates[1]=s->q_radps; MODEL_DW_VAR.body_rates[2]=s->r_radps; return 1; }
static int hil_contract_get_initial_state(HilInitialState* s, double ground_height_m) { if (!s) return 0; s->north_m=MODEL_DW_VAR.position_ned[0]; s->east_m=MODEL_DW_VAR.position_ned[1]; s->down_m=MODEL_DW_VAR.position_ned[2]; s->vn_mps=MODEL_DW_VAR.velocity_ned[0]; s->ve_mps=MODEL_DW_VAR.velocity_ned[1]; s->vd_mps=MODEL_DW_VAR.velocity_ned[2]; s->q_w=MODEL_DW_VAR.quaternion_frd_to_ned[0]; s->q_x=MODEL_DW_VAR.quaternion_frd_to_ned[1]; s->q_y=MODEL_DW_VAR.quaternion_frd_to_ned[2]; s->q_z=MODEL_DW_VAR.quaternion_frd_to_ned[3]; s->p_radps=MODEL_DW_VAR.body_rates[0]; s->q_radps=MODEL_DW_VAR.body_rates[1]; s->r_radps=MODEL_DW_VAR.body_rates[2]; s->airborne=s->down_m < -ground_height_m; return 1; }
#define MODEL_READ_ax_mps2(y) ((y)->ax_mps2)
#define MODEL_READ_ay_mps2(y) ((y)->ay_mps2)
#define MODEL_READ_az_mps2(y) ((y)->az_mps2)
#define HIL_INPUT_COUNT 20
typedef struct { const char* name; int is_bool; unsigned dimension; double min_value; double max_value; } HilInputSpec;
static const HilInputSpec HIL_INPUT_SPECS[HIL_INPUT_COUNT ? HIL_INPUT_COUNT : 1] = {
{"flight_control.motor_command", 0, 4, 0, 1},
{"environment.wind_n_mps", 0, 1, -50, 50},
{"environment.wind_e_mps", 0, 1, -50, 50},
{"environment.wind_d_mps", 0, 1, -50, 50},
{"environment.pressure_pa", 0, 1, 1000, 120000},
{"environment.temperature_k", 0, 1, 150, 350},
{"environment.ground_height_m", 0, 1, -1000, 10000},
{"fault.gps_bias_n_m", 0, 1, -1000, 1000},
{"fault.gps_bias_e_m", 0, 1, -1000, 1000},
{"fault.gps_bias_d_m", 0, 1, -1000, 1000},
{"fault.imu_bias_p_radps", 0, 1, -10, 10},
{"fault.imu_bias_q_radps", 0, 1, -10, 10},
{"fault.imu_bias_r_radps", 0, 1, -10, 10},
{"fault.motor_1_failed", 1, 1, 0, 1},
{"fault.motor_2_failed", 1, 1, 0, 1},
{"fault.motor_3_failed", 1, 1, 0, 1},
{"fault.motor_4_failed", 1, 1, 0, 1},
{"fault.command_delay_ms", 0, 1, 0, 1000},
{"fault.sensor_delay_ms", 0, 1, 0, 1000},
{"fault.packet_loss_ratio", 0, 1, 0, 1},
};
static const HilInputSpec* hil_contract_find_input(const char* name) { unsigned i; for (i=0; i<HIL_INPUT_COUNT; ++i) if (!strcmp(HIL_INPUT_SPECS[i].name,name)) return &HIL_INPUT_SPECS[i]; return 0; }
static int hil_contract_set_input(ModelU_t* u, const char* name, const double* values, unsigned count) {
if (!strcmp(name,"flight_control.motor_command")) { if (count != 4) return 0; u->motor_command[0] = (double)values[0]; u->motor_command[1] = (double)values[1]; u->motor_command[2] = (double)values[2]; u->motor_command[3] = (double)values[3]; return 1; }
if (!strcmp(name,"environment.wind_n_mps")) { if (count != 1) return 0; u->wind_n_mps = (double)values[0]; return 1; }
if (!strcmp(name,"environment.wind_e_mps")) { if (count != 1) return 0; u->wind_e_mps = (double)values[0]; return 1; }
if (!strcmp(name,"environment.wind_d_mps")) { if (count != 1) return 0; u->wind_d_mps = (double)values[0]; return 1; }
if (!strcmp(name,"environment.pressure_pa")) { if (count != 1) return 0; u->pressure_pa = (double)values[0]; return 1; }
if (!strcmp(name,"environment.temperature_k")) { if (count != 1) return 0; u->temperature_k = (double)values[0]; return 1; }
if (!strcmp(name,"environment.ground_height_m")) { if (count != 1) return 0; u->ground_height_m = (double)values[0]; return 1; }
if (!strcmp(name,"fault.gps_bias_n_m")) { if (count != 1) return 0; u->gps_bias_n_m = (double)values[0]; return 1; }
if (!strcmp(name,"fault.gps_bias_e_m")) { if (count != 1) return 0; u->gps_bias_e_m = (double)values[0]; return 1; }
if (!strcmp(name,"fault.gps_bias_d_m")) { if (count != 1) return 0; u->gps_bias_d_m = (double)values[0]; return 1; }
if (!strcmp(name,"fault.imu_bias_p_radps")) { if (count != 1) return 0; u->imu_bias_p_radps = (double)values[0]; return 1; }
if (!strcmp(name,"fault.imu_bias_q_radps")) { if (count != 1) return 0; u->imu_bias_q_radps = (double)values[0]; return 1; }
if (!strcmp(name,"fault.imu_bias_r_radps")) { if (count != 1) return 0; u->imu_bias_r_radps = (double)values[0]; return 1; }
if (!strcmp(name,"fault.motor_1_failed")) { if (count != 1) return 0; u->motor_1_failed = values[0] != 0.0; return 1; }
if (!strcmp(name,"fault.motor_2_failed")) { if (count != 1) return 0; u->motor_2_failed = values[0] != 0.0; return 1; }
if (!strcmp(name,"fault.motor_3_failed")) { if (count != 1) return 0; u->motor_3_failed = values[0] != 0.0; return 1; }
if (!strcmp(name,"fault.motor_4_failed")) { if (count != 1) return 0; u->motor_4_failed = values[0] != 0.0; return 1; }
if (!strcmp(name,"fault.command_delay_ms")) { if (count != 1) return 0; u->command_delay_ms = (double)values[0]; return 1; }
if (!strcmp(name,"fault.sensor_delay_ms")) { if (count != 1) return 0; u->sensor_delay_ms = (double)values[0]; return 1; }
if (!strcmp(name,"fault.packet_loss_ratio")) { if (count != 1) return 0; u->packet_loss_ratio = (double)values[0]; return 1; }
(void)u; (void)name; (void)values; (void)count; return 0; }
#define HIL_CONTRACT_GET_INPUT 1
static int hil_contract_get_input(const ModelU_t* u, const char* name, double* values, unsigned count) {
if (!strcmp(name,"flight_control.motor_command")) { if (count != 4) return 0; values[0] = (double)u->motor_command[0]; values[1] = (double)u->motor_command[1]; values[2] = (double)u->motor_command[2]; values[3] = (double)u->motor_command[3]; return 1; }
if (!strcmp(name,"environment.wind_n_mps")) { if (count != 1) return 0; values[0] = (double)u->wind_n_mps; return 1; }
if (!strcmp(name,"environment.wind_e_mps")) { if (count != 1) return 0; values[0] = (double)u->wind_e_mps; return 1; }
if (!strcmp(name,"environment.wind_d_mps")) { if (count != 1) return 0; values[0] = (double)u->wind_d_mps; return 1; }
if (!strcmp(name,"environment.pressure_pa")) { if (count != 1) return 0; values[0] = (double)u->pressure_pa; return 1; }
if (!strcmp(name,"environment.temperature_k")) { if (count != 1) return 0; values[0] = (double)u->temperature_k; return 1; }
if (!strcmp(name,"environment.ground_height_m")) { if (count != 1) return 0; values[0] = (double)u->ground_height_m; return 1; }
if (!strcmp(name,"fault.gps_bias_n_m")) { if (count != 1) return 0; values[0] = (double)u->gps_bias_n_m; return 1; }
if (!strcmp(name,"fault.gps_bias_e_m")) { if (count != 1) return 0; values[0] = (double)u->gps_bias_e_m; return 1; }
if (!strcmp(name,"fault.gps_bias_d_m")) { if (count != 1) return 0; values[0] = (double)u->gps_bias_d_m; return 1; }
if (!strcmp(name,"fault.imu_bias_p_radps")) { if (count != 1) return 0; values[0] = (double)u->imu_bias_p_radps; return 1; }
if (!strcmp(name,"fault.imu_bias_q_radps")) { if (count != 1) return 0; values[0] = (double)u->imu_bias_q_radps; return 1; }
if (!strcmp(name,"fault.imu_bias_r_radps")) { if (count != 1) return 0; values[0] = (double)u->imu_bias_r_radps; return 1; }
if (!strcmp(name,"fault.motor_1_failed")) { if (count != 1) return 0; values[0] = (double)u->motor_1_failed; return 1; }
if (!strcmp(name,"fault.motor_2_failed")) { if (count != 1) return 0; values[0] = (double)u->motor_2_failed; return 1; }
if (!strcmp(name,"fault.motor_3_failed")) { if (count != 1) return 0; values[0] = (double)u->motor_3_failed; return 1; }
if (!strcmp(name,"fault.motor_4_failed")) { if (count != 1) return 0; values[0] = (double)u->motor_4_failed; return 1; }
if (!strcmp(name,"fault.command_delay_ms")) { if (count != 1) return 0; values[0] = (double)u->command_delay_ms; return 1; }
if (!strcmp(name,"fault.sensor_delay_ms")) { if (count != 1) return 0; values[0] = (double)u->sensor_delay_ms; return 1; }
if (!strcmp(name,"fault.packet_loss_ratio")) { if (count != 1) return 0; values[0] = (double)u->packet_loss_ratio; return 1; }
(void)u; (void)name; (void)values; (void)count; return 0; }
#define HIL_ACTUATOR_COUNT 4
typedef struct { double min_value; double max_value; double safe_value; } HilActuatorSpec;
static const HilActuatorSpec HIL_ACTUATOR_SPECS[HIL_ACTUATOR_COUNT ? HIL_ACTUATOR_COUNT : 1] = {
{0, 1, 0},
{0, 1, 0},
{0, 1, 0},
{0, 1, 0},
};
#define HIL_CONTROL_SOURCE_MASK 7U
#define HIL_DEMO_MISSION_ENABLED 1
#define HIL_FIXED_WING 0
#define HIL_FIXED_WING_V3_TCP 0
static int hil_contract_set_actuators(ModelU_t* u, const double* values, unsigned count) { if (count != HIL_ACTUATOR_COUNT) return 0;
u->motor_command[0] = (double)values[0];
u->motor_command[1] = (double)values[1];
u->motor_command[2] = (double)values[2];
u->motor_command[3] = (double)values[3];
return 1; }
enum { HIL_PARAM_LIVE=1, HIL_PARAM_RESET_ONLY=2, HIL_PARAM_READONLY=3 };
#define HIL_PARAMETER_COUNT 12
typedef struct { double value[HIL_PARAMETER_COUNT ? HIL_PARAMETER_COUNT : 1]; } HilParameterValues;
typedef struct { const char* name; const char* unit; const char* review_status; int klass; double default_value; double min_value; double max_value; int is_bool; unsigned phase_mask; } HilParameterSpec;
#define HIL_PARAMETER_METADATA 1
static const HilParameterSpec HIL_PARAMETER_SPECS[HIL_PARAMETER_COUNT ? HIL_PARAMETER_COUNT : 1] = {
{"mass_kg", "kg", "approved", HIL_PARAM_LIVE, 1.5, 0.20000000000000001, 25, 0, 3},
{"inertia_xx_kgm2", "kg*m2", "approved", HIL_PARAM_LIVE, 0.029000000000000001, 0.001, 2, 0, 3},
{"inertia_yy_kgm2", "kg*m2", "approved", HIL_PARAM_LIVE, 0.029000000000000001, 0.001, 2, 0, 3},
{"inertia_zz_kgm2", "kg*m2", "approved", HIL_PARAM_LIVE, 0.055, 0.001, 4, 0, 3},
{"thrust_coefficient_n", "N", "approved", HIL_PARAM_LIVE, 4.2000000000000002, 0.5, 20, 0, 3},
{"moment_coefficient_nm", "N*m", "approved", HIL_PARAM_LIVE, 0.080000000000000002, 0.001, 2, 0, 3},
{"linear_drag_ns_m", "N*s/m", "approved", HIL_PARAM_LIVE, 0.25, 0, 20, 0, 3},
{"angular_drag_nms", "N*m*s", "approved", HIL_PARAM_LIVE, 0.02, 0, 5, 0, 3},
{"wind_n_bias_mps", "m/s", "approved", HIL_PARAM_LIVE, 0, -30, 30, 0, 3},
{"wind_e_bias_mps", "m/s", "approved", HIL_PARAM_LIVE, 0, -30, 30, 0, 3},
{"wind_d_bias_mps", "m/s", "approved", HIL_PARAM_LIVE, 0, -30, 30, 0, 3},
{"motor_efficiency", "1", "approved", HIL_PARAM_LIVE, 1, 0.20000000000000001, 1.2, 0, 3},
};
extern real_T uav_mass_kg;
extern real_T uav_inertia_xx_kgm2;
extern real_T uav_inertia_yy_kgm2;
extern real_T uav_inertia_zz_kgm2;
extern real_T uav_thrust_coefficient_n;
extern real_T uav_moment_coefficient_nm;
extern real_T uav_linear_drag_ns_m;
extern real_T uav_angular_drag_nms;
extern real_T uav_wind_n_bias_mps;
extern real_T uav_wind_e_bias_mps;
extern real_T uav_wind_d_bias_mps;
extern real_T uav_motor_efficiency;
static unsigned hil_contract_phase_mask(const char* name) { unsigned i; for (i=0; i<HIL_PARAMETER_COUNT; ++i) if (!strcmp(HIL_PARAMETER_SPECS[i].name,name)) return HIL_PARAMETER_SPECS[i].phase_mask; return 0; }
static void hil_contract_apply_defaults(ModelU_t* u, HilParameterValues* values) {
u->wind_n_mps = (double)0;
u->wind_e_mps = (double)0;
u->wind_d_mps = (double)0;
u->pressure_pa = (double)101325;
u->temperature_k = (double)288.14999999999998;
u->ground_height_m = (double)0;
values->value[0] = 1.5;
values->value[1] = 0.029000000000000001;
values->value[2] = 0.029000000000000001;
values->value[3] = 0.055;
values->value[4] = 4.2000000000000002;
values->value[5] = 0.080000000000000002;
values->value[6] = 0.25;
values->value[7] = 0.02;
values->value[8] = 0;
values->value[9] = 0;
values->value[10] = 0;
values->value[11] = 1;
}
static void hil_contract_apply_exported_globals(const HilParameterValues* values) {
uav_mass_kg = (double)values->value[0];
uav_inertia_xx_kgm2 = (double)values->value[1];
uav_inertia_yy_kgm2 = (double)values->value[2];
uav_inertia_zz_kgm2 = (double)values->value[3];
uav_thrust_coefficient_n = (double)values->value[4];
uav_moment_coefficient_nm = (double)values->value[5];
uav_linear_drag_ns_m = (double)values->value[6];
uav_angular_drag_nms = (double)values->value[7];
uav_wind_n_bias_mps = (double)values->value[8];
uav_wind_e_bias_mps = (double)values->value[9];
uav_wind_d_bias_mps = (double)values->value[10];
uav_motor_efficiency = (double)values->value[11];
}
static int hil_contract_set_parameter(ModelU_t* u, HilParameterValues* values, const char* name, double value) {
if (!strcmp(name,"mass_kg")) { values->value[0] = value; return 1; }
if (!strcmp(name,"inertia_xx_kgm2")) { values->value[1] = value; return 1; }
if (!strcmp(name,"inertia_yy_kgm2")) { values->value[2] = value; return 1; }
if (!strcmp(name,"inertia_zz_kgm2")) { values->value[3] = value; return 1; }
if (!strcmp(name,"thrust_coefficient_n")) { values->value[4] = value; return 1; }
if (!strcmp(name,"moment_coefficient_nm")) { values->value[5] = value; return 1; }
if (!strcmp(name,"linear_drag_ns_m")) { values->value[6] = value; return 1; }
if (!strcmp(name,"angular_drag_nms")) { values->value[7] = value; return 1; }
if (!strcmp(name,"wind_n_bias_mps")) { values->value[8] = value; return 1; }
if (!strcmp(name,"wind_e_bias_mps")) { values->value[9] = value; return 1; }
if (!strcmp(name,"wind_d_bias_mps")) { values->value[10] = value; return 1; }
if (!strcmp(name,"motor_efficiency")) { values->value[11] = value; return 1; }
(void)u; (void)values; (void)name; (void)value; return 0; }
#endif
