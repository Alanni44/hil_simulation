#ifndef MISSION_CONTROLLER_H
#define MISSION_CONTROLLER_H

#include "flight_state.h"

#define MISSION_CONTROLLER_MAX_ROUTE_WAYPOINTS 50U
#define MISSION_CONTROLLER_MAX_WAYPOINTS \
    (MISSION_CONTROLLER_MAX_ROUTE_WAYPOINTS + 1U)

typedef struct {
    double north_m;
    double east_m;
    double down_m;
    double speed_mps;
} MissionWaypoint;

typedef enum {
    MISSION_TAKEOFF = 0,
    MISSION_FLYING = 1,
    MISSION_LANDING = 2,
    MISSION_LANDED = 3
} MissionPhase;

int mission_controller_load(const MissionWaypoint* waypoints, unsigned count,
                            double completion_radius_m);
void mission_controller_step(const FlightState_t* state, double dt_s,
                             float motor[4]);
MissionPhase mission_controller_phase(void);
void mission_controller_reset(void);

#endif
