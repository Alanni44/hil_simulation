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

/* V3 only appends normalized fixed-wing data after the V2 prefix.  Python
 * accepts both layouts, so existing deployed V2 model binaries remain usable
 * until rebuilt.  Rate derivatives use FRD; wind uses NED. */
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
    float p_dot_radps2;
    float q_dot_radps2;
    float r_dot_radps2;
    float wind_n_mps;
    float wind_e_mps;
    float wind_d_mps;
    float throttle;
    float aileron_rad;
    float elevator_rad;
    float rudder_rad;
    /* The active model contract's low-TAS cutoff for optional V3 aero data. */
    float tas_min_mps;
    uint8_t flight_phase;
    uint8_t control_surface_valid;
    uint16_t reserved_v3;
} FlightStateV3_t;
#pragma pack(pop)

enum {
    HIL_RUNNING = 0,
    HIL_PAUSED = 1,
    HIL_RESETTING = 2,
    HIL_ENDED = 3
};

#define FLIGHT_STATE_VERSION 2U
#define FLIGHT_STATE_V3_VERSION 3U
#define FLIGHT_STATE_SIZE sizeof(FlightState_t)
#define FLIGHT_STATE_V3_SIZE sizeof(FlightStateV3_t)

enum {
    HIL_FLIGHT_READY = 0,
    HIL_FLIGHT_TAKING_OFF = 1,
    HIL_FLIGHT_FLYING = 2,
    HIL_FLIGHT_LANDING = 3,
    HIL_FLIGHT_LANDED = 4,
    HIL_FLIGHT_FAULT = 5
};

#endif
