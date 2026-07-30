#include "mission_controller.h"
#include "model_rt_wrapper.h"

#include <math.h>
#include <string.h>

#define GRAVITY_MPS2 9.80665
#define MAX_HORIZONTAL_ACCEL_MPS2 2.5
#define MAX_VERTICAL_ACCEL_MPS2 2.0
#define MAX_TILT_RAD 0.45
#define MAX_VERTICAL_SPEED_MPS 1.8
#define MAX_HORIZONTAL_DECEL_MPS2 2.0
#define MAX_VERTICAL_DECEL_MPS2 1.5
#define ARRIVAL_HORIZONTAL_SPEED_MPS 0.35
#define ARRIVAL_VERTICAL_SPEED_MPS 0.25
#define CAPTURE_HORIZONTAL_SPEED_MPS 0.30
#define CAPTURE_VERTICAL_SPEED_MPS 0.25
#define CAPTURE_POSITION_GAIN 0.8
#define CAPTURE_SETTLE_TIME_S 0.50
#define CAPTURE_RELEASE_RADIUS_MULTIPLIER 2.0
#define WAYPOINT_HORIZONTAL_TOLERANCE_M 0.15
#define WAYPOINT_VERTICAL_TOLERANCE_M 0.10
#define LANDING_HORIZONTAL_SPEED_MPS 0.20
#define LANDING_HORIZONTAL_POSITION_GAIN 0.6
#define LANDING_SETTLE_TIME_S 0.75
#define INTEGRAL_ENABLE_DISTANCE_M 3.0
#define POSITION_INTEGRAL_LIMIT 2.0
#define ATTITUDE_INTEGRAL_LIMIT 0.35
#define PI 3.14159265358979323846

typedef struct {
    MissionWaypoint waypoints[MISSION_CONTROLLER_MAX_WAYPOINTS];
    unsigned count;
    unsigned target_index;
    double completion_radius_m;
    MissionPhase phase;
    int loaded;
    int landed_event_pending;
    double north_integral;
    double east_integral;
    double down_integral;
    double roll_integral;
    double pitch_integral;
    double yaw_integral;
    int capture_active;
    int capture_yaw_valid;
    double capture_yaw_rad;
    double capture_settle_time_s;
    int landing_descent_active;
    double landing_hold_down_m;
    double landing_settle_time_s;
} MissionController;

static MissionController controller;

static double clamp_double(double value, double minimum, double maximum)
{
    if (value < minimum) return minimum;
    if (value > maximum) return maximum;
    return value;
}

static double braking_speed(double distance, double deceleration, double limit)
{
    if (distance <= 0.0 || deceleration <= 0.0) return 0.0;
    return fmin(limit, sqrt(2.0 * deceleration * distance));
}

static void update_position_integrals(double north_error, double east_error,
                                      double down_error, double distance,
                                      double dt_s)
{
    if (distance > INTEGRAL_ENABLE_DISTANCE_M) {
        const double decay = fmax(0.0, 1.0 - 0.8 * dt_s);
        controller.north_integral *= decay;
        controller.east_integral *= decay;
        controller.down_integral *= decay;
        return;
    }
    controller.north_integral = clamp_double(controller.north_integral + north_error * dt_s,
                                              -POSITION_INTEGRAL_LIMIT, POSITION_INTEGRAL_LIMIT);
    controller.east_integral = clamp_double(controller.east_integral + east_error * dt_s,
                                             -POSITION_INTEGRAL_LIMIT, POSITION_INTEGRAL_LIMIT);
    controller.down_integral = clamp_double(controller.down_integral + down_error * dt_s,
                                             -POSITION_INTEGRAL_LIMIT, POSITION_INTEGRAL_LIMIT);
}

static void reset_tracking_integrals(void)
{
    controller.north_integral = 0.0;
    controller.east_integral = 0.0;
    controller.down_integral = 0.0;
    controller.roll_integral = 0.0;
    controller.pitch_integral = 0.0;
    controller.yaw_integral = 0.0;
}

static void reset_waypoint_capture(void)
{
    controller.capture_active = 0;
    controller.capture_yaw_valid = 0;
    controller.capture_yaw_rad = 0.0;
    controller.capture_settle_time_s = 0.0;
}

static int waypoint_is_settled(const FlightState_t* state,
                               const MissionWaypoint* target)
{
    const double north_error = target->north_m - state->north_m;
    const double east_error = target->east_m - state->east_m;
    const double horizontal_speed = hypot(state->vn_mps, state->ve_mps);
    return hypot(north_error, east_error) <= WAYPOINT_HORIZONTAL_TOLERANCE_M &&
           fabs(target->down_m - state->down_m) <= WAYPOINT_VERTICAL_TOLERANCE_M &&
           horizontal_speed <= ARRIVAL_HORIZONTAL_SPEED_MPS &&
           fabs(state->vd_mps) <= ARRIVAL_VERTICAL_SPEED_MPS;
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

static void advance_phase_if_complete(const FlightState_t* state, double dt_s)
{
    const MissionWaypoint* target = &controller.waypoints[controller.target_index];
    const double horizontal_speed = hypot(state->vn_mps, state->ve_mps);
    const double distance = distance_to(state, target);
    if (controller.phase == MISSION_LANDING && !controller.landing_descent_active) {
        const double horizontal_error = hypot(target->north_m - state->north_m,
                                              target->east_m - state->east_m);
        if (horizontal_error <= WAYPOINT_HORIZONTAL_TOLERANCE_M &&
            horizontal_speed <= LANDING_HORIZONTAL_SPEED_MPS &&
            fabs(state->vd_mps) <= ARRIVAL_VERTICAL_SPEED_MPS) {
            controller.landing_settle_time_s += dt_s;
        } else {
            controller.landing_settle_time_s = 0.0;
        }
        if (controller.landing_settle_time_s >= LANDING_SETTLE_TIME_S) {
            controller.landing_descent_active = 1;
            reset_tracking_integrals();
            reset_waypoint_capture();
        }
        return;
    }
    if (!controller.capture_active && distance >= controller.completion_radius_m) return;
    if (controller.capture_active &&
        distance >= CAPTURE_RELEASE_RADIUS_MULTIPLIER * controller.completion_radius_m) {
        reset_waypoint_capture();
        return;
    }
    /* Enter a separate point-capture mode.  While it is active the controller
     * brakes and holds this point with a fixed heading instead of chasing an
     * error vector that reverses every time the aircraft crosses the point. */
    if (!controller.capture_active) {
        controller.capture_active = 1;
        controller.capture_settle_time_s = 0.0;
        controller.capture_yaw_valid = 0;
        reset_tracking_integrals();
    }
    if (waypoint_is_settled(state, target)) {
        controller.capture_settle_time_s += dt_s;
    } else {
        controller.capture_settle_time_s = 0.0;
    }
    if (controller.capture_settle_time_s < CAPTURE_SETTLE_TIME_S) return;

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
            controller.landing_descent_active = 0;
            controller.landing_hold_down_m = state->down_m;
            controller.landing_settle_time_s = 0.0;
        }
    } else if (controller.phase == MISSION_LANDING) {
        controller.phase = MISSION_LANDED;
        controller.landed_event_pending = 1;
    }
    reset_tracking_integrals();
    reset_waypoint_capture();
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
                        const MissionWaypoint* target, double dt_s,
                        float motor[4])
{
    const double north_error = target->north_m - state->north_m;
    const double east_error = target->east_m - state->east_m;
    const double down_target_m = controller.phase == MISSION_LANDING &&
                                 !controller.landing_descent_active ?
                                 controller.landing_hold_down_m : target->down_m;
    const double down_error = down_target_m - state->down_m;
    const double horizontal_distance = hypot(north_error, east_error);
    const double position_distance = hypot(horizontal_distance, down_error);
    double horizontal_speed_limit = braking_speed(horizontal_distance,
                                                  MAX_HORIZONTAL_DECEL_MPS2,
                                                  target->speed_mps);
    double vertical_speed_limit = braking_speed(fabs(down_error),
                                                MAX_VERTICAL_DECEL_MPS2,
                                                fmin(target->speed_mps,
                                                     MAX_VERTICAL_SPEED_MPS));
    double desired_vn = horizontal_distance > 1.0e-9 ?
                        north_error * horizontal_speed_limit / horizontal_distance : 0.0;
    double desired_ve = horizontal_distance > 1.0e-9 ?
                        east_error * horizontal_speed_limit / horizontal_distance : 0.0;
    double desired_vd = down_error >= 0.0 ? vertical_speed_limit : -vertical_speed_limit;
    double acceleration_n;
    double acceleration_e;
    double acceleration_d;
    double horizontal_acceleration;
    double roll, pitch, yaw, yaw_target;
    double forward_acceleration, right_acceleration;
    double roll_target, pitch_target, collective;
    double roll_mix, pitch_mix, yaw_mix;
    double mass_kg, thrust_coefficient_n, motor_efficiency;
    int holding_position;
    double mixed[4];
    unsigned index;

    holding_position = controller.capture_active || controller.phase == MISSION_LANDING;
    if (holding_position) {
        /* Small, non-oscillatory position hold: velocity falls linearly to
         * zero at the point and cannot command another high-speed pass. */
        desired_vn = clamp_double(CAPTURE_POSITION_GAIN * north_error,
                                  -CAPTURE_HORIZONTAL_SPEED_MPS,
                                  CAPTURE_HORIZONTAL_SPEED_MPS);
        desired_ve = clamp_double(CAPTURE_POSITION_GAIN * east_error,
                                  -CAPTURE_HORIZONTAL_SPEED_MPS,
                                  CAPTURE_HORIZONTAL_SPEED_MPS);
        desired_vd = clamp_double(CAPTURE_POSITION_GAIN * down_error,
                                  -CAPTURE_VERTICAL_SPEED_MPS,
                                  CAPTURE_VERTICAL_SPEED_MPS);
        if (controller.phase == MISSION_LANDING && controller.landing_descent_active) {
            desired_vn = clamp_double(LANDING_HORIZONTAL_POSITION_GAIN * north_error,
                                      -LANDING_HORIZONTAL_SPEED_MPS,
                                      LANDING_HORIZONTAL_SPEED_MPS);
            desired_ve = clamp_double(LANDING_HORIZONTAL_POSITION_GAIN * east_error,
                                      -LANDING_HORIZONTAL_SPEED_MPS,
                                      LANDING_HORIZONTAL_SPEED_MPS);
            desired_vd = down_error >= 0.0 ? vertical_speed_limit : -vertical_speed_limit;
        }
        horizontal_speed_limit = 0.0;
    } else {
        update_position_integrals(north_error, east_error, down_error,
                                  position_distance, dt_s);
    }
    acceleration_n = 1.6 * (desired_vn - state->vn_mps) +
                     0.18 * controller.north_integral;
    acceleration_e = 1.6 * (desired_ve - state->ve_mps) +
                     0.18 * controller.east_integral;
    acceleration_d = 1.8 * (desired_vd - state->vd_mps) +
                     0.22 * controller.down_integral;
    horizontal_acceleration = hypot(acceleration_n, acceleration_e);

    if (horizontal_acceleration > MAX_HORIZONTAL_ACCEL_MPS2) {
        const double scale = MAX_HORIZONTAL_ACCEL_MPS2 / horizontal_acceleration;
        acceleration_n *= scale;
        acceleration_e *= scale;
    }
    acceleration_d = clamp_double(acceleration_d, -MAX_VERTICAL_ACCEL_MPS2,
                                  MAX_VERTICAL_ACCEL_MPS2);

    quaternion_to_euler(state, &roll, &pitch, &yaw);
    if (holding_position) {
        if (!controller.capture_yaw_valid) {
            controller.capture_yaw_rad = yaw;
            controller.capture_yaw_valid = 1;
        }
        yaw_target = controller.capture_yaw_rad;
    } else {
        yaw_target = horizontal_speed_limit > 0.05 ? atan2(east_error, north_error) : yaw;
    }
    /* The NED acceleration is transformed using the measured attitude, not
     * the desired heading; this prevents a heading step at a corner from
     * rotating the requested translation into a sideways command. */
    forward_acceleration = cos(yaw) * acceleration_n +
                           sin(yaw) * acceleration_e;
    right_acceleration = -sin(yaw) * acceleration_n +
                         cos(yaw) * acceleration_e;
    pitch_target = clamp_double(atan2(-forward_acceleration,
                                      GRAVITY_MPS2 - acceleration_d),
                                -MAX_TILT_RAD, MAX_TILT_RAD);
    roll_target = clamp_double(atan2(right_acceleration,
                                     GRAVITY_MPS2 - acceleration_d),
                               -MAX_TILT_RAD, MAX_TILT_RAD);

    mass_kg = isfinite(uav_mass_kg) && uav_mass_kg > 0.0 ? uav_mass_kg : 1.5;
    thrust_coefficient_n = isfinite(uav_thrust_coefficient_n) &&
                           uav_thrust_coefficient_n > 0.0 ?
                           uav_thrust_coefficient_n : 4.2;
    motor_efficiency = isfinite(uav_motor_efficiency) && uav_motor_efficiency > 0.0 ?
                        uav_motor_efficiency : 1.0;
    collective = sqrt(clamp_double(
        mass_kg * (GRAVITY_MPS2 - acceleration_d) /
        (4.0 * thrust_coefficient_n * motor_efficiency * motor_efficiency), 0.0, 1.0));

    controller.roll_integral = clamp_double(controller.roll_integral +
                                            wrap_pi(roll_target - roll) * dt_s,
                                            -ATTITUDE_INTEGRAL_LIMIT, ATTITUDE_INTEGRAL_LIMIT);
    controller.pitch_integral = clamp_double(controller.pitch_integral +
                                             wrap_pi(pitch_target - pitch) * dt_s,
                                             -ATTITUDE_INTEGRAL_LIMIT, ATTITUDE_INTEGRAL_LIMIT);
    controller.yaw_integral = clamp_double(controller.yaw_integral +
                                           wrap_pi(yaw_target - yaw) * dt_s,
                                           -ATTITUDE_INTEGRAL_LIMIT, ATTITUDE_INTEGRAL_LIMIT);
    roll_mix = clamp_double(0.18 * wrap_pi(roll_target - roll) +
                            0.035 * controller.roll_integral -
                            0.035 * state->p_radps, -0.10, 0.10);
    pitch_mix = clamp_double(0.18 * wrap_pi(pitch_target - pitch) +
                             0.035 * controller.pitch_integral -
                             0.035 * state->q_radps, -0.10, 0.10);
    yaw_mix = clamp_double(0.09 * wrap_pi(yaw_target - yaw) +
                           0.02 * controller.yaw_integral -
                           0.025 * state->r_radps, -0.06, 0.06);

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
    reset_tracking_integrals();
    reset_waypoint_capture();
    controller.landing_descent_active = 0;
    controller.landing_hold_down_m = 0.0;
    controller.landing_settle_time_s = 0.0;
    return 1;
}

void mission_controller_step(const FlightState_t* state, double dt_s,
                             float motor[4])
{
    zero_motors(motor);
    if (!motor || !controller.loaded || controller.phase == MISSION_LANDED ||
        !state_is_usable(state) || !isfinite(dt_s) || dt_s <= 0.0) return;
    advance_phase_if_complete(state, dt_s);
    if (controller.phase == MISSION_LANDED) return;
    mix_control(state, &controller.waypoints[controller.target_index], dt_s, motor);
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
