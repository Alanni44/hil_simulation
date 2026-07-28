#include "mission_controller.h"

#include <math.h>
#include <string.h>

#define GRAVITY_MPS2 9.80665
#define NOMINAL_MASS_KG 1.5
#define NOMINAL_MOTOR_THRUST_N 4.2
#define MAX_HORIZONTAL_ACCEL_MPS2 2.5
#define MAX_VERTICAL_ACCEL_MPS2 2.0
#define MAX_TILT_RAD 0.45
#define PI 3.14159265358979323846

typedef struct {
    MissionWaypoint waypoints[MISSION_CONTROLLER_MAX_WAYPOINTS];
    unsigned count;
    unsigned target_index;
    double completion_radius_m;
    MissionPhase phase;
    int loaded;
    int landed_event_pending;
} MissionController;

static MissionController controller;

static double clamp_double(double value, double minimum, double maximum)
{
    if (value < minimum) return minimum;
    if (value > maximum) return maximum;
    return value;
}

static double wrap_pi(double angle)
{
    while (angle > PI) angle -= 2.0 * PI;
    while (angle < -PI) angle += 2.0 * PI;
    return angle;
}

static void zero_motors(float motor[4])
{
    unsigned index;
    if (!motor) return;
    for (index = 0; index < 4; ++index) motor[index] = 0.0f;
}

static int waypoint_is_valid(const MissionWaypoint* waypoint)
{
    return waypoint && isfinite(waypoint->north_m) &&
           isfinite(waypoint->east_m) && isfinite(waypoint->down_m) &&
           isfinite(waypoint->speed_mps) && waypoint->speed_mps > 0.0;
}

static int state_is_usable(const FlightState_t* state)
{
    double quaternion_norm;
    if (!state || !isfinite(state->north_m) || !isfinite(state->east_m) ||
        !isfinite(state->down_m) || !isfinite(state->vn_mps) ||
        !isfinite(state->ve_mps) || !isfinite(state->vd_mps) ||
        !isfinite(state->q_w) || !isfinite(state->q_x) ||
        !isfinite(state->q_y) || !isfinite(state->q_z) ||
        !isfinite(state->p_radps) || !isfinite(state->q_radps) ||
        !isfinite(state->r_radps)) return 0;
    quaternion_norm = sqrt((double)state->q_w * state->q_w +
                           (double)state->q_x * state->q_x +
                           (double)state->q_y * state->q_y +
                           (double)state->q_z * state->q_z);
    return quaternion_norm > 1.0e-6;
}

static double distance_to(const FlightState_t* state,
                          const MissionWaypoint* waypoint)
{
    const double north_error = waypoint->north_m - state->north_m;
    const double east_error = waypoint->east_m - state->east_m;
    const double down_error = waypoint->down_m - state->down_m;
    return sqrt(north_error * north_error + east_error * east_error +
                down_error * down_error);
}

static void advance_phase_if_complete(const FlightState_t* state)
{
    const MissionWaypoint* target = &controller.waypoints[controller.target_index];
    if (distance_to(state, target) >= controller.completion_radius_m) return;

    if (controller.phase == MISSION_TAKEOFF) {
        if (controller.count == 2U) {
            controller.phase = MISSION_LANDING;
            controller.target_index = 1U;
        } else {
            controller.phase = MISSION_FLYING;
            controller.target_index = 1U;
        }
    } else if (controller.phase == MISSION_FLYING) {
        if (controller.target_index + 1U < controller.count - 1U) {
            ++controller.target_index;
        } else {
            controller.phase = MISSION_LANDING;
            controller.target_index = controller.count - 1U;
        }
    } else if (controller.phase == MISSION_LANDING) {
        controller.phase = MISSION_LANDED;
        controller.landed_event_pending = 1;
    }
}

static void quaternion_to_euler(const FlightState_t* state, double* roll,
                                double* pitch, double* yaw)
{
    const double norm = sqrt((double)state->q_w * state->q_w +
                             (double)state->q_x * state->q_x +
                             (double)state->q_y * state->q_y +
                             (double)state->q_z * state->q_z);
    const double qw = state->q_w / norm;
    const double qx = state->q_x / norm;
    const double qy = state->q_y / norm;
    const double qz = state->q_z / norm;
    const double pitch_sine = clamp_double(2.0 * (qw * qy - qz * qx), -1.0, 1.0);
    *roll = atan2(2.0 * (qw * qx + qy * qz),
                  1.0 - 2.0 * (qx * qx + qy * qy));
    *pitch = asin(pitch_sine);
    *yaw = atan2(2.0 * (qw * qz + qx * qy),
                 1.0 - 2.0 * (qy * qy + qz * qz));
}

static void mix_control(const FlightState_t* state,
                        const MissionWaypoint* target, float motor[4])
{
    const double north_error = target->north_m - state->north_m;
    const double east_error = target->east_m - state->east_m;
    const double down_error = target->down_m - state->down_m;
    const double horizontal_distance = hypot(north_error, east_error);
    const double position_distance = sqrt(horizontal_distance * horizontal_distance +
                                          down_error * down_error);
    const double speed_scale = position_distance > 1.0e-9 ?
                               target->speed_mps / position_distance : 0.0;
    const double desired_vn = north_error * speed_scale;
    const double desired_ve = east_error * speed_scale;
    const double desired_vd = down_error * speed_scale;
    double acceleration_n = 0.8 * north_error + 1.2 * (desired_vn - state->vn_mps);
    double acceleration_e = 0.8 * east_error + 1.2 * (desired_ve - state->ve_mps);
    double acceleration_d = 0.9 * down_error + 1.4 * (desired_vd - state->vd_mps);
    double horizontal_acceleration = hypot(acceleration_n, acceleration_e);
    double roll, pitch, yaw, yaw_target;
    double forward_acceleration, right_acceleration;
    double roll_target, pitch_target, collective;
    double roll_mix, pitch_mix, yaw_mix;
    double mixed[4];
    unsigned index;

    if (horizontal_acceleration > MAX_HORIZONTAL_ACCEL_MPS2) {
        const double scale = MAX_HORIZONTAL_ACCEL_MPS2 / horizontal_acceleration;
        acceleration_n *= scale;
        acceleration_e *= scale;
    }
    acceleration_d = clamp_double(acceleration_d, -MAX_VERTICAL_ACCEL_MPS2,
                                  MAX_VERTICAL_ACCEL_MPS2);

    quaternion_to_euler(state, &roll, &pitch, &yaw);
    yaw_target = horizontal_distance > controller.completion_radius_m ?
                 atan2(east_error, north_error) : yaw;
    forward_acceleration = cos(yaw_target) * acceleration_n +
                           sin(yaw_target) * acceleration_e;
    right_acceleration = -sin(yaw_target) * acceleration_n +
                         cos(yaw_target) * acceleration_e;
    pitch_target = clamp_double(atan2(-forward_acceleration,
                                      GRAVITY_MPS2 - acceleration_d),
                                -MAX_TILT_RAD, MAX_TILT_RAD);
    roll_target = clamp_double(atan2(right_acceleration,
                                     GRAVITY_MPS2 - acceleration_d),
                               -MAX_TILT_RAD, MAX_TILT_RAD);

    collective = sqrt(clamp_double(
        NOMINAL_MASS_KG * (GRAVITY_MPS2 - acceleration_d) /
        (4.0 * NOMINAL_MOTOR_THRUST_N), 0.0, 1.0));
    roll_mix = clamp_double(0.16 * wrap_pi(roll_target - roll) -
                            0.025 * state->p_radps, -0.10, 0.10);
    pitch_mix = clamp_double(0.16 * wrap_pi(pitch_target - pitch) -
                             0.025 * state->q_radps, -0.10, 0.10);
    yaw_mix = clamp_double(0.08 * wrap_pi(yaw_target - yaw) -
                           0.02 * state->r_radps, -0.06, 0.06);

    /* X-frame signs match the generated plant's roll/pitch/yaw moments. */
    mixed[0] = collective + roll_mix + pitch_mix - yaw_mix;
    mixed[1] = collective - roll_mix + pitch_mix + yaw_mix;
    mixed[2] = collective - roll_mix - pitch_mix - yaw_mix;
    mixed[3] = collective + roll_mix - pitch_mix + yaw_mix;
    for (index = 0; index < 4; ++index) {
        const double value = clamp_double(mixed[index], 0.0, 1.0);
        motor[index] = isfinite(value) ? (float)value : 0.0f;
    }
}

int mission_controller_load(const MissionWaypoint* waypoints, unsigned count,
                            double completion_radius_m)
{
    unsigned index;
    if (!waypoints || count < 2U || count > MISSION_CONTROLLER_MAX_WAYPOINTS ||
        !isfinite(completion_radius_m) || completion_radius_m <= 0.0) {
        mission_controller_reset();
        return 0;
    }
    for (index = 0; index < count; ++index) {
        if (!waypoint_is_valid(&waypoints[index])) {
            mission_controller_reset();
            return 0;
        }
    }
    memcpy(controller.waypoints, waypoints, count * sizeof(waypoints[0]));
    controller.count = count;
    controller.target_index = 0U;
    controller.completion_radius_m = completion_radius_m;
    controller.phase = MISSION_TAKEOFF;
    controller.loaded = 1;
    controller.landed_event_pending = 0;
    return 1;
}

void mission_controller_step(const FlightState_t* state, double dt_s,
                             float motor[4])
{
    zero_motors(motor);
    if (!motor || !controller.loaded || controller.phase == MISSION_LANDED ||
        !state_is_usable(state) || !isfinite(dt_s) || dt_s <= 0.0) return;
    advance_phase_if_complete(state);
    if (controller.phase == MISSION_LANDED) return;
    mix_control(state, &controller.waypoints[controller.target_index], motor);
}

MissionPhase mission_controller_phase(void)
{
    return controller.loaded ? controller.phase : MISSION_LANDED;
}

int mission_controller_take_landed_event(void)
{
    const int pending = controller.landed_event_pending;
    controller.landed_event_pending = 0;
    return pending;
}

void mission_controller_reset(void)
{
    memset(&controller, 0, sizeof(controller));
    controller.phase = MISSION_LANDED;
}
