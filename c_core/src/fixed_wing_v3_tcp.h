#ifndef FIXED_WING_V3_TCP_H
#define FIXED_WING_V3_TCP_H

#include "flight_state.h"
#include "mission_controller.h"

/* The V3 server is Python Bridge; the compiled fixed-wing C core is the
 * protocol client.  Networking runs on its own best-effort thread so the
 * 1 ms model loop never waits for TCP, DNS, ACKs, or a renderer. */
int fixed_wing_v3_tcp_start(void);
void fixed_wing_v3_tcp_publish_state(const FlightStateV3_t* state);
void fixed_wing_v3_tcp_set_mission(const char* mission_id,
                                   const MissionWaypoint* waypoints,
                                   unsigned waypoint_count);
void fixed_wing_v3_tcp_clear_mission(void);
void fixed_wing_v3_tcp_send_event(const char* event_name, const char* mission_id);
void fixed_wing_v3_tcp_stop(void);

#endif
