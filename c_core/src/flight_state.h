#ifndef FLIGHT_STATE_H
#define FLIGHT_STATE_H

/* Fixed C-core to Python normalized state contract.  It is intentionally
 * independent of any supplied model ABI. */
#include <stdint.h>

#pragma pack(push, 1)
typedef struct {
    uint32_t version;
    uint64_t sequence;
    double sim_time_s;
    double north_m;
    double east_m;
    double down_m;
    float vn_mps;
    float ve_mps;
    float vd_mps;
    float q_w;
    float q_x;
    float q_y;
    float q_z;
    float p_radps;
    float q_radps;
    float r_radps;
    float ax_mps2;
    float ay_mps2;
    float az_mps2;
    uint8_t airborne;
    uint8_t lifecycle;
    uint16_t reserved;
} FlightState_t;
#pragma pack(pop)

enum {
    HIL_RUNNING = 0,
    HIL_PAUSED = 1,
    HIL_RESETTING = 2,
    HIL_ENDED = 3
};

#define FLIGHT_STATE_VERSION 2U
#define FLIGHT_STATE_SIZE sizeof(FlightState_t)

#endif
