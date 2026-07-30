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

static void run_controller_steps(const FlightState_t* state, float motor[4],
                                 unsigned count)
{
    unsigned index;
    for (index = 0; index < count; ++index)
        mission_controller_step(state, 0.001, motor);
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
    int runtime_lifecycle = HIL_RUNNING;
    unsigned ended_transitions = 0U;

    mission_controller_reset();
    mission_controller_configure_vehicle(1.5, 4.2, 1.0);
    mission_controller_step(&state, 0.001, motor);
    assert_zero(motor);

    assert(mission_controller_load(mission,
                                   (unsigned)(sizeof(mission) / sizeof(mission[0])),
                                   1.0));
    assert(mission_controller_phase() == MISSION_TAKEOFF);

    /* Invalid optional vehicle parameters fall back safely without any
     * dependency on model-generated exported globals. */
    mission_controller_configure_vehicle(NAN, -1.0, 0.0);
    mission_controller_step(&state, 0.001, motor);
    assert_bounded(motor);

    mission_controller_step(&state, 0.001, motor);
    assert(mission_controller_phase() == MISSION_TAKEOFF);
    assert_bounded(motor);

    state = state_at(0.0, 0.0, -19.0);
    mission_controller_step(&state, 0.001, motor);
    assert(mission_controller_phase() == MISSION_TAKEOFF);

    state = state_at(0.0, 0.0, -20.0);
    run_controller_steps(&state, motor, 600U);
    assert(mission_controller_phase() == MISSION_FLYING);
    assert_bounded(motor);

    state = state_at(40.0, 0.0, -20.0);
    run_controller_steps(&state, motor, 600U);
    assert(mission_controller_phase() == MISSION_FLYING);
    assert_bounded(motor);

    state = state_at(0.0, 20.0, -20.0);
    run_controller_steps(&state, motor, 600U);
    assert(mission_controller_phase() == MISSION_FLYING);

    state = state_at(40.0, 20.0, -20.0);
    run_controller_steps(&state, motor, 600U);
    assert(mission_controller_phase() == MISSION_LANDING);
    assert_bounded(motor);

    /* Landing waits for a horizontal hold before it starts descending. */
    run_controller_steps(&state, motor, 800U);
    assert(mission_controller_phase() == MISSION_LANDING);

    state = state_at(40.0, 20.0, 0.0);
    run_controller_steps(&state, motor, 600U);
    assert(mission_controller_phase() == MISSION_LANDED);
    assert_zero(motor);
    if (mission_controller_take_landed_event()) {
        runtime_lifecycle = HIL_ENDED;
        ++ended_transitions;
    }
    if (mission_controller_take_landed_event()) {
        runtime_lifecycle = HIL_ENDED;
        ++ended_transitions;
    }
    assert(runtime_lifecycle == HIL_ENDED);
    assert(ended_transitions == 1U);

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
