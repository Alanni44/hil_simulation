#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "mission_controller.h"

static FlightState_t state_at(double north_m, double east_m, double down_m)
{
    FlightState_t state;
    memset(&state, 0, sizeof(state));
    state.q_w = 1.0f;
    state.north_m = north_m;
    state.east_m = east_m;
    state.down_m = down_m;
    return state;
}

static void assert_bounded(const float motor[4])
{
    unsigned index;
    for (index = 0; index < 4; ++index) {
        assert(isfinite(motor[index]));
        assert(motor[index] >= 0.0f);
        assert(motor[index] <= 1.0f);
    }
}

static void assert_zero(const float motor[4])
{
    unsigned index;
    for (index = 0; index < 4; ++index) assert(motor[index] == 0.0f);
}

int main(void)
{
    const MissionWaypoint mission[] = {
        {0.0, 0.0, -20.0, 2.0},
        {40.0, 0.0, -20.0, 5.0},
        {0.0, 20.0, -20.0, 5.0},
        {40.0, 20.0, -20.0, 5.0},
        {40.0, 20.0, 0.0, 1.5}
    };
    FlightState_t state = state_at(0.0, 0.0, 0.0);
    MissionWaypoint maximum_mission[MISSION_CONTROLLER_MAX_WAYPOINTS];
    float motor[4] = {1.0f, 1.0f, 1.0f, 1.0f};
    unsigned index;

    mission_controller_reset();
    mission_controller_step(&state, 0.001, motor);
    assert_zero(motor);

    assert(mission_controller_load(mission,
                                   (unsigned)(sizeof(mission) / sizeof(mission[0])),
                                   1.0));
    assert(mission_controller_phase() == MISSION_TAKEOFF);

    mission_controller_step(&state, 0.001, motor);
    assert(mission_controller_phase() == MISSION_TAKEOFF);
    assert_bounded(motor);

    state = state_at(0.0, 0.0, -19.0);
    mission_controller_step(&state, 0.001, motor);
    assert(mission_controller_phase() == MISSION_TAKEOFF);

    state = state_at(0.0, 0.0, -20.0);
    mission_controller_step(&state, 0.001, motor);
    assert(mission_controller_phase() == MISSION_FLYING);
    assert_bounded(motor);

    state = state_at(40.0, 0.0, -20.0);
    mission_controller_step(&state, 0.001, motor);
    assert(mission_controller_phase() == MISSION_FLYING);
    assert_bounded(motor);

    state = state_at(0.0, 20.0, -20.0);
    mission_controller_step(&state, 0.001, motor);
    assert(mission_controller_phase() == MISSION_FLYING);

    state = state_at(40.0, 20.0, -20.0);
    mission_controller_step(&state, 0.001, motor);
    assert(mission_controller_phase() == MISSION_LANDING);
    assert_bounded(motor);

    state = state_at(40.0, 20.0, 0.0);
    mission_controller_step(&state, 0.001, motor);
    assert(mission_controller_phase() == MISSION_LANDED);
    assert_zero(motor);

    mission_controller_reset();
    mission_controller_step(&state, 0.001, motor);
    assert(mission_controller_phase() == MISSION_LANDED);
    assert_zero(motor);

    for (index = 0; index < MISSION_CONTROLLER_MAX_WAYPOINTS; ++index) {
        maximum_mission[index].north_m = (double)index;
        maximum_mission[index].east_m = 0.0;
        maximum_mission[index].down_m =
            index == MISSION_CONTROLLER_MAX_ROUTE_WAYPOINTS ? 0.0 : -20.0;
        maximum_mission[index].speed_mps = 2.0;
    }
    assert(mission_controller_load(maximum_mission,
                                   MISSION_CONTROLLER_MAX_WAYPOINTS, 1.0));
    assert(mission_controller_phase() == MISSION_TAKEOFF);

    puts("mission_controller: all tests passed");
    return 0;
}
